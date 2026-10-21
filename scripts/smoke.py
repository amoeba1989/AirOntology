"""对运行中的完整服务做验收：默认http://127.0.0.1:8092。"""
import json
import os
import time
import urllib.request

base = os.getenv('AIRONTOLOGY_URL', 'http://127.0.0.1:8092')
def get(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base + path, timeout=10) as response:
        return response.read().decode()

for attempt in range(45):
    try:
        health = json.loads(get('/api/health'))
        situation = json.loads(get('/api/situation'))
        if health['status'] == 'ok' and situation['targets'] and not situation['targets'][0]['stale']:
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit('完整服务未就绪：请检查app、mqtt、fuseki及simulator日志')

before = situation['targets'][0]
assert 'owl:Class' in get('/api/ontology/ttl')
assert 'drone001' in get('/api/targets/drone001/ttl')
assert len(json.loads(get('/api/ontology'))['items']) == 11
assert 'AirOntology' in get('/')
for attempt in range(10):
    time.sleep(1)
    after = json.loads(get('/api/situation'))['targets'][0]
    if after['timestamp'] != before['timestamp'] and after['lon'] != before['lon']:
        break
else:
    raise AssertionError('目标未持续更新')
assert after['distance'] >= 0
print('通过：依赖健康、MQTT更新、态势API、本体结构、定义与实例TTL、前端静态入口')
