from fastapi.testclient import TestClient
from rdflib import Graph, RDF
from app.main import create_app
from app.domain import CU, SCHEMA
from app import learning
from test_core import settings, store, make_track


def client_for(settings, store):
    return TestClient(create_app(settings, store, enable_mqtt=False))


def test_dictionary_relations_and_current_instances(settings, store):
    store.write_track(make_track())
    client = client_for(settings, store)
    items = client.get('/api/learning/dictionary').json()
    assert items['source'] == 'business'
    assert any(t['label'] == '阵地' for t in items['items'])
    term = client.get('/api/learning/term', params={'uri': str(CU.Observation)}).json()
    assert term['count'] == 1 and term['examples'][0]['object'] == str(CU.Observation)
    assert any(r['uri'] == str(CU.basedOnObservation) for r in term['relations'])
    Graph().parse(data=term['ttl'], format='turtle')
    assert client.get('/api/learning/term', params={'uri': 'file:///etc/passwd'}).status_code == 404


def test_import_isolated_persistent_and_preview_rejects_invalid(settings, store):
    client = client_for(settings, store)
    baseline = store.construct(f'CONSTRUCT {{?s ?p ?o}} WHERE {{GRAPH <{SCHEMA}> {{?s ?p ?o}}}}')
    ttl = '@prefix owl: <http://www.w3.org/2002/07/owl#> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . <urn:FlightTask> a owl:Class; rdfs:label "飞行任务"@zh .'
    assert client.post('/api/learning/model/preview', json={'ttl': ttl}).status_code == 200
    assert client.put('/api/learning/model', json={'ttl': ttl}).status_code == 200
    store.initialize()  # Deployment startup refreshes business TBox, preserving learning graph.
    result = client.get('/api/learning/dictionary').json()
    assert result['source'] == 'learning' and result['items'][0]['label'] == '飞行任务'
    assert len(store.construct(f'CONSTRUCT {{?s ?p ?o}} WHERE {{GRAPH <{SCHEMA}> {{?s ?p ?o}}}}')) == len(baseline)
    assert client.post('/api/learning/model/preview', json={'ttl': 'broken'}).status_code == 422
    imports = ttl + ' <urn:o> owl:imports <file:///etc/passwd> .'
    assert client.put('/api/learning/model', json={'ttl': imports}).status_code == 422
    assert client.delete('/api/learning/model').status_code == 200
    assert client.get('/api/learning/dictionary').json()['source'] == 'business'


def test_five_queries_use_real_named_graphs_and_reject_injection(settings, store):
    store.write_track(make_track())
    store.write_track(make_track(1))
    client = client_for(settings, store)
    catalog = client.get('/api/learning/queries').json()['items']
    assert len(catalog) == 5
    for spec in catalog:
        response = client.post('/api/learning/query', json={
            'query_id': spec['id'], 'target_id': 'drone001', 'position_id': 'pos001'})
        assert response.status_code == 200, response.text
        value = response.json()
        assert value['rows'] and value['variables'] and 'SELECT' in value['sparql']
        if spec['id'] == 'history':
            assert len(value['rows']) == 2
        if spec['id'] == 'evidence':
            assert len(value['rows']) == 2
            assert all('rule' in row and 'observation' in row for row in value['rows'])
    assert client.post('/api/learning/query', json={'query_id': 'evidence'}).status_code == 422
    assert client.post('/api/learning/query', json={'query_id': 'current', 'target_id': 'x> SERVICE <http://evil>'}).status_code == 422
    assert client.post('/api/learning/query', json={'query_id': 'DELETE WHERE {?s ?p ?o}'}).status_code == 422


def test_shacl_valid_invalid_current_and_empty_scope(settings, store):
    client = client_for(settings, store)
    examples = client.get('/api/learning/validation/examples').json()
    good = client.post('/api/learning/validation', json={'ttl': examples['valid']}).json()
    assert good['conforms'] and good['focus_count'] > 0
    bad = client.post('/api/learning/validation', json={'ttl': examples['invalid']}).json()
    assert not bad['conforms'] and bad['result_count'] >= 3
    paths = {r['path'] for r in bad['results']}
    assert {str(CU.timestamp), str(CU.lon), str(CU.toPosition)} <= paths
    assert all(r['shape'] and r['message'] for r in bad['results'])
    Graph().parse(data=bad['report_ttl'], format='turtle')
    assert bad['inference'] == 'none'
    store.write_track(make_track())
    current = client.post('/api/learning/validation/current').json()
    assert current['conforms'] and current['focus_count'] == 5  # 1 observation + 2 assessments + 2 positions
    assert client.post('/api/learning/validation', json={'ttl': 'not turtle'}).status_code == 422
    assert client.post('/api/learning/validation', json={'ttl': 'x' * 32769}).status_code == 422
    empty = client.post('/api/learning/validation', json={'ttl': '<urn:s> <urn:p> <urn:o> .'}).json()
    assert empty['focus_count'] == 0 and '不代表' in empty['note']


def test_dictionary_and_validation_limit_to_current_observations(settings, store):
    for i in range(3):
        store.write_track(make_track(i))
    g = learning.current_graph(store, settings.ontology_dir)
    assert len(list(g.subjects(RDF.type, CU.Observation))) == 1
    assert len(list(g.subjects(RDF.type, CU.Assessment))) == 2
