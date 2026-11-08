from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app import rules
from app.main import create_app
from app.domain import Track
from app.version import VERSION
from test_core import settings, store


def rule(**kwargs):
    return rules.Rule(id='zone-test', name='区域进入', kind='zone', enabled=True,
                      source='测试假设', position_id='pos001', **kwargs)


def snapshot(t, lon=116.4):
    return {'positions':[{'id':'pos001','name':'阵地','lon':116.4,'lat':39.9}],
            'targets':[{'id':'u1','lon':lon,'lat':39.9,'timestamp':t.isoformat(),'observation_id':'obs1','data_mode':'simulated'}]}


def test_boundary_stale_and_future_are_distinct():
    t=datetime.now(timezone.utc)
    r=rule()
    assert rules.evaluate([r],snapshot(t),[],t)[0]['status']=='matched'
    assert rules.evaluate([r],snapshot(t),[],t+timedelta(seconds=30))[0]['status']=='matched'
    assert rules.evaluate([r],snapshot(t),[],t+timedelta(seconds=31))[0]['status']=='unknown'
    assert rules.evaluate([r],snapshot(t),[],t-timedelta(seconds=3))[0]['status']=='unknown'
    assert rules.evaluate([r],snapshot(t,117),[],t)[0]['status']=='clear'


def test_no_false_exit_on_data_loss_and_deduplicated_events():
    t=datetime.now(timezone.utc);doc=rules.empty();r=rule()
    def step(time, lon=116.4, observed=None):
        rows=rules.evaluate([r],snapshot(observed or time,lon),[],time)
        rules.transition(doc,rows,time,'config1')
    step(t)
    step(t+timedelta(seconds=5))
    assert [e['event'] for e in doc['events']]==['首次确认在区域内']
    step(t+timedelta(seconds=40),observed=t)
    assert doc['events'][-1]['event']=='无法判断'
    step(t+timedelta(seconds=45),lon=117)
    assert not any(e['event']=='离开区域' for e in doc['events'])
    step(t+timedelta(seconds=50))
    step(t+timedelta(seconds=55),lon=117)
    assert [e['event'] for e in doc['events']][-2:]==['进入区域','离开区域']


def test_radar_threshold_and_missing_time():
    t=datetime.now(timezone.utc)
    r=rules.Rule(id='radar',name='设备中断',kind='device_stale',enabled=True,source='设备说明')
    devices=[{'id':'r1','kind':'radar','published_at':(t-timedelta(seconds=31)).isoformat()}]
    assert rules.evaluate([r],snapshot(t),devices,t)[0]['status']=='matched'
    devices[0]['published_at']=''
    assert rules.evaluate([r],snapshot(t),devices,t)[0]['status']=='unknown'
    assert '不支持' in rules.evaluate([r],snapshot(t),devices,t,True)[0]['reason']


def test_validation_rejects_bad_rule():
    with pytest.raises(ValidationError):rule(radius=float('nan'))
    with pytest.raises(ValidationError):rules.Rule(id='bad',name='test',kind='zone',source='test')
    with pytest.raises(ValidationError):rules.Change(expected_revision=0,rules=[rule(),rule()],note='duplicate')


def test_publish_trial_persistence_and_conflict(store,settings):
    with TestClient(create_app(settings,store,enable_mqtt=False)) as client:
        first=client.get('/api/rules').json();assert first['revision']==0
        r=rule().model_dump()
        body={'expected_revision':0,'rules':[r],'note':'首次发布'}
        assert client.put('/api/rules',json=body).status_code==200
        assert client.put('/api/rules',json=body).status_code==409
        store.write_track(Track(target_id='test-uav',lon=116.408,lat=39.9045,speed=1,timestamp=datetime.now(timezone.utc)))
        before=rules.read(store)
        trial=client.post('/api/rules/trial',json={'rules':[r]})
        assert trial.status_code==200 and trial.json()['results']
        assert rules.read(store)==before
        engine=rules.Engine(store);engine.tick()
        after=rules.read(store)
        assert after['evaluated_at'] and after['results']
        store.initialize()
        assert rules.read(store)==after
        assert client.get('/api/health').json()['version']==VERSION
        assert client.get('/openapi.json').json()['paths']['/api/rules']['put']['summary']=='发布规则集'
        bad=dict(body,expected_revision=1,rules=[dict(r,position_id='missing')])
        assert client.put('/api/rules',json=bad).status_code==422


def test_version_matches_frontend():
    p=Path(__file__).resolve().parents[2]/'frontend/package.json'
    assert json.loads(p.read_text())['version']==VERSION


def test_sampling_gap_and_config_change_reset_zone_baseline():
    t=datetime.now(timezone.utc);doc=rules.empty();r=rule()
    rows=rules.evaluate([r],snapshot(t),[],t)
    rules.transition(doc,rows,t,'c1')
    later=t+timedelta(seconds=60)
    rows=rules.evaluate([r],snapshot(later,117),[],later)
    rules.transition(doc,rows,later,'c1')
    assert not any(e['event']=='离开区域' for e in doc['events'])
    rows=rules.evaluate([r],snapshot(later),[],later)
    rules.transition(doc,rows,later,'c2')
    assert doc['events'][-1]['event']=='首次确认在区域内'


def test_empty_data_stays_unknown_and_events_are_bounded():
    t=datetime.now(timezone.utc);doc=rules.empty();r=rule()
    for i in range(2):
        rows=rules.evaluate([r],{'positions':[],'targets':[]},[],t)
        rules.transition(doc,rows,t,'c1')
    assert len(doc['events'])==1 and doc['results'][0]['status']=='unknown'
    doc['events']*=301
    rules.transition(doc,rows,t,'c1')
    assert len(doc['events'])==300


def test_timer_detects_stale_without_incoming_messages(store,monkeypatch):
    t=datetime.now(timezone.utc)
    r=rules.Rule(id='fresh',name='过期',kind='observation_stale',source='测试',enabled=True)
    rules.publish(store,rules.Change(expected_revision=0,rules=[r],note='test'))
    store.write_track(Track(target_id='test-uav',lon=116.4,lat=39.9,speed=1,timestamp=t))
    engine=rules.Engine(store)
    monkeypatch.setattr(rules,'now',lambda:t)
    engine.tick();assert rules.read(store)['results'][0]['status']=='clear'
    monkeypatch.setattr(rules,'now',lambda:t+timedelta(seconds=31))
    engine.tick();assert rules.read(store)['results'][0]['status']=='matched'
    assert rules.read(store)['events'][-1]['event']=='触发提醒'
