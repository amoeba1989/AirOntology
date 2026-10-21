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
print('通过：三目标×多阵地独立评估、MQTT更新、观测依据、规则版本、历史回放及TTL接口')
