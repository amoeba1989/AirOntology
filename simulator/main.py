"""固定路线往返模拟。停止进程后，页面在过期阈值后显示数据过期。"""
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
lon = float(os.getenv('POSITION_LON', '116.4077'))
lat = float(os.getenv('POSITION_LAT', '39.9045'))
step = 0
previous_position = None
try:
    while not stop.is_set():
        if not connected.wait(1):
            continue
        # 距离从380米接近到20米再远离，每个完整周期约72秒。
        distance = 200 + 180 * math.cos(step * math.pi / 36)
        target_lon, target_lat, _ = geod.fwd(lon, lat, 65, distance)
        speed = 0.0 if previous_position is None else geod.inv(*previous_position, target_lon, target_lat)[2]
        payload = json.dumps({'target_id': 'drone001', 'lon': target_lon, 'lat': target_lat,
                              'speed': speed, 'timestamp': datetime.now(timezone.utc).isoformat()})
        result = client.publish(os.getenv('MQTT_TOPIC', 'counteruav/track/blue'), payload, qos=1, retain=False)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f'已发布 drone001，距离约 {distance:.1f} 米', flush=True)
            previous_position = (target_lon, target_lat)
            step += 1
        stop.wait(1)
finally:
    client.disconnect()
    client.loop_stop()
