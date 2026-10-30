from fastapi.testclient import TestClient
from rdflib import RDF
from app.main import create_app
from app.domain import CU
from test_core import settings, store, make_track


def test_model_without_observations_and_live_type_links(settings, store):
    client = TestClient(create_app(settings, store, enable_mqtt=False))
    empty = client.get('/api/ontology/topology')
    assert empty.status_code == 200, empty.text
    value = empty.json()
    assert any(t['uri'] == str(CU.RadarSensor) for t in value['terms'])
    assert any(e['source'] == str(CU.RadarSensor) and e['target'] == str(CU.SensorDevice)
               and e['kind'] == 'inheritance' for e in value['schema_edges'])
    store.write_track(make_track())
    value = client.get('/api/ontology/topology').json()
    assert any(e['source'] == str(CU.drone001) and e['target'] == str(CU.BlueDevice)
               and e['predicate'] == str(RDF.type) for e in value['edges'])
    assert any(e['predicate'] == str(CU.basedOnObservation) for e in value['edges'])
    assert all('graph' in t for t in value['triples'])
    assert not value['truncated']
    assert any(t['constraints'] for t in value['terms'] if t['kind'] == 'class')
