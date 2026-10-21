from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from rdflib import Dataset, Graph, RDF
from app.config import Settings
from app.domain import CU, STATE, GEOD, Track, evaluate
from app.main import create_app
from app.store import FusekiStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings():
    return Settings(ontology_dir=ROOT / 'ontology')


def make_track(seconds=0, **values):
    return Track(target_id='drone001', lon=116.408, lat=39.9045, speed=10,
                 timestamp=datetime.now(timezone.utc) + timedelta(seconds=seconds), **values)


@pytest.fixture
def store(settings):
    dataset = Dataset()
    def handle(request):
        if request.url.path.endswith('/update'):
            dataset.update(request.content.decode())
            return httpx.Response(204)
        from urllib.parse import parse_qs
        sparql = parse_qs(request.content.decode())['query'][0]
        result = dataset.query(sparql)
        if result.type == 'CONSTRUCT':
            return httpx.Response(200, text=result.graph.serialize(format='turtle'))
        return httpx.Response(200, content=result.serialize(format='json'))
    instance = FusekiStore(settings)
    instance.client.close()
    instance.client = httpx.Client(transport=httpx.MockTransport(handle))
    instance.initialize()
    return instance


@pytest.mark.parametrize('distance,level', [(0,'HighAttention'),(99,'HighAttention'),
    (101,'MediumAttention'),(199,'MediumAttention'),(201,'LowAttention'),(299,'LowAttention'),(301,'OutsideThreshold')])
def test_distance_levels(settings, distance, level):
    lon,lat,_ = GEOD.fwd(settings.position_lon,settings.position_lat,60,distance)
    track = Track(target_id='test',lon=lon,lat=lat,speed=0,timestamp=datetime.now(timezone.utc))
    actual,result = evaluate(track,settings)
    assert actual == pytest.approx(distance,abs=.001)
    assert result == level


@pytest.mark.parametrize('field,value', [('lon',181),('lat',-91),('speed',-1),('speed',float('nan')),
    ('target_id','bad\";DROP'),('timestamp','2026-10-21T10:00:00')])
def test_reject_bad_data(field,value):
    payload={'target_id':'drone001','lon':116.4,'lat':39.9,'speed':1,'timestamp':datetime.now(timezone.utc)}
    payload[field]=value
    with pytest.raises(ValidationError):
        Track(**payload)


def test_update_rejects_old_and_duplicate_after_reinitialize(store):
    latest=make_track()
    store.write_track(latest)
    store.write_track(latest.model_copy(update={'lon':117}))
    store.initialize()
    store.write_track(latest.model_copy(update={'timestamp':latest.timestamp-timedelta(seconds=1),'lon':118}))
    rows=store.situation()
    assert len(rows)==1
    assert float(rows[0]['lon'])==latest.lon
    newer=latest.model_copy(update={'timestamp':latest.timestamp+timedelta(seconds=1),'lon':116.42})
    store.write_track(newer)
    assert float(store.situation()[0]['lon'])==116.42
    ttl=Graph().parse(data=store.target_ttl('drone001'),format='turtle')
    assert len(list(ttl.objects(CU.drone001,CU.lon)))==1
    assert (CU.pos001,RDF.type,CU.Position) in ttl
    assert (CU.OutsideThreshold,RDF.type,CU.DistanceLevel) in ttl


def test_api_and_stale_state(store,settings):
    store.write_track(make_track(seconds=-10))
    with TestClient(create_app(settings,store,enable_mqtt=False)) as client:
        assert client.get('/api/health').json()['fuseki'] is True
        situation=client.get('/api/situation').json()
        assert situation['targets'][0]['stale'] is True
        assert situation['position']['name']=='一号阵地'
        assert len(client.get('/api/ontology').json()['items'])==11
        assert 'owl:Class' in client.get('/api/ontology/ttl').text
        assert client.get('/api/targets/missing').status_code==404
        assert client.get('/api/targets/drone001').status_code==200
        assert client.get('/api/targets/drone001/ttl').status_code==200
        assert client.get('/api/targets/bad!').status_code==422


@pytest.mark.parametrize('distance,level', [(100,'HighAttention'),(100.001,'MediumAttention'),
    (200,'MediumAttention'),(200.001,'LowAttention'),(300,'LowAttention'),(300.001,'OutsideThreshold')])
def test_exact_threshold_boundaries(settings,monkeypatch,distance,level):
    from types import SimpleNamespace
    import app.domain as domain
    monkeypatch.setattr(domain,'GEOD',SimpleNamespace(inv=lambda *args:(0,0,distance)))
    assert evaluate(make_track(),settings)[1]==level
