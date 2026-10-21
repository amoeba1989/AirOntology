import logging
import queue
import threading
import time
import paho.mqtt.client as mqtt
from .domain import Track

logger = logging.getLogger(__name__)


class Consumer:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.queue = queue.Queue(maxsize=settings.queue_size)
        self.stop_event = threading.Event()
        self.connected = False
        self.last_error = None
        self.last_write = None
        self.rejected = 0
        self.dropped = 0
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.mqtt_client_id)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(1, 10)
        self.worker = threading.Thread(target=self.run, daemon=True)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if self.connected:
            client.subscribe(self.settings.mqtt_topic, qos=1)
            logger.info('MQTT连接成功并订阅 %s', self.settings.mqtt_topic)

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False

    def on_message(self, client, userdata, message):
        try:
            if len(message.payload) > 16384:
                raise ValueError('报文超过16KB')
            track = Track.model_validate_json(message.payload)
            self.queue.put_nowait(track)
        except queue.Full:
            self.dropped += 1
            logger.warning('队列已满，丢弃本次报文')
        except (ValueError, TypeError):
            self.rejected += 1
            logger.warning('已拒绝非法航迹报文')

    def run(self):
        while not self.stop_event.is_set():
            try:
                track = self.queue.get(timeout=.3)
            except queue.Empty:
                continue
            for attempt in range(3):
                try:
                    self.store.write_track(track)
                    self.last_write = time.time()
                    self.last_error = None
                    break
                except Exception:
                    self.last_error = '实例写入失败，请查看后端日志'
                    logger.exception('Fuseki实例写入失败，第%s次尝试', attempt + 1)
                    if self.stop_event.wait(.5 * (attempt + 1)):
                        break
            self.queue.task_done()

    def start(self):
        self.worker.start()
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, 30)
        self.client.loop_start()

    def stop(self):
        self.stop_event.set()
        self.client.disconnect()
        self.client.loop_stop()
        self.worker.join(timeout=10)

    def status(self):
        return {'connected': self.connected, 'queue_size': self.queue.qsize(),
                'rejected': self.rejected, 'dropped': self.dropped,
                'last_write': self.last_write, 'last_error': self.last_error}
