"""三架无人机的固定路线演示。停止进程即可演示观测过期。"""
import json
import math
import os
import signal
import threading
import time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
from pyproj import Geod

stop = threading.Event()
connected = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: stop.set())
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='airontology-simulator')


def on_connect(client, userdata, flags, reason_code, properties):
    if not reason_code.is_failure:
        connected.set()


def on_disconnect(client, userdata, flags, reason_code, properties):
    connected.clear()


client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.reconnect_delay_set(1, 10)
client.connect_async(os.getenv('MQTT_HOST', 'localhost'), int(os.getenv('MQTT_PORT', '1883')), 30)
client.loop_start()
geod = Geod(ellps='WGS84')
lon, lat = float(os.getenv('POSITION_LON', '116.4077')), float(os.getenv('POSITION_LAT', '39.9045'))
step, previous = 0, {}
try:
    while not stop.is_set():
        if not connected.wait(1):
            continue
        now = time.monotonic()
        for index, (bearing, phase) in enumerate([(65, 0), (110, 2.1), (290, 4.2)], start=1):
            target_id = f'drone{index:03d}'
            distance = 260 + 240 * math.cos(step * math.pi / 36 + phase)
            target_lon, target_lat, _ = geod.fwd(lon, lat, bearing, distance)
            old = previous.get(target_id)
            speed = 0 if old is None else geod.inv(old[0], old[1], target_lon, target_lat)[2]/max(.001, now-old[2])
            payload = json.dumps({'target_id': target_id, 'name':f'无人机{index:03d}',
                'source':'固定航线模拟器', 'lon':target_lon, 'lat':target_lat, 'speed':speed,
                'timestamp':datetime.now(timezone.utc).isoformat()})
            result = client.publish(os.getenv('MQTT_TOPIC', 'counteruav/track/blue'), payload, qos=1, retain=False)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                previous[target_id] = (target_lon, target_lat, now)
        print(f'已发布3架无人机观测，演示步数 {step}', flush=True)
        step += 1
        stop.wait(1)
finally:
    client.disconnect()
    client.loop_stop()
