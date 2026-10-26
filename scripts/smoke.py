"""对运行中的第二版服务做验收，默认http://127.0.0.1:8092。"""
import json
import os
import time
import urllib.request
from urllib.parse import quote

base=os.getenv('AIRONTOLOGY_URL','http://127.0.0.1:8092')
def get(path):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base+path,timeout=15) as response:
        return response.read().decode()

def post(path, body=None):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request=urllib.request.Request(base+path, data=json.dumps(body or {}).encode(),
        headers={'Content-Type':'application/json'}, method='POST')
    with opener.open(request,timeout=20) as response:
        return json.loads(response.read())

assert '<div id="app"></div>' in get('/back'), '本体学习路由须支持直接打开与刷新'

for attempt in range(60):
    try:
        health=json.loads(get('/api/health'))
        situation=json.loads(get('/api/situation'))
        if health['status']=='ok' and len(situation['targets'])>=3 and all(not t['stale'] for t in situation['targets']):
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit('演示未就绪：请检查app、mqtt、fuseki及simulator日志')

assert len(situation['positions'])>=1
assert len(situation['assessments'])==len(situation['targets'])*len(situation['positions'])
assert 'owl:Class' in get('/api/ontology/ttl')
assert 'basedOnObservation' in get('/api/targets/drone001/ttl')
assert {'Observation','Assessment','DistanceRule'} <= {i['id'] for i in json.loads(get('/api/ontology'))['items']}
assert 'AirOntology' in get('/')
before=situation['targets'][0]
for attempt in range(10):
    time.sleep(1)
    after=json.loads(get('/api/situation'))['targets'][0]
    if after['timestamp']!=before['timestamp'] and after['lon']!=before['lon']:
        break
else:
    raise AssertionError('目标未持续更新')
assert after['assessments'][0]['distance']>=0
history=json.loads(get('/api/history?target_id=drone001&limit=30'))
assert history['records']
replay=json.loads(get('/api/situation?at='+quote(history['records'][0]['timestamp'],safe='')))
assert replay['mode']=='replay'
entry=situation['assessments'][0]
detail=json.loads(get('/api/assessments/'+entry['id']))
assert detail['rule_version'] and detail['observation']['source']
dictionary=json.loads(get('/api/learning/dictionary'))
assert dictionary['items'] and dictionary['source']=='business'
term=json.loads(get('/api/learning/term?uri='+quote('http://counteruav.org/counterUav#Observation',safe='')))
assert term['examples'] and term['relations'] and term['ttl']
assert post('/api/learning/model/preview', {'ttl':dictionary['ttl']})['items']
queries=json.loads(get('/api/learning/queries'))['items']
assert len(queries)==5
for query in queries:
    result=post('/api/learning/query', {'query_id':query['id'],
        'target_id':before['id'], 'position_id':situation['positions'][0]['id']})
    assert result['sparql'] and isinstance(result['rows'],list)
    if query['id']!='nearby':
        assert result['rows'], query['id']
examples=json.loads(get('/api/learning/validation/examples'))
assert post('/api/learning/validation', {'ttl':examples['valid']})['conforms']
invalid=post('/api/learning/validation', {'ttl':examples['invalid']})
assert not invalid['conforms'] and invalid['result_count']>=3
current=post('/api/learning/validation/current')
assert current['conforms'] and current['focus_count']>0, current
agent_questions=json.loads(get('/api/agent/questions'))
assert {q['id'] for q in agent_questions['items']}=={'attention','nearest'}
# CI never calls a paid model; production smoke can skip the stream if configured.
if not agent_questions['llm_configured']:
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request=urllib.request.Request(base+'/api/agent/ask',data=json.dumps({
        'question_id':'attention','position_id':situation['positions'][0]['id']}).encode(),
        headers={'Content-Type':'application/json'},method='POST')
    with opener.open(request,timeout=30) as response:
        stream=response.read().decode()
    assert 'event: snapshot' in stream and 'event: candidate' in stream and 'event: done' in stream
    assert 'attention-policy-v1' in stream and '未配置 DeepSeek' in stream
print('通过：多目标独立评估、MQTT、回放、本体词典、Fuseki查询、SHACL校验、策略排序与流式卡片')

# Real MQTT simulator → consumer → Fuseki → API path, not direct HTTP fixture writes.
devices=json.loads(get('/api/devices'))
assert len(devices['devices'])>=7
assert {d['kind'] for d in devices['devices']}=={'uav','radar','jammer'}
assert devices['frame']['payload']['tick']>=0
assert all(d['state'] and d['in_latest_frame'] for d in devices['devices'])
assert len(json.loads(get('/api/devices/deployments'))['rows'])==4
assert 'deployedAt' in get('/api/devices/ttl')
validation=post('/api/devices/validate')
assert validation['conforms'],validation
assert all('jammer' not in d['state'] for d in devices['devices'] if d['kind']=='radar')
print('通过：MQTT设备登记、四类对象、态势适配、显式部署关系、设备SHACL校验')
