import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Path as PathParam
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from rdflib import Graph, OWL, RDFS, RDF
from .config import Settings
from .domain import LEVELS
from .store import FusekiStore
from .consumer import Consumer

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')


def create_app(settings=None, store=None, enable_mqtt=True):
    settings = settings or Settings()
    store = store or FusekiStore(settings)
    consumer = Consumer(settings, store)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize_with_retry()
        if enable_mqtt:
            consumer.start()
        try:
            yield
        finally:
            if enable_mqtt:
                consumer.stop()
            store.close()

    app = FastAPI(title='AirOntology 无人机本体演示', lifespan=lifespan)
    app.state.store = store
    app.state.consumer = consumer

    @app.get('/api/health')
    def health():
        try:
            fuseki = store.ready()
        except Exception:
            fuseki = False
        status = consumer.status()
        return {'status': 'ok' if fuseki and status['connected'] and not status['last_error'] else 'degraded',
                'fuseki': fuseki, 'mqtt': status}

    @app.get('/api/ontology')
    def ontology():
        graph = Graph().parse(settings.ontology_dir / 'cu_ontology.ttl', format='turtle')
        items = []
        for kind, title in [(OWL.Class, '类'), (OWL.DatatypeProperty, '数据属性'), (OWL.ObjectProperty, '对象属性')]:
            for subject in sorted(graph.subjects(RDF.type, kind)):
                items.append({'uri': str(subject), 'id': str(subject).split('#')[-1], 'kind': title,
                              'label': str(graph.value(subject, RDFS.label) or subject),
                              'comment': str(graph.value(subject, RDFS.comment) or ''),
                              'range': str(graph.value(subject, RDFS.range) or '').split('#')[-1]})
        return {'items': items, 'namespace': 'http://counteruav.org/counterUav#'}

    @app.get('/api/ontology/ttl', response_class=PlainTextResponse)
    def ontology_ttl():
        return PlainTextResponse((settings.ontology_dir / 'cu_ontology.ttl').read_text(), media_type='text/turtle')

    def targets(target_id=None):
        try:
            rows = store.situation(target_id)
        except Exception as error:
            logging.exception('态势查询失败')
            raise HTTPException(503, '本体数据服务暂不可用') from error
        output = []
        now = datetime.now(timezone.utc)
        for row in rows:
            level_id = row['level'].split('#')[-1]
            label, color = LEVELS.get(level_id, ('未知', '#7b8794'))
            age = max(0, (now - datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))).total_seconds())
            output.append({'id': row['target'].split('#')[-1], 'uri': row['target'], 'name': row['name'],
                           **{key: float(row[key]) for key in ('lon', 'lat', 'speed', 'distance')},
                           'timestamp': row['timestamp'], 'level': level_id, 'level_label': label,
                           'color': color, 'position_uri': row['position'], 'stale': age > settings.stale_seconds,
                           'age_seconds': round(age, 1)})
        return output

    @app.get('/api/situation')
    def situation():
        return {'position': {'id': settings.position_id, 'name': settings.position_name,
                             'lon': settings.position_lon, 'lat': settings.position_lat},
                'thresholds': [settings.high_threshold, settings.medium_threshold, settings.low_threshold],
                'stale_seconds': settings.stale_seconds, 'targets': targets(),
                'server_time': datetime.now(timezone.utc).isoformat()}

    @app.get('/api/targets/{target_id}')
    def target(target_id: str = PathParam(pattern=r'^[A-Za-z0-9_-]{1,100}$')):
        rows = targets(target_id)
        if not rows:
            raise HTTPException(404, '目标不存在')
        return rows[0]

    @app.get('/api/targets/{target_id}/ttl', response_class=PlainTextResponse)
    def target_ttl(target_id: str = PathParam(pattern=r'^[A-Za-z0-9_-]{1,100}$')):
        if not targets(target_id):
            raise HTTPException(404, '目标不存在')
        try:
            return PlainTextResponse(store.target_ttl(target_id), media_type='text/turtle')
        except Exception as error:
            raise HTTPException(503, '实例导出失败') from error

    static_dir = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    if static_dir.is_dir():
        app.mount('/', StaticFiles(directory=static_dir, html=True), name='frontend')
    return app


app = create_app()
