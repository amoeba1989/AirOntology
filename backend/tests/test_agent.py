import asyncio
import json
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, RDF, Literal, XSD
from app import agent
from app.domain import CU, GEOD, Track, SCHEMA
from app.main import create_app
from test_core import settings, store


def track(settings, target_id, distance, stamp):
    lon, lat, _ = GEOD.fwd(settings.position_lon, settings.position_lat, 90, distance)
    return Track(target_id=target_id, name='演示'+target_id, lon=lon, lat=lat, speed=10, timestamp=stamp)


def events(response):
    return [(chunk.split('\n')[0].removeprefix('event: '), json.loads(chunk.split('\ndata: ')[1]))
            for chunk in response.text.strip().split('\n\n')]


def test_policy_rank_and_radial_trend_are_deterministic(settings, store):
    now = datetime.now(timezone.utc)
    for target_id, old, new in [('near',151,150),('approaching',230,180)]:
        store.write_track(track(settings,target_id,old,now-timedelta(seconds=2)))
        store.write_track(track(settings,target_id,new,now-timedelta(seconds=1)))
    result = agent.build_analysis(store,settings,'attention','pos001')
    assert [c['target_id'] for c in result['candidates']] == ['approaching','near']
    assert result['candidates'][0]['closing_speed'] == pytest.approx(50, abs=.01)
    assert result['candidates'][0]['eta_seconds'] == pytest.approx(1.6, abs=.01)
    assert result['candidates'][0]['previous_observation_uri']
    nearest = agent.build_analysis(store,settings,'nearest','pos001')
    assert [c['target_id'] for c in nearest['candidates']] == ['near','approaching']
    assert all(c['eta_seconds'] is None and c['closing_speed'] is None for c in nearest['candidates'])
    nearest_payload = agent.explanation_payload(nearest)
    assert all('eta_seconds' not in c and 'trend_note' not in c and 'level_label' not in c
               for c in nearest_payload['candidates'])
    assert nearest_payload['policy']['keys'] == ['distanceToPosition','targetIdentifier']
    assert 'max_gap' not in nearest_payload['policy']
    assert '不使用趋势' in nearest_payload['scope']
    graph = Graph().parse(data=result['ttl'],format='turtle')
    assert len(list(graph.subjects(RDF.type,CU.RankedCandidate))) == 2
    assert (CU[result['id']], CU.usedRankingPolicy, CU['attention-policy-v1']) in graph
    client = TestClient(create_app(settings,store,enable_mqtt=False))
    detail = client.get('/api/learning/term',params={'uri':str(CU.RankedCandidate)}).json()
    assert detail['count']==2 and '分析快照' in detail['scope']
    # A single analysis graph is replaced, not appended indefinitely.
    saved = store.construct(f'CONSTRUCT {{?s ?p ?o}} WHERE {{GRAPH <{agent.ANALYSIS_GRAPH}> {{?s ?p ?o}}}}')
    assert len(list(saved.subjects(RDF.type,CU.SituationAnalysis))) == 1


def test_missing_trend_receding_stale_clock_skew_and_config_change(settings, store):
    now = datetime.now(timezone.utc)
    store.write_track(track(settings,'one-observation',160,now-timedelta(seconds=1)))
    store.write_track(track(settings,'receding',120,now-timedelta(seconds=2)))
    store.write_track(track(settings,'receding',170,now-timedelta(seconds=1)))
    store.write_track(track(settings,'stale',50,now-timedelta(seconds=40)))
    store.write_track(track(settings,'future',40,now+timedelta(seconds=10)))
    result = agent.build_analysis(store,settings,'attention','pos001')
    assert {c['target_id'] for c in result['candidates']} == {'one-observation','receding'}
    assert all(c['eta_seconds'] is None for c in result['candidates'])
    assert {c['target_id'] for c in result['excluded']} == {'stale','future'}
    updated = store.config.model_copy(update={'high_threshold':90.0})
    store.set_config(updated,store.config.version)
    result = agent.build_analysis(store,settings,'attention','pos001')
    assert not result['candidates']
    assert any(e['reason']=='等待当前规则的新评估' for e in result['excluded'])


def test_policy_is_read_from_business_tbox_and_bad_policy_rejected(settings, store):
    now = datetime.now(timezone.utc)
    store.write_track(track(settings,'droneB',50,now))
    store.write_track(track(settings,'droneA',50,now))
    result = agent.build_analysis(store,settings,'attention','pos001')
    assert [c['target_id'] for c in result['candidates']] == ['droneA','droneB']
    store.update(f'''DELETE WHERE {{GRAPH <{SCHEMA}> {{ <{CU['attention-policy-v1']}> <{CU.sortKeys}> ?list }}}}''')
    with pytest.raises(ValueError,match='排序策略'):
        agent.build_analysis(store,settings,'attention','pos001')


def test_sse_cards_before_explanation_and_fixed_question_boundary(settings, store):
    now = datetime.now(timezone.utc)
    for i in range(10):
        store.write_track(track(settings,f'drone{i:03}',40+i*20,now))
    client = TestClient(create_app(settings,store,enable_mqtt=False))
    assert len(client.get('/api/agent/questions').json()['items']) == 3
    response = client.post('/api/agent/ask',json={'question_id':'attention','position_id':'pos001'})
    assert response.status_code == 200 and 'text/event-stream' in response.headers['content-type']
    received = events(response)
    assert received[0][0]=='snapshot' and received[-1][0]=='done'
    cards = [v for k,v in received if k=='candidate']
    assert len(cards)==10 and [c['rank'] for c in cards]==list(range(1,11))
    assert received[11][0]=='notice' and '未配置 DeepSeek' in received[11][1]['message']
    assert next(v for k,v in received if k=='explanation')['source']=='rule'
    for payload in [dict(question_id='DELETE WHERE {}',position_id='pos001'),
                    dict(question_id='attention',position_id='pos001',limit=11),
                    dict(question_id='attention',position_id='x> SERVICE <http://evil>')]:
        assert client.post('/api/agent/ask',json=payload).status_code==422


def test_optional_deepseek_stream_and_failure_never_change_cards(settings, store):
    store.write_track(track(settings,'first',30,datetime.now(timezone.utc)))
    settings.deepseek_api_key = __import__('pydantic').SecretStr('test-secret')
    snapshot = agent.build_analysis(store,settings,'attention','pos001')
    requests=[]
    def handle(request):
        payload=json.loads(request.content); requests.append(payload)
        assert payload['stream'] is True and 'tools' not in payload
        assert 'test-secret' not in request.content.decode()
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':'根据既定策略，首位需关注。'}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n')
    async def collect(transport):
        return [part async for part in agent.answer_events(snapshot,settings,transport=transport)]
    result = asyncio.run(collect(httpx.MockTransport(handle)))
    assert any('deepseek' in part for part in result)
    assert len([p for p in result if p.startswith('event: candidate')])==1
    assert json.loads(requests[0]['messages'][1]['content'])['candidates'][0]['rank']==1
    sent = json.loads(requests[0]['messages'][1]['content'])
    assert sent['rdf_evidence'] == snapshot['evidence']
    assert any(row['origin']=='观测、评估与规则快照' for row in sent['rdf_evidence'])
    assert any(row['origin']=='本体规则' for row in sent['rdf_evidence'])
    assert any(p.startswith('event: explanation_audit') and '"has_citations": false' in p for p in result)
    failed = asyncio.run(collect(httpx.MockTransport(lambda request:httpx.Response(401))))
    assert any(p.startswith('event: explanation_error') for p in failed)
    assert failed[-1].startswith('event: done')


def test_incomplete_model_stream_reported_as_incomplete(settings, store):
    store.write_track(track(settings,'first',30,datetime.now(timezone.utc)))
    settings.deepseek_api_key = __import__('pydantic').SecretStr('test-secret')
    snapshot = agent.build_analysis(store,settings,'attention','pos001')
    transport=httpx.MockTransport(lambda request:httpx.Response(200,text='data: {"choices":[{"delta":{"content":"部分文字"}}]}\n\n'))
    async def collect():
        return [part async for part in agent.answer_events(snapshot,settings,transport=transport)]
    result=asyncio.run(collect())
    assert any(p.startswith('event: explanation_error') for p in result)


def test_model_citation_audit_reports_unknown_ids(settings, store):
    store.write_track(track(settings,'first',30,datetime.now(timezone.utc)))
    settings.deepseek_api_key = __import__('pydantic').SecretStr('test-secret')
    snapshot = agent.build_analysis(store,settings,'nearest','pos001')
    transport=httpx.MockTransport(lambda request:httpx.Response(200,text='data: '+json.dumps(
        {'choices':[{'delta':{'content':'依据 [E1] 和 [E99999]。'}}]},ensure_ascii=False)+'\n\ndata: [DONE]\n\n'))
    async def collect():
        return [part async for part in agent.answer_events(snapshot,settings,transport=transport)]
    result=asyncio.run(collect())
    audit = next(json.loads(part.split('\ndata: ')[1]) for part in result if part.startswith('event: explanation_audit'))
    assert audit['has_citations'] and audit['unknown'] == ['E99999']


def test_empty_snapshot_skips_model(settings, store):
    client = TestClient(create_app(settings,store,enable_mqtt=False))
    response=client.post('/api/agent/ask',json={'question_id':'attention','position_id':'pos001'})
    received=events(response)
    assert not any(k=='candidate' for k,v in received)
    assert any(k=='notice' and '没有' in v['message'] for k,v in received)


def test_high_zone_uses_rdf_level_rule_and_sends_bounded_related_evidence(settings, store):
    now = datetime.now(timezone.utc)
    for target, distance, age in [('inside', 50, 1), ('outside', 180, 1), ('stale', 30, 60)]:
        store.write_track(track(settings, target, distance, now-timedelta(seconds=age)))
    snapshot = agent.build_analysis(store, settings, 'high_zone', 'pos001')
    assert [c['target_id'] for c in snapshot['candidates']] == ['inside']
    assert snapshot['filtered_out'] == 1
    assert [e['target_id'] for e in snapshot['excluded']] == ['stale']
    statements = snapshot['evidence']
    assert len(statements) <= 500
    assert any(e['predicate'] == CU.requiredDistanceLevel.n3() and e['object'] == CU.HighAttention.n3() for e in statements)
    assert any(e['predicate'] == CU.basedOnObservation.n3() for e in statements)
    assert any(e['predicate'] == CU.highThreshold.n3() for e in statements)
    assert not any(CU['outside'].n3() in (e['subject'], e['object']) for e in statements)
    rdf = Graph().parse(data='\n'.join(f"{e['subject']} {e['predicate']} {e['object']} ." for e in statements), format='nt')
    assert (CU['high-zone-policy-v1'], CU.requiredDistanceLevel, CU.HighAttention) in rdf
    assessment = CU[snapshot['candidates'][0]['assessment_id']]
    assert (assessment, CU.toPosition, CU.pos001) in rdf
    assert (assessment, CU.basedOnObservation, CU[snapshot['candidates'][0]['observation_id']]) in rdf


def test_high_zone_empty_result_does_not_claim_missing_observations(settings, store):
    store.write_track(track(settings, 'outside', 180, datetime.now(timezone.utc)))
    client = TestClient(create_app(settings,store,enable_mqtt=False))
    received = events(client.post('/api/agent/ask',json={'question_id':'high_zone','position_id':'pos001'}))
    snapshot = next(value for kind,value in received if kind=='snapshot')
    assert snapshot['eligible'] == 0 and snapshot['filtered_out'] == 1
    assert any(kind=='notice' and '没有符合高关注' in value['message'] for kind,value in received)
