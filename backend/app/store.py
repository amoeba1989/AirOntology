import time
import httpx
from rdflib import Graph, Literal, RDF, XSD
from .domain import CU, SCHEMA, STATE, uri, track_graph


class FusekiStore:
    def __init__(self, settings):
        self.settings = settings
        self.client = httpx.Client(timeout=8, trust_env=False)
        self.url = settings.fuseki_url.rstrip('/')

    def close(self):
        self.client.close()

    def query(self, sparql):
        response = self.client.post(self.url + '/query', data={'query': sparql},
                                    headers={'Accept': 'application/sparql-results+json'})
        response.raise_for_status()
        return response.json()

    def update(self, sparql):
        response = self.client.post(self.url + '/update', content=sparql,
                                    headers={'Content-Type': 'application/sparql-update'})
        response.raise_for_status()

    def ready(self):
        return self.query('ASK {}')['boolean']

    def initialize(self):
        definition = Graph().parse(self.settings.ontology_dir / 'cu_ontology.ttl', format='turtle')
        initial = Graph().parse(self.settings.ontology_dir / 'initial_data.ttl', format='turtle')
        # 当前配置是阵地属性的唯一来源，避免重启后同时存在多个位置值。
        point = uri(self.settings.position_id)
        initial.add((point, RDF.type, CU.Position))
        for name, value, dtype in [('name', self.settings.position_name, XSD.string),
                                   ('lon', self.settings.position_lon, XSD.double),
                                   ('lat', self.settings.position_lat, XSD.double)]:
            initial.add((point, CU[name], Literal(value, datatype=dtype)))
        schema = definition + initial
        self.update(f'CLEAR SILENT GRAPH <{SCHEMA}>; INSERT DATA {{ GRAPH <{SCHEMA}> {{ {schema.serialize(format="nt")} }} }}')

    def write_track(self, track):
        subject = uri(track.target_id).n3()
        incoming = Literal(track.timestamp, datatype=XSD.dateTime).n3()
        triples = track_graph(track, self.settings).serialize(format='nt')
        # 单次 DELETE/INSERT，数据库中比较观测时间，重启后也不会接受旧报文。
        self.update(f'''PREFIX cu: <{CU}>
DELETE {{ GRAPH <{STATE}> {{ {subject} ?p ?o }} }}
INSERT {{ GRAPH <{STATE}> {{ {triples} }} }}
WHERE {{
 FILTER NOT EXISTS {{ GRAPH <{STATE}> {{ {subject} cu:timestamp ?old }} FILTER (?old >= {incoming}) }}
 OPTIONAL {{ GRAPH <{STATE}> {{ {subject} ?p ?o }} }}
}}''')

    def situation(self, target_id=None):
        target_filter = f'FILTER (?target = {uri(target_id).n3()})' if target_id else ''
        result = self.query(f'''PREFIX cu: <{CU}>
SELECT ?target ?name ?lon ?lat ?speed ?distance ?timestamp ?level ?position WHERE {{
 GRAPH <{STATE}> {{ ?target a cu:BlueDevice; cu:name ?name; cu:lon ?lon; cu:lat ?lat;
 cu:speed ?speed; cu:distanceToPosition ?distance; cu:timestamp ?timestamp;
 cu:hasDistanceLevel ?level; cu:monitoredAgainst ?position . {target_filter} }}
}} ORDER BY ?target''')
        return [{key: value['value'] for key, value in row.items()} for row in result['results']['bindings']]

    def target_ttl(self, target_id):
        target = uri(target_id).n3()
        response = self.client.post(self.url + '/query', data={'query': f'''
CONSTRUCT {{ ?s ?p ?o }} WHERE {{
 {{ GRAPH <{STATE}> {{ BIND({target} AS ?s) ?s ?p ?o }} }} UNION
 {{ GRAPH <{STATE}> {{ {target} ?rel ?s }} GRAPH <{SCHEMA}> {{ ?s ?p ?o }} }}
}}'''}, headers={'Accept': 'text/turtle'})
        response.raise_for_status()
        return response.text

    def initialize_with_retry(self):
        for attempt in range(30):
            try:
                self.initialize()
                return
            except httpx.HTTPError:
                if attempt == 29:
                    raise
                time.sleep(1)
