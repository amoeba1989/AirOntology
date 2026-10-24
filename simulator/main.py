"""Publish explicit device registration and telemetry over MQTT for ontology learning."""
import os
import signal
import threading
from uuid import uuid4
import paho.mqtt.client as mqtt
from app.config import Settings
from app.demo_telemetry import make_registry, make_frame


def main():
    settings=Settings()
    stop=threading.Event();connected=threading.Event();needs_registration=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='airontology-simulator')
    def on_connect(client,userdata,flags,reason_code,properties):
        if not reason_code.is_failure:needs_registration.set();connected.set()
    def on_disconnect(client,userdata,flags,reason_code,properties):connected.clear()
    client.on_connect=on_connect;client.on_disconnect=on_disconnect;client.reconnect_delay_set(1,10)
    client.connect_async(settings.mqtt_host,settings.mqtt_port,30);client.loop_start()
    count=max(1,min(100,int(os.getenv('DEMO_TARGET_COUNT','16'))))
    interval=max(1,min(30,float(os.getenv('DEMO_INTERVAL_SECONDS','2'))))
    registry=make_registry(settings,uuid4().hex,count)
    tick=0
    try:
        while not stop.is_set():
            if not connected.wait(1):continue
            # Retain registration only. Frames are never retained/replayed as live data.
            if needs_registration.is_set() or tick%15==0:
                result=client.publish(settings.mqtt_registry_topic,registry.model_dump_json(),qos=1,retain=True)
                result.wait_for_publish(timeout=5)
                if not result.is_published():continue
                needs_registration.clear()
            frame=make_frame(settings,registry,tick,interval)
            client.publish(settings.mqtt_telemetry_topic,frame.model_dump_json(),qos=1,retain=False)
            print(f'模拟态势 tick={tick}：{count}架无人机、{len(registry.devices)-count}部登记设备；合成航线并非真实飞行',flush=True)
            tick+=1;stop.wait(interval)
    finally:
        client.disconnect();client.loop_stop()


if __name__=='__main__':main()
