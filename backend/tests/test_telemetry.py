from datetime import timedelta
import pytest
from pydantic import ValidationError
from rdflib import RDF, Literal, XSD
from fastapi.testclient import TestClient
from test_core import settings, store
from app import telemetry as t
from app.demo_telemetry import make_registry, make_frame
from app.main import create_app
from app.learning import validate_facts
from app.domain import CU
from app.domain import GEOD, classify
from app.demo_routes import flight_sample


def setup(store, settings):
    now=t.utcnow()-timedelta(seconds=3)
    registry=make_registry(settings,'test-run',count=2,published_at=now)
    t.register(store,registry)
    frame=make_frame(settings,registry,0,published_at=now)
    return registry,frame,now


def test_four_types_relationships_and_typed_states(store,settings):
    registry,frame,now=setup(store,settings)
    t.ingest(store,frame)
    facts=t.facts(store)
    assert (CU.drone001,RDF.type,CU.UAV) in facts
    assert (CU.radar001,RDF.type,CU.RadarSensor) in facts
    assert (CU.jammer001,RDF.type,CU.Jammer) in facts
    assert len(list(facts.triples((None,CU.deployedAt,None))))==4
    assert not list(facts.triples((CU.drone001,CU.deployedAt,None)))
    assert len(list(facts.subjects(RDF.type,CU.DeviceState)))==6
    assert len(list(store.snapshot_graph().subjects(RDF.type,CU.Observation)))==2
    assert facts.value(CU.radar001,CU.reportedDeviceStatus)==Literal('unknown',datatype=XSD.string)
    report=validate_facts(facts,settings.ontology_dir)
    assert report['conforms'],report['results']
    assert len(store.query(t.deployment_query())['results']['bindings'])==4
    rows=store.query(t.deployment_query(registry.devices[2].deployed_at))['results']['bindings']
    assert len(rows)==2
    assert all(row['kind']['value'] in ('radar','jammer') for row in rows)


def test_repeated_and_out_of_order_frames(store,settings):
    registry,frame,now=setup(store,settings)
    assert t.register(store,registry)['status']=='unchanged'
    t.ingest(store,frame)
    assert t.ingest(store,frame)['status']=='unchanged'
    newer=make_frame(settings,registry,6,published_at=now+timedelta(seconds=1))
    t.ingest(store,newer)
    assert t.ingest(store,frame)['status']=='ignored_old_frame'
    conflict=newer.model_copy(update={'published_at':now+timedelta(seconds=2)})
    with pytest.raises(ValueError,match='冲突'):t.ingest(store,conflict)
    assert t.read_graph(store).value(t.NS['state-jammer001'],CU.emitterEmitting)==Literal(False,datatype=XSD.boolean)
    assert t.read_graph(store).value(t.NS['state-jammer001'],CU.emitterEnabled)==Literal(True,datatype=XSD.boolean)
    newregistry=make_registry(settings,'next-run',2,published_at=now+timedelta(seconds=2))
    t.register(store,newregistry)
    with pytest.raises(ValueError,match='登记'):t.ingest(store,newer)
    assert t.view(store)['frame'] is None


def test_missing_entity_and_missing_block_are_not_false(store,settings):
    registry,frame,now=setup(store,settings)
    t.ingest(store,frame)
    newer=make_frame(settings,registry,1,published_at=now+timedelta(seconds=1),omit_handles=(1001,))
    raw=newer.model_dump(mode='json')
    first=raw['payload']['entities'][0]
    first['blocks']-=16
    first.pop('rf_link')
    t.ingest(store,t.Frame(**raw))
    devices={d['id']:d for d in t.view(store)['devices']}
    assert not devices['radar001']['in_latest_frame']
    assert devices['radar001']['state']['transform']
    assert devices['drone001']['state'].get('rf_link') is None
    assert t.read_graph(store).value(t.NS['state-drone001'],CU.rcLinked) is None


def test_bad_references_reject_whole_frame(store,settings):
    registry,frame,now=setup(store,settings)
    raw=frame.model_dump(mode='json');raw['payload']['entities'][-1]['id']=99999
    with pytest.raises(ValueError,match='未登记'):t.ingest(store,t.Frame(**raw))
    assert not list(store.snapshot_graph().subjects(RDF.type,CU.Observation))
    assert t.view(store)['frame'] is None
    raw=registry.model_dump(mode='json');raw['run_id']='bad-run';raw['published_at']=t.utcnow();raw['devices'][0]['deployed_at']='missing'
    with pytest.raises(ValueError,match='不存在'):t.register(store,t.Registry(**raw))
    assert t.view(store)['registry']['run_id']=='test-run'


@pytest.mark.parametrize('error',['mask','count','coordinate','time','duplicate'])
def test_invalid_message_contract(settings,error):
    registry=make_registry(settings,'test-run',1)
    raw=make_frame(settings,registry,0).model_dump(mode='json')
    if error=='mask':raw['payload']['entities'][0]['blocks']=0
    if error=='count':raw['payload']['reported_count']=0
    if error=='coordinate':raw['payload']['entities'][0]['transform']['latitude_deg']=100
    if error=='time':raw['published_at']='2026-01-01T00:00:00'
    if error=='duplicate':raw['payload']['entities'][1]['id']=raw['payload']['entities'][0]['id']
    with pytest.raises(ValidationError):t.Frame(**raw)


def test_device_api_learning_surfaces(store,settings):
    registry,frame,now=setup(store,settings);t.ingest(store,frame)
    with TestClient(create_app(settings,store,enable_mqtt=False)) as client:
        assert len(client.get('/api/devices').json()['devices'])==6
        assert 'deployedAt' in client.get('/api/devices/ttl').text
        assert len(client.get('/api/devices/deployments').json()['rows'])==4
        assert client.get('/api/devices/deployments?position_id=bad!').status_code==422
        assert client.post('/api/devices/validate').json()['conforms']
        result=client.get('/api/learning/term',params={'uri':str(CU.Jammer)}).json()
        assert result['examples'] and result['ttl']


def test_mqtt_routing_and_reference_order(store,settings):
    from types import SimpleNamespace
    from app.consumer import Consumer
    consumer=Consumer(settings,store)
    registry=make_registry(settings,'mqtt-run',1)
    frame=make_frame(settings,registry,0)
    subscribed=[]
    fake=SimpleNamespace(subscribe=lambda topics:subscribed.extend(topics))
    consumer.on_connect(fake,None,None,SimpleNamespace(is_failure=False),None)
    assert {topic for topic,qos in subscribed}=={settings.mqtt_topic,settings.mqtt_observation_topic,settings.mqtt_registry_topic,settings.mqtt_telemetry_topic}
    consumer.worker.start()
    try:
        for topic,record in [(settings.mqtt_registry_topic,registry),(settings.mqtt_telemetry_topic,frame)]:
            consumer.on_message(None,None,SimpleNamespace(topic=topic,payload=record.model_dump_json().encode()))
        consumer.queue.join()
        assert t.view(store)['frame']['run_id']=='mqtt-run'
        assert consumer.rejected==0
        consumer.on_message(None,None,SimpleNamespace(topic=settings.mqtt_telemetry_topic,payload=b'x'*262145))
        consumer.on_message(None,None,SimpleNamespace(topic='unknown',payload=b'{}'))
        assert consumer.rejected==2
    finally:
        consumer.stop()


def test_fuseki_abbreviated_strings_validate_without_weakening_enum(store,settings):
    from rdflib import Graph
    registry,frame,now=setup(store,settings);t.ingest(store,frame)
    original=t.facts(store)
    abbreviated=Graph()
    for s,p,o in original:
        if isinstance(o,Literal) and o.datatype==XSD.string:o=Literal(str(o))
        abbreviated.add((s,p,o))
    assert validate_facts(abbreviated,settings.ontology_dir)['conforms']
    assert abbreviated.value(CU.drone001,CU.deviceKind).datatype is None
    abbreviated.set((CU.drone001,CU.deviceKind,Literal('unsupported-device')))
    report=validate_facts(abbreviated,settings.ontology_dir)
    assert not report['conforms']
    assert any(r['path']==str(CU.deviceKind) for r in report['results'])


def test_demo_routes_are_repeatable_continuous_and_change_attention(settings):
    positions=settings.initial_config().positions
    registry=make_registry(settings,'route-test',count=16)
    assert len(registry.devices)==20
    assert all(not device.deployed_at for device in registry.devices[:16])
    assert len({d.parameters['demo_route_profile'] for d in registry.devices[:16]})==4
    paths=[]
    for i in range(16):
        anchor=positions[i%len(positions)]
        points=[flight_sample(anchor,i,tick,2) for tick in range(150)]
        assert points==[flight_sample(anchor,i,tick,2) for tick in range(150)]
        distances=[GEOD.inv(lon,lat,anchor.lon,anchor.lat)[2] for lon,lat,*_ in points]
        steps=[GEOD.inv(a[0],a[1],b[0],b[1])[2] for a,b in zip(points,points[1:])]
        assert all(0<step<35 for step in steps)
        assert all(0<sample[3]<18 and 45<sample[4]<150 for sample in points)
        paths.append(tuple(round(value/100) for value in distances))
        if i<2:
            assert len({classify(distance,settings) for distance in distances})>=3
    assert len(set(paths))>=12
    # At least some close approaches and some distant transits; no fixed radial oscillation.
    assert any(min(path)<1 and max(path)>4 for path in paths)
    f0=make_frame(settings,registry,0,interval=2)
    f1=make_frame(settings,registry,1,interval=2)
    for first,second in zip(f0.payload.entities[:16],f1.payload.entities[:16]):
        bearing,_,distance=GEOD.inv(first.transform.longitude_deg,first.transform.latitude_deg,
                                    second.transform.longitude_deg,second.transform.latitude_deg)
        assert distance/2==pytest.approx(second.motion.speed_mps,abs=.01)
        assert (bearing+360)%360==pytest.approx(second.transform.yaw_deg,abs=.1)
