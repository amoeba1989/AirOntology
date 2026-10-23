from datetime import timedelta
from types import SimpleNamespace
import json
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from rdflib import RDF, Literal, XSD
from app import evidence as ev, learning
from app.domain import CU
from app.main import create_app
from app.consumer import Consumer
from test_core import settings, store, make_track


def client_for(settings, store):
    return TestClient(create_app(settings,store,enable_mqtt=False))


def device(store, **kw):
    data=ev.examples()['devices'];data.update(kw)
    rec=ev.Device(**data);ev.save(store,'devices',rec);return rec


def obs(store, **kw):
    data=ev.examples()['observations'];data.update(kw)
    rec=ev.SensorObservation(**data);ev.save(store,'observations',rec);return rec


def judgement(store, **kw):
    data=ev.examples()['judgements'];data.update(kw)
    rec=ev.Judgement(**data);ev.save(store,'judgements',rec);return rec


def test_demo_four_sources_separate_layers_and_graph(settings,store):
    client=client_for(settings,store)
    assert client.get('/api/evidence').json()['observations']==[]
    assert client.post('/api/evidence/demo').status_code==200
    value=client.get('/api/evidence').json()
    assert {d['sensor_kind'] for d in value['devices']}=={'radar','radio','camera','infrared'}
    assert len(value['observations'])==4 and len(value['judgements'])==3
    assert all(x['data_mode']=='simulated' for kind in ('devices','observations','regions','judgements') for x in value[kind])
    intrusion=next(j for j in value['judgements'] if j['layer']=='intrusion')
    assert intrusion['current_status']=='pending' and intrusion['authorization_status']=='unknown'
    negative=next(o for o in value['observations'] if o['outcome']=='not_detected')
    assert not negative['usable_positive']
    g=ev.read_graph(store)
    assert not list(g.subjects(RDF.type,CU.BlueDevice))
    assert len(list(g.subjects(RDF.type,CU.SuspectedTarget)))==1
    assert client.get('/api/evidence/ttl').status_code==200
    result=client.post('/api/evidence/validate').json()
    assert result['conforms'], result
    assert result['focus_count']==12
    detail=client.get('/api/learning/term',params={'uri':str(CU.SensorObservation)}).json()
    assert detail['count']==4


def test_immutable_ids_reference_integrity_and_snapshots(store):
    d=device(store);o=obs(store)
    assert ev.save(store,'observations',o)['status']=='unchanged'
    with pytest.raises(ev.EvidenceConflict):ev.save(store,'observations',o.model_copy(update={'features':'changed'}))
    with pytest.raises(ValueError,match='设备'):obs(store,id='orphan',device_id='missing')
    with pytest.raises(ValueError,match='不存在'):judgement(store,observation_ids=['missing'])
    device(store,reported_at=d.reported_at+timedelta(seconds=1),reported_status='fault')
    with pytest.raises(ev.EvidenceConflict):ev.save(store,'devices',d)
    value=ev.view(store)['observations'][0]
    assert value['device_state_at_receipt']['reported_status']=='normal'
    assert not value['usable_positive']
    j=judgement(store)
    with pytest.raises(ev.EvidenceConflict):ev.save(store,'judgements',j.model_copy(update={'uncertainty':'changed'}))
    with pytest.raises(ValueError,match='其他疑似目标'):judgement(store,id='other',target_ref='different',judgement_ids=[j.id])


@pytest.mark.parametrize('kind,changes',[
 ('observations',{'observed_at':'2026-10-23T10:00:00'}),
 ('observations',{'crs':'unknown'}),
 ('observations',{'lat':None}),
 ('observations',{'lon':float('nan')}),
 ('judgements',{'score':.99}),
 ('judgements',{'status':'confirmed'}),
 ('judgements',{'observation_ids':[],'status':'suspected'}),
 ('judgements',{'observation_ids':['same','same']}),
 ('judgements',{'layer':'intrusion'}),
 ('judgements',{'probability':.9}),
])
def test_reject_ambiguous_or_unsupported_claims(kind,changes):
    data=ev.examples()[kind];data.update(changes)
    with pytest.raises(ValidationError):ev.MODELS[kind](**data)


def test_unknown_expired_and_conflicting_inputs_remain_uncertain(store):
    d=device(store);o=obs(store)
    j=judgement(store,status='suspected')
    assert ev.view(store)['judgements'][0]['current_status']=='suspected'
    judgement(store,id='association',layer='association',status='suspected')
    assert next(j for j in ev.view(store)['judgements'] if j['id']=='association')['current_status']=='insufficient'
    obs(store,id='negative',outcome='not_detected')
    judgement(store,id='negative-judgement',observation_ids=['negative'],status='suspected')
    assert next(j for j in ev.view(store)['judgements'] if j['id']=='negative-judgement')['current_status']=='insufficient'
    obs(store,id='old',observed_at=ev.now()-timedelta(hours=1))
    assert not next(o for o in ev.view(store)['observations'] if o['id']=='old')['usable_positive']
    obs(store,id='mixed',data_mode='operational')
    judgement(store,id='mixed-judgement',observation_ids=[o.id,'mixed'],status='suspected')
    assert next(j for j in ev.view(store)['judgements'] if j['id']=='mixed-judgement')['current_status']=='conflict'
    device(store,reported_at=d.reported_at+timedelta(seconds=1),coverage='insufficient')
    assert '覆盖不足' in ev.view(store)['devices'][0]['observation_note']
    device(store,reported_at=d.reported_at+timedelta(seconds=2),reported_status='unknown')
    assert all(j['current_status']=='insufficient' for j in ev.view(store)['judgements'])


def test_authorization_unknown_expired_and_authorized_not_blackflight(store):
    device(store);obs(store)
    region=ev.Region(**ev.examples()['regions']);ev.save(store,'regions',region)
    base=ev.examples()['authorizations'];now=ev.now()
    for key,status,start,end in [('unknown','unknown',now-timedelta(minutes=1),now+timedelta(hours=1)),('expired','unauthorized',now-timedelta(hours=2),now-timedelta(hours=1)),('yes','authorized',now-timedelta(minutes=1),now+timedelta(hours=1))]:
        auth=ev.Authorization(**(base|{'id':key,'status':status,'valid_from':start,'valid_until':end}))
        ev.save(store,'authorizations',auth)
        judgement(store,id='intrusion-'+key,layer='intrusion',region_id=region.id,authorization_id=key,status='suspected')
    values={j['id']:j for j in ev.view(store)['judgements']}
    assert values['intrusion-unknown']['current_status']=='pending'
    assert values['intrusion-expired']['authorization_status']=='unknown'
    assert values['intrusion-expired']['current_status']=='pending'
    assert values['intrusion-yes']['current_status']=='conflict'
    with pytest.raises(ValueError,match='匹配'):judgement(store,id='bad-auth',target_ref='different',layer='intrusion',region_id=region.id,authorization_id='yes')


def test_quota_does_not_delete_referenced_evidence(store,monkeypatch):
    device(store);o=obs(store);judgement(store)
    monkeypatch.setitem(ev.LIMITS,'observations',1)
    with pytest.raises(ev.EvidenceConflict):obs(store,id='next')
    assert ev.view(store)['observations'][0]['id']==o.id
    assert ev.save(store,'observations',o)['status']=='unchanged'


def test_api_ingest_validation_and_storage_errors(settings,store,monkeypatch):
    client=client_for(settings,store);values=client.get('/api/evidence/examples').json()
    assert client.post('/api/evidence/observations',json=values['observations']).status_code==422
    for kind in ['devices','observations','regions','authorizations','judgements']:
        response=client.post('/api/evidence/'+kind,json=values[kind]);assert response.status_code==200,response.text
    assert client.post('/api/evidence/observations',json=values['observations']|{'quality':'invalid'}).status_code==409
    assert client.post('/api/evidence/judgements',json=values['judgements']|{'status':'confirmed'}).status_code==422
    monkeypatch.setattr(store,'construct',lambda *_:(_ for _ in ()).throw(RuntimeError('test failure')))
    assert client.get('/api/evidence').status_code==503
    assert client.post('/api/evidence/devices',json=values['devices']).status_code==503


def test_shacl_detects_missing_source_and_score_meaning(settings,store):
    device(store);obs(store);judgement(store,score=82,score_meaning='算法原始打分，未校准，非概率')
    g=ev.read_graph(store)
    assert learning.validate_facts(g,settings.ontology_dir)['conforms']
    g.remove((None,CU.fromDevice,None));g.remove((None,CU.scoreMeaning,None))
    result=learning.validate_facts(g,settings.ontology_dir)
    assert not result['conforms'] and result['result_count']>=2


def test_raw_mqtt_and_legacy_track_coexist(settings,store):
    device(store);consumer=Consumer(settings,store)
    payload=ev.examples()['observations']
    consumer.on_message(None,None,SimpleNamespace(topic=settings.mqtt_observation_topic,payload=json.dumps(payload).encode()))
    assert isinstance(consumer.queue.queue[0],ev.SensorObservation)
    consumer.on_message(None,None,SimpleNamespace(topic=settings.mqtt_topic,payload=make_track(data_mode='simulated').model_dump_json().encode()))
    consumer.worker.start()
    consumer.queue.join();consumer.stop_event.set();consumer.worker.join(timeout=2)
    assert len(ev.view(store)['observations'])==1
    assert consumer.rejected==0 and consumer.last_write
    g=store.snapshot_graph()
    assert list(g.objects(CU.drone001,CU.latestObservation))
    assert Literal('simulated',datatype=XSD.string) in g.objects(None,CU.dataMode)
