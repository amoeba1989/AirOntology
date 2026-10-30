"""Bounded RDF explorer. No inferred relationships or client supplied SPARQL."""
from datetime import datetime, timezone
from rdflib import Graph, URIRef, Literal, BNode, RDF, RDFS
from . import learning
from .domain import CU, STATE, HISTORY


def topology_view(store, directory):
    model = Graph().parse(directory / 'cu_ontology.ttl', format='turtle')
    shapes = Graph().parse(directory / 'shapes.ttl', format='turtle')
    # Preserve graph provenance and bound reads on the server, including evidence.
    query = f'''SELECT DISTINCT ?g ?s ?p ?o WHERE {{
      {{ VALUES ?g {{ <urn:airontology:state> <urn:airontology:config>
          <urn:airontology:devices> <urn:airontology:evidence> }} GRAPH ?g {{ ?s ?p ?o }} }}
      UNION {{ GRAPH <{STATE}> {{ ?target ?pointer ?s }}
        VALUES ?pointer {{ <{CU.latestObservation}> <{CU.latestAssessment}> }}
        BIND(<{HISTORY}> AS ?g) GRAPH ?g {{ ?s ?p ?o }} }}
      UNION {{ GRAPH <{STATE}> {{ ?target <{CU.latestAssessment}> ?assessment }}
        GRAPH <{HISTORY}> {{ ?assessment <{CU.usedRule}> ?s . ?s ?p ?o }}
        BIND(<{HISTORY}> AS ?g) }}
    }} ORDER BY ?g ?s ?p ?o LIMIT 4001'''
    rows = store.query(query)['results']['bindings']
    truncated = len(rows) > 4000
    rows = rows[:4000]
    facts = Graph().parse(directory / 'initial_data.ttl', format='turtle')
    triples = []
    for row in rows:
        s, p, o = row['s'], row['p'], row['o']
        if s['type'] != 'uri':
            continue
        value = (URIRef(o['value']) if o['type'] == 'uri' else
                 BNode(o['value']) if o['type'] == 'bnode' else
                 Literal(o['value'], lang=o.get('xml:lang'), datatype=o.get('datatype')))
        facts.add((URIRef(s['value']), URIRef(p['value']), value))
        triples.append({'subject': s['value'], 'predicate': p['value'], 'object': o['value'],
                        'literal': o['type'] not in ('uri', 'bnode'), 'graph': row['g']['value'],
                        'datatype': o.get('datatype', ''), 'language': o.get('xml:lang', '')})
    for s, p, o in Graph().parse(directory / 'initial_data.ttl', format='turtle'):
        triples.append({'subject': str(s), 'predicate': str(p), 'object': str(o),
                        'literal': isinstance(o, Literal), 'graph': 'initial_data.ttl'})
    terms = learning.dictionary(model)
    classes = {t['uri'] for t in terms if t['kind'] == '类'}
    def title(uri):
        subject = URIRef(uri)
        return str(facts.value(subject, CU.name) or model.value(subject, RDFS.label)
                   or facts.value(subject, RDFS.label) or uri.rsplit('#', 1)[-1].rsplit(':', 1)[-1])
    nodes = []
    for term in terms:
        constraints = []
        for shape in shapes.subjects(learning.SH.targetClass, URIRef(term['uri'])):
            for prop in shapes.objects(shape, learning.SH.property):
                constraints.append({str(p).split('#')[-1]: str(o) for p, o in shapes.predicate_objects(prop)})
        nodes.append({**term, 'kind': 'class' if term['uri'] in classes else 'property',
                      'count': len(set(facts.subjects(RDF.type, URIRef(term['uri'])))),
                      'constraints': constraints})
    schema_edges = []
    for s, p, o in model:
        if p == RDFS.subClassOf and isinstance(o, URIRef):
            schema_edges.append({'source': str(s), 'target': str(o), 'predicate': str(p), 'label': '继承', 'kind': 'inheritance'})
    for term in terms:
        if term['kind'] == '对象属性':
            for domain in term['domain']:
                for range_ in term['range']:
                    schema_edges.append({'source': domain, 'target': range_, 'predicate': term['uri'], 'label': term['label'], 'kind': 'object'})
    subjects = {str(s) for s in facts.subjects() if isinstance(s, URIRef)} - classes
    individuals = []
    for uri in sorted(subjects):
        types = sorted(str(v) for v in facts.objects(URIRef(uri), RDF.type))
        individuals.append({'uri': uri, 'label': title(uri), 'kind': 'individual', 'types': types})
    edges = [{'source': t['subject'], 'target': t['object'], 'predicate': t['predicate'],
              'label': '类型' if t['predicate'] == str(RDF.type) else title(t['predicate']),
              'kind': 'type' if t['predicate'] == str(RDF.type) else 'object', 'graph': t['graph']}
             for t in triples if not t['literal']]
    return {'terms': nodes, 'individuals': individuals, 'schema_edges': schema_edges,
            'edges': edges, 'triples': triples, 'truncated': truncated,
            'at': datetime.now(timezone.utc).isoformat(),
            'scope': '业务模型；当前状态、设备、配置、证据及最新观测与评估。最多读取 4000 行，不含完整历史；实例数量仅针对本次读取。',
            'schema_ttl': model.serialize(format='turtle')}
