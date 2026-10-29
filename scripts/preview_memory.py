#!/usr/bin/env python3
"""Local, disposable RDF preview. Never connects to the ECS, Fuseki or MQTT."""
import os
import logging
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import uvicorn
from fastapi.responses import JSONResponse
from rdflib import Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings
from app.demo_telemetry import make_registry, make_frame
from app.domain import GEOD
from app.main import create_app
from app.store import FusekiStore
from app import telemetry


def create_preview():
    settings = Settings(fuseki_url='http://preview.invalid/counteruav', mqtt_host='127.0.0.1',
                        stale_seconds=30, history_limit=10)
    dataset, dataset_lock = Dataset(), threading.RLock()

    def handle(request):
        with dataset_lock:
            if request.url.path.endswith('/update'):
                dataset.update(request.content.decode())
                return httpx.Response(204)
            query = parse_qs(request.content.decode())['query'][0]
            result = dataset.query(query)
            if result.type == 'CONSTRUCT':
                return httpx.Response(200, text=result.graph.serialize(format='nt'))
            return httpx.Response(200, content=result.serialize(format='json'))

    store = FusekiStore(settings)
    store.client.close()
    store.client = httpx.Client(transport=httpx.MockTransport(handle), timeout=30)
    app = create_app(settings, store, enable_mqtt=False)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        stop = threading.Event()
        async with original_lifespan(application):
            registry = make_registry(settings, 'preview-' + uuid4().hex, count=4)
            telemetry.register(store, registry)

            def preview_frame(tick):
                frame = make_frame(settings, registry, tick, interval=10)
                # Keep one synthetic target within the first position's high-distance
                # threshold so all three questions can be explored immediately.
                first = next(entity for entity in frame.payload.entities if entity.id == 1)
                position = store.config.positions[0]
                radius = min(65.0, store.config.high_threshold * 0.65)
                bearing = (tick * 20) % 360
                lon, lat, _ = GEOD.fwd(position.lon, position.lat, bearing, radius)
                first.transform.longitude_deg, first.transform.latitude_deg = lon, lat
                first.transform.yaw_deg = (bearing + 90) % 360
                first.motion.speed_mps = first.flight.airspeed_mps = radius * 0.0347
                return frame

            telemetry.ingest(store, preview_frame(0))

            def simulate():
                tick = 1
                while not stop.wait(10):
                    try:
                        telemetry.ingest(store, preview_frame(tick))
                        tick += 1
                    except Exception:
                        import logging
                        logging.exception('本地预览模拟观测失败')

            worker = threading.Thread(target=simulate, name='preview-observations', daemon=True)
            worker.start()
            try:
                yield
            finally:
                stop.set()
                worker.join(timeout=10)

    app.router.lifespan_context = lifespan

    @app.middleware('http')
    async def preview_health(request, call_next):
        if request.url.path == '/api/health':
            return JSONResponse({'status':'preview', 'preview':True, 'fuseki':False,
                                 'mqtt':{'connected':False, 'last_error':None}, 'version':'2.4.0'})
        return await call_next(request)

    return app


if __name__ == '__main__':
    print('本地预览：内存 RDF 与模拟观测，重启后清空；不连接 ECS、Fuseki 或 MQTT。', flush=True)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    uvicorn.run(create_preview(), host='127.0.0.1', port=int(os.getenv('PREVIEW_PORT', '8093')), access_log=False)
