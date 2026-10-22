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
print('通过：多目标独立评估、MQTT、历史回放、TTL、本体词典、五个Fuseki只读查询、SHACL正常/异常/实时校验')
