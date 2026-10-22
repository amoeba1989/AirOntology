from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from rdflib import Dataset, Graph, RDF
from app.config import Settings
from app.domain import CU, STATE, HISTORY, CONFIG, GEOD, Track, evaluate
from app.views import situation_view
from app.models import RuntimeConfig
from app.store import ConfigConflict
from app.main import create_app
from app.store import FusekiStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings():
    return Settings(ontology_dir=ROOT / 'ontology', deepseek_api_key='')


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
            # N-Triples is valid Turtle and preserves exact double lexical values;
            # RDFLib's abbreviated Turtle serializer rounds coordinates in mocks.
            return httpx.Response(200, text=result.graph.serialize(format='nt'))
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
    snapshot=situation_view(store.snapshot_graph(),store.config)
    assert len(snapshot['targets'])==1
    assert snapshot['targets'][0]['lon']==latest.lon
    assert len(snapshot['assessments'])==2
    assert len(list(store.history_graph('drone001',100).subjects(RDF.type,CU.Observation)))==1
    newer=latest.model_copy(update={'timestamp':latest.timestamp+timedelta(seconds=1),'lon':116.42})
    store.write_track(newer)
    snapshot=situation_view(store.snapshot_graph(),store.config)
    assert snapshot['targets'][0]['lon']==116.42
    ttl=Graph().parse(data=store.target_ttl('drone001'),format='turtle')
    assert len(list(ttl.objects(CU.drone001,CU.latestObservation)))==1
    assert len(list(ttl.objects(CU.drone001,CU.latestAssessment)))==2
    assert len(list(ttl.subjects(RDF.type,CU.Assessment)))==2


def test_api_and_stale_state(store,settings):
    store.write_track(make_track(seconds=-10))
    with TestClient(create_app(settings,store,enable_mqtt=False)) as client:
        assert client.get('/api/health').json()['fuseki'] is True
        situation=client.get('/api/situation').json()
        assert situation['targets'][0]['stale'] is True
        assert len(situation['positions'])==2
        terms = {t['id'] for t in client.get('/api/ontology').json()['items']}
        assert {'Observation','Assessment','DistanceRule','AttentionRankingPolicy','RankedCandidate'} <= terms
        assert 'owl:Class' in client.get('/api/ontology/ttl').text
        assert client.get('/api/targets/missing').status_code==404
        assert client.get('/api/targets/drone001').status_code==200
        assert client.get('/api/targets/drone001/ttl').status_code==200
        assert client.get('/api/targets/bad!').status_code==422
        assert client.get('/api/situation?at=2026-10-21T10:00:00').status_code==422
        assert client.get('/api/history?target_id=drone001&limit=0').status_code==422
        history=client.get('/api/history?target_id=drone001').json()
        assert history['count']==1
        evaluation=situation['assessments'][0]
        detail=client.get('/api/assessments/'+evaluation['id']).json()
        assert detail['source']=='MQTT'
        assert detail['observation']['lon']==pytest.approx(116.408)
        assert client.get('/api/assessments/'+evaluation['id']+'/ttl').status_code==200


@pytest.mark.parametrize('distance,level', [(100,'HighAttention'),(100.001,'MediumAttention'),
    (200,'MediumAttention'),(200.001,'LowAttention'),(300,'LowAttention'),(300.001,'OutsideThreshold')])
def test_exact_threshold_boundaries(settings,monkeypatch,distance,level):
    from types import SimpleNamespace
    import app.domain as domain
    monkeypatch.setattr(domain,'GEOD',SimpleNamespace(inv=lambda *args:(0,0,distance)))
    assert evaluate(make_track(),settings)[1]==level


def test_independent_assessments_and_replay(store):
    old=make_track(seconds=-20)
    store.write_track(old)
    new=old.model_copy(update={'timestamp':old.timestamp+timedelta(seconds=10),'lon':116.42})
    store.write_track(new)
    live=situation_view(store.snapshot_graph(),store.config)
    past=situation_view(store.snapshot_graph(old.timestamp),store.config,old.timestamp)
    assert live['targets'][0]['lon']==116.42
    assert past['targets'][0]['lon']==old.lon
    assert len(past['assessments'])==2
    assert past['assessments'][0]['distance']!=past['assessments'][1]['distance']
    assert past['mode']=='replay'
    assert not situation_view(store.snapshot_graph(old.timestamp-timedelta(seconds=1)),store.config,old.timestamp-timedelta(seconds=1))['targets']


def test_config_persistence_conflict_and_immutable_evidence(store):
    old=make_track(seconds=-10)
    store.write_track(old)
    previous=situation_view(store.snapshot_graph(),store.config)['assessments'][0]
    version=store.config.version
    payload=store.config.model_dump()
    payload['positions'][0]['lon']=116.5
    payload['high_threshold']=50
    config=RuntimeConfig(**payload)
    store.set_config(config,version)
    store.initialize()
    assert store.config.positions[0].lon==116.5
    with pytest.raises(ConfigConflict):store.set_config(config,version)
    pending=situation_view(store.snapshot_graph(),store.config)['assessments'][0]
    assert pending['config_pending'] is True
    store.write_track(old.model_copy(update={'timestamp':old.timestamp+timedelta(seconds=1)}))
    snapshot=situation_view(store.snapshot_graph(),store.config)
    assert all(a['rule_version']==config.version for a in snapshot['assessments'])
    evidence=store.assessment_graph(previous['id'])
    assert str(evidence.value(CU[previous['id']],CU.positionLon))==str(previous['position_lon'])
    assert str(evidence.value(CU[previous['id']],CU.usedRule)).endswith(version)


def test_retention_cleans_observations_and_assessments(store):
    config=store.config.model_copy(update={'history_limit':10})
    store.set_config(config,store.config.version)
    old=make_track(seconds=-20)
    for i in range(12):store.write_track(old.model_copy(update={'timestamp':old.timestamp+timedelta(seconds=i)}))
    g=store.history_graph('drone001',100)
    assert len(list(g.subjects(RDF.type,CU.Observation)))==10
    assert len(list(g.subjects(RDF.type,CU.Assessment)))==20
    assert len(situation_view(store.snapshot_graph(),store.config)['assessments'])==2


def test_config_api_validation_and_conflict(store,settings):
    with TestClient(create_app(settings,store,enable_mqtt=False)) as client:
        initial=client.get('/api/config').json()
        change={'expected_version':initial['version'],'config':initial['config']}
        change['config']['high_threshold']=75
        assert client.put('/api/config',json=change).status_code==200
        assert client.put('/api/config',json=change).status_code==409
        invalid=client.get('/api/config').json()
        invalid['config']['positions'].append(invalid['config']['positions'][0])
        assert client.put('/api/config',json={'expected_version':invalid['version'],'config':invalid['config']}).status_code==422
        invalid['config']['positions']=invalid['config']['positions'][:1]
        invalid['config']['high_threshold']=999
        assert client.put('/api/config',json={'expected_version':invalid['version'],'config':invalid['config']}).status_code==422


def test_v1_migration_preserves_latest_target(store):
    stamp=make_track(seconds=-10).timestamp.isoformat()
    store.update(f"""INSERT DATA {{ GRAPH <{STATE}> {{
     <{CU.legacy}> a <{CU.BlueDevice}>; <{CU.lon}> 116.4; <{CU.lat}> 39.9;
     <{CU.speed}> 1; <{CU.timestamp}> \"{stamp}\"^^<http://www.w3.org/2001/XMLSchema#dateTime> .
    }} }}""")
    store.initialize()
    snapshot=situation_view(store.snapshot_graph(target_id='legacy'),store.config)
    assert snapshot['targets'][0]['source']=='第一版迁移'
    assert len(snapshot['assessments'])==2


def test_three_targets_two_positions_and_asof_selection(store):
    start=make_track(seconds=-20)
    for index in range(3):
        store.write_track(start.model_copy(update={'target_id':f'drone{index+1:03d}','timestamp':start.timestamp+timedelta(seconds=index)}))
    store.write_track(start.model_copy(update={'lon':116.42,'timestamp':start.timestamp+timedelta(seconds=10)}))
    cutoff=start.timestamp+timedelta(seconds=1)
    state=situation_view(store.snapshot_graph(cutoff),store.config,cutoff)
    assert len(state['targets'])==2
    assert len(state['assessments'])==4
    assert state['targets'][0]['lon']==start.lon
    live=situation_view(store.snapshot_graph(),store.config)
    assert len(live['targets'])==3 and len(live['assessments'])==6
    assert live['targets'][0]['lon']==116.42
    assert len(situation_view(store.snapshot_graph(target_id='drone002'),store.config)['targets'])==1


def test_removing_position_does_not_rewrite_history(store):
    old=make_track(seconds=-10)
    store.write_track(old)
    config=store.config.model_copy(update={'positions':store.config.positions[:1]})
    store.set_config(config,store.config.version)
    live=situation_view(store.snapshot_graph(),store.config)
    assert len(live['positions'])==1 and len(live['assessments'])==1
    past=situation_view(store.snapshot_graph(old.timestamp),store.config,old.timestamp)
    assert len(past['positions'])==2 and len(past['assessments'])==2


@pytest.mark.parametrize('reserved',['runtime','HighAttention','obs-123','eval-123','rule-123'])
def test_reserved_ids_do_not_collide_with_ontology(reserved):
    with pytest.raises(ValidationError):
        Track(target_id=reserved,lon=116.4,lat=39.9,speed=1,timestamp=datetime.now(timezone.utc))


def test_missing_history_target_does_not_leak_other_targets(store,settings):
    track=make_track(seconds=-10)
    store.write_track(track)
    assert len(store.history_graph('missing',100))==0
    assert not situation_view(store.snapshot_graph(track.timestamp,'missing'),store.config,track.timestamp)['targets']
    with TestClient(create_app(settings,store,enable_mqtt=False)) as client:
        from urllib.parse import quote
        assert client.get('/api/targets/missing/ttl?at='+quote(track.timestamp.isoformat(),safe='')).status_code==404
        assert client.get('/api/history?target_id=missing').json()['records']==[]
