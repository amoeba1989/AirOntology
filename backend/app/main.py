import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Path as PathParam, Query
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from rdflib import Graph, OWL, RDFS, RDF
from .config import Settings
from .domain import CU
from .models import ConfigChange, ID_PATTERN
from .store import FusekiStore, ConfigConflict
from .consumer import Consumer
from .views import situation_view, assessment_view, text

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')


def validate_at(at):
    if at and at.tzinfo is None:
        raise HTTPException(422, '回放时间必须包含时区')


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

    app = FastAPI(title='AirOntology 无人机本体工作台', version='2.0.0', lifespan=lifespan)
    app.state.store, app.state.consumer = store, consumer

    def safe(operation):
        try:
            return operation()
        except HTTPException:
            raise
        except Exception as error:
            logging.exception('本体数据操作失败')
            raise HTTPException(503, '本体数据服务暂不可用，请查看后端日志') from error

    @app.get('/api/health')
    def health():
        try:
            fuseki = store.ready()
        except Exception:
            fuseki = False
        status = consumer.status()
        return {'status':'ok' if fuseki and status['connected'] and not status['last_error'] else 'degraded',
                'fuseki':fuseki, 'mqtt':status, 'version':'2.0.0'}

    @app.get('/api/config')
    def config():
        return store.get_config()

    @app.put('/api/config')
    def save_config(change: ConfigChange):
        try:
            return store.set_config(change.config, change.expected_version)
        except ConfigConflict as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except Exception as error:
            logging.exception('配置保存失败')
            raise HTTPException(503, '配置保存失败，请稍后重试') from error

    @app.get('/api/ontology')
    def ontology():
        graph = Graph().parse(settings.ontology_dir / 'cu_ontology.ttl', format='turtle')
        items=[]
        for kind,title in [(OWL.Class,'类'),(OWL.DatatypeProperty,'数据属性'),(OWL.ObjectProperty,'对象属性')]:
            for subject in sorted(graph.subjects(RDF.type,kind)):
                items.append({'uri':str(subject),'id':str(subject).split('#')[-1],'kind':title,
                    'label':str(graph.value(subject,RDFS.label) or subject),
                    'comment':str(graph.value(subject,RDFS.comment) or ''),
                    'range':str(graph.value(subject,RDFS.range) or '').split('#')[-1]})
        return {'items':items, 'namespace':str(CU)}

    @app.get('/api/ontology/ttl',response_class=PlainTextResponse)
    def ontology_ttl():
        return PlainTextResponse((settings.ontology_dir/'cu_ontology.ttl').read_text(),media_type='text/turtle')

    def snapshot(at=None, target_id=None):
        validate_at(at)
        with store.lock:
            return situation_view(store.snapshot_graph(at,target_id),store.config,at)

    @app.get('/api/situation')
    def situation(at:datetime|None=None):
        return safe(lambda:snapshot(at))

    @app.get('/api/targets/{target_id}')
    def target(target_id:str=PathParam(pattern=ID_PATTERN),at:datetime|None=None):
        result=safe(lambda:snapshot(at,target_id))['targets']
        if not result:
            raise HTTPException(404,'目标不存在或该时间没有保留的观测')
        return result[0]

    @app.get('/api/targets/{target_id}/ttl',response_class=PlainTextResponse)
    def target_ttl(target_id:str=PathParam(pattern=ID_PATTERN),at:datetime|None=None):
        target(target_id,at)
        return PlainTextResponse(safe(lambda:store.target_ttl(target_id,at)),media_type='text/turtle')

    @app.get('/api/assessments/{assessment_id}')
    def assessment(assessment_id:str=PathParam(pattern=r'^eval-[a-f0-9]{24}$')):
        g=safe(lambda:store.assessment_graph(assessment_id))
        subject=CU[assessment_id]
        if (subject,RDF.type,CU.Assessment) not in g:
            raise HTTPException(404,'评估不存在或已超过历史保留范围')
        return assessment_view(g,subject)

    @app.get('/api/assessments/{assessment_id}/ttl',response_class=PlainTextResponse)
    def assessment_ttl(assessment_id:str=PathParam(pattern=r'^eval-[a-f0-9]{24}$')):
        g=safe(lambda:store.assessment_graph(assessment_id))
        if not len(g):
            raise HTTPException(404,'评估不存在或已超过历史保留范围')
        return PlainTextResponse(g.serialize(format='turtle'),media_type='text/turtle')

    @app.get('/api/history')
    def history(target_id:str=Query(pattern=ID_PATTERN),limit:int=Query(default=300,ge=1,le=1000)):
        g=safe(lambda:store.history_graph(target_id,limit))
        records=[]
        for obs in g.subjects(RDF.type,CU.Observation):
            evaluations=[assessment_view(g,s) for s in g.subjects(CU.basedOnObservation,obs)]
            records.append({'id':str(obs).split('#')[-1], 'timestamp':text(g,obs,'timestamp'),
                'lon':float(text(g,obs,'lon')), 'lat':float(text(g,obs,'lat')), 'source':text(g,obs,'source'),
                'assessments':sorted(evaluations,key=lambda e:e['distance'])})
        records.sort(key=lambda record:datetime.fromisoformat(record['timestamp']))
        return {'target_id':target_id,'records':records,'count':len(records),
                'note':'仅包含当前仍保留的观测；回放期间实时接入继续运行'}

    static_dir=Path(__file__).resolve().parents[2]/'frontend'/'dist'
    if static_dir.is_dir():
        app.mount('/',StaticFiles(directory=static_dir,html=True),name='frontend')
    return app


app=create_app()
