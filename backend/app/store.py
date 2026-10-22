import threading
import time
from datetime import datetime, timezone
import httpx
from rdflib import Graph, Literal, RDF, XSD, URIRef
from .domain import CU, SCHEMA, STATE, HISTORY, CONFIG, uri, graph, add_values, observation_graphs, Track
from .models import RuntimeConfig


class ConfigConflict(ValueError):
    pass


class FusekiStore:
    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.Client(timeout=15, trust_env=False)
        self.url = settings.fuseki_url.rstrip('/')
        self.lock = threading.RLock()
        self.config = settings.initial_config()

    def close(self):
        self.client.close()

    def query(self, sparql):
        response = self.client.post(self.url + '/query', data={'query': sparql},
                                    headers={'Accept': 'application/sparql-results+json'})
        response.raise_for_status()
        return response.json()

    def construct(self, sparql):
        response = self.client.post(self.url + '/query', data={'query': sparql}, headers={'Accept': 'text/turtle'})
        response.raise_for_status()
        return graph().parse(data=response.text, format='turtle')

    def update(self, sparql):
        response = self.client.post(self.url + '/update', content=sparql,
                                    headers={'Content-Type': 'application/sparql-update'})
        response.raise_for_status()

    def ready(self):
        return self.query('ASK {}')['boolean']

    def config_graph(self, config):
        result = graph()
        add_values(result, CU.runtime, [('configJson', config.model_dump_json(), XSD.string)])
        for point in config.positions:
            subject = uri(point.id)
            result.add((subject, RDF.type, CU.Position))
            add_values(result, subject, [('name', point.name, XSD.string), ('lon', point.lon, XSD.double), ('lat', point.lat, XSD.double)])
        return result

    def get_config(self):
        with self.lock:
            return {'version': self.config.version, 'config': self.config.model_dump()}

    def set_config(self, config, expected_version):
        with self.lock:
            if expected_version != self.config.version:
                raise ConfigConflict('配置已被更新，请重新加载后再保存')
            ids = {p.id for p in config.positions}
            targets = self.query(f'SELECT ?s WHERE {{ GRAPH <{STATE}> {{ ?s a <{CU.BlueDevice}> }} }}')['results']['bindings']
            if any(row['s']['value'] in {str(uri(i)) for i in ids} for row in targets):
                raise ValueError('阵地编号不能与已有无人机编号相同')
            triples = self.config_graph(config).serialize(format='nt')
            self.update(f'CLEAR SILENT GRAPH <{CONFIG}>; INSERT DATA {{ GRAPH <{CONFIG}> {{ {triples} }} }}')
            self.config = config.model_copy(deep=True)
            # 配置只影响下一条观测，旧评估保留当时的规则和阵地坐标。
            for row in targets:
                self.prune(URIRef(row['s']['value']))
            return self.get_config()

    def initialize(self):
        with self.lock:
            definition = Graph().parse(self.settings.ontology_dir / 'cu_ontology.ttl', format='turtle')
            initial = Graph().parse(self.settings.ontology_dir / 'initial_data.ttl', format='turtle')
            schema = definition + initial + Graph().parse(self.settings.ontology_dir / 'attention_policy.ttl', format='turtle')
            self.update(f'CLEAR SILENT GRAPH <{SCHEMA}>; INSERT DATA {{ GRAPH <{SCHEMA}> {{ {schema.serialize(format="nt")} }} }}')
            result = self.query(f'SELECT ?json WHERE {{ GRAPH <{CONFIG}> {{ <{CU.runtime}> <{CU.configJson}> ?json }} }}')
            rows = result['results']['bindings']
            if rows:
                self.config = RuntimeConfig.model_validate_json(rows[0]['json']['value'])
            else:
                triples = self.config_graph(self.config).serialize(format='nt')
                self.update(f'INSERT DATA {{ GRAPH <{CONFIG}> {{ {triples} }} }}')
            # 第一版迁移：保留旧目标最新位置，补齐观测和独立评估，不删除历史图。
            legacy = self.query(f'''PREFIX cu: <{CU}>
SELECT ?target ?lon ?lat ?speed ?time WHERE {{ GRAPH <{STATE}> {{
 ?target a cu:BlueDevice; cu:lon ?lon; cu:lat ?lat; cu:speed ?speed; cu:timestamp ?time .
 FILTER NOT EXISTS {{ ?target cu:latestObservation ?obs }}
}} }}''')['results']['bindings']
            for row in legacy:
                self.write_track(Track(target_id=row['target']['value'].split('#')[-1],
                    lon=row['lon']['value'], lat=row['lat']['value'], speed=row['speed']['value'],
                    timestamp=row['time']['value'], source='第一版迁移'))

    def write_track(self, track):
        with self.lock:
            if track.target_id in {p.id for p in self.config.positions}:
                raise ValueError('目标编号不能与阵地编号相同')
            subject = uri(track.target_id).n3()
            incoming = Literal(track.timestamp, datatype=XSD.dateTime).n3()
            state, history = observation_graphs(track, self.config)
            # 同一事务写当前指针与完整观测/评估；旧报文不会产生历史记录。
            self.update(f'''PREFIX cu: <{CU}>
DELETE {{ GRAPH <{STATE}> {{ {subject} ?p ?o }} }}
INSERT {{ GRAPH <{STATE}> {{ {state.serialize(format='nt')} }}
          GRAPH <{HISTORY}> {{ {history.serialize(format='nt')} }} }}
WHERE {{
 FILTER NOT EXISTS {{ GRAPH <{STATE}> {{ {subject} cu:latestObservation ?known; cu:timestamp ?old }} FILTER (?old >= {incoming}) }}
 OPTIONAL {{ GRAPH <{STATE}> {{ {subject} ?p ?o }} }}
}}''')
            self.prune(uri(track.target_id))

    def prune(self, target):
        # 先确定待清理的不可变观测ID，再删除关联评估和观测。
        # 不在DELETE子查询中依赖OFFSET，以保持不同SPARQL实现的行为一致。
        result = self.query(f"""PREFIX cu: <{CU}>
SELECT ?obs WHERE {{ GRAPH <{HISTORY}> {{
 ?obs a cu:Observation; cu:ofTarget {target.n3()}; cu:timestamp ?time
}} }} ORDER BY DESC(?time) OFFSET {self.config.history_limit}""")
        obsolete = result['results']['bindings']
        if not obsolete:
            return
        values = ' '.join(URIRef(row['obs']['value']).n3() for row in obsolete)
        self.update(f"""PREFIX cu: <{CU}>
DELETE {{ GRAPH <{HISTORY}> {{ ?assessment ?p ?o }} }} WHERE {{
 VALUES ?obs {{ {values} }}
 GRAPH <{HISTORY}> {{ ?assessment cu:basedOnObservation ?obs; ?p ?o }}
}};
DELETE {{ GRAPH <{HISTORY}> {{ ?obs ?p ?o }} }} WHERE {{
 VALUES ?obs {{ {values} }} GRAPH <{HISTORY}> {{ ?obs ?p ?o }}
}};
DELETE {{ GRAPH <{HISTORY}> {{ ?rule ?p ?o }} }} WHERE {{
 GRAPH <{HISTORY}> {{ ?rule a cu:DistanceRule; ?p ?o }}
 FILTER NOT EXISTS {{ GRAPH <{HISTORY}> {{ ?assessment cu:usedRule ?rule }} }}
}}""")

    def snapshot_graph(self, at=None, target_id=None):
        target_filter = f'FILTER (?target = {uri(target_id).n3()})' if target_id else ''
        if at:
            cutoff = Literal(at, datatype=XSD.dateTime).n3()
            roots = f'''{{ SELECT ?target (MAX(?time) AS ?latest) WHERE {{
 GRAPH <{HISTORY}> {{ ?record a cu:Observation; cu:ofTarget ?target; cu:timestamp ?time }}
 FILTER (?time <= {cutoff}) {target_filter}
 }} GROUP BY ?target }}
 GRAPH <{HISTORY}> {{ ?obs a cu:Observation; cu:ofTarget ?target; cu:timestamp ?latest .
 ?assessment cu:basedOnObservation ?obs }}
 FILTER (?latest <= {cutoff}) {target_filter}'''
        else:
            roots = f'GRAPH <{STATE}> {{ ?target cu:latestObservation ?obs; cu:latestAssessment ?assessment . {target_filter} }}'
        return self.construct(f'''PREFIX cu: <{CU}>
CONSTRUCT {{ ?target cu:latestObservation ?obs; cu:latestAssessment ?assessment . ?s ?p ?o }} WHERE {{
 {roots}
 GRAPH <{HISTORY}> {{ ?assessment cu:usedRule ?rule }}
 VALUES ?which {{ 1 2 3 }}
 BIND(IF(?which=1, ?obs, IF(?which=2, ?assessment, ?rule)) AS ?s)
 GRAPH <{HISTORY}> {{ ?s ?p ?o }}
}}''')

    def history_graph(self, target_id, limit):
        return self.construct(f'''PREFIX cu: <{CU}>
CONSTRUCT {{ ?s ?p ?o }} WHERE {{
 {{ SELECT ?obs WHERE {{ GRAPH <{HISTORY}> {{ ?obs a cu:Observation; cu:ofTarget {uri(target_id).n3()}; cu:timestamp ?time }} }}
 ORDER BY DESC(?time) LIMIT {limit} }}
 GRAPH <{HISTORY}> {{ ?obs cu:ofTarget {uri(target_id).n3()} }}
 GRAPH <{HISTORY}> {{ ?assessment cu:basedOnObservation ?obs; cu:usedRule ?rule }}
 VALUES ?which {{ 1 2 3 }}
 BIND(IF(?which=1, ?obs, IF(?which=2, ?assessment, ?rule)) AS ?s)
 GRAPH <{HISTORY}> {{ ?s ?p ?o }}
}}''')

    def assessment_graph(self, assessment_id):
        assessment = uri(assessment_id).n3()
        return self.construct(f'''PREFIX cu: <{CU}>
CONSTRUCT {{ ?s ?p ?o }} WHERE {{
 GRAPH <{HISTORY}> {{ {assessment} a cu:Assessment; cu:basedOnObservation ?obs; cu:usedRule ?rule }}
 VALUES ?which {{ 1 2 3 }}
 BIND(IF(?which=1, {assessment}, IF(?which=2, ?obs, ?rule)) AS ?s)
 GRAPH <{HISTORY}> {{ ?s ?p ?o }}
}}''')

    def target_ttl(self, target_id, at=None):
        result = self.snapshot_graph(at, target_id)
        result += self.construct(f'CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{SCHEMA}> {{ ?s ?p ?o }} }}')
        # 历史阵地坐标由评估记录中的positionLon/positionLat提供，避免混入当前坐标。
        return result.serialize(format='turtle')

    def initialize_with_retry(self):
        for attempt in range(30):
            try:
                self.initialize()
                return
            except httpx.HTTPError:
                if attempt == 29:
                    raise
                time.sleep(1)
