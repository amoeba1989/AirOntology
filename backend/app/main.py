import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import threading
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
from pydantic import BaseModel, Field
from . import learning


class TurtleInput(BaseModel):
    ttl: str = Field(min_length=1, max_length=32768)


class QueryInput(BaseModel):
    query_id: str = Field(pattern='^(current|nearby|evidence|history|graphs)$')
    target_id: str | None = Field(default=None, pattern=ID_PATTERN)
    position_id: str | None = Field(default=None, pattern=ID_PATTERN)

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

    app = FastAPI(title='AirOntology 无人机本体工作台', version='2.1.0', lifespan=lifespan)
    app.state.store, app.state.consumer = store, consumer
    validation_lock = threading.Lock()

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
                'fuseki':fuseki, 'mqtt':status, 'version':'2.1.0'}

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

    def learning_model():
        return learning.model_graph(store, settings.ontology_dir)

    @app.get('/api/learning/dictionary')
    def dictionary():
        def read():
            with store.lock:
                model, source = learning_model()
                return {'items': learning.dictionary(model), 'source': source,
                        'ttl': model.serialize(format='turtle'), 'graph': str(learning.LEARNING),
                        'note': '独立学习模型不会改变距离计算或业务 TBox；重启后导入模型仍保留。'}
        return safe(read)

    @app.get('/api/learning/term')
    def term(uri: str = Query(min_length=1, max_length=500)):
        def read():
            with store.lock:
                model, _ = learning_model()
                try:
                    return learning.term_view(model, learning.current_graph(store, settings.ontology_dir), uri)
                except ValueError as error:
                    raise HTTPException(404, str(error)) from error
        return safe(read)

    @app.post('/api/learning/model/preview')
    def preview_model(body: TurtleInput):
        try:
            g = learning.parse_turtle(body.ttl)
            return {'items': learning.validate_model(g), 'triple_count': len(g),
                    'ttl': g.serialize(format='turtle')}
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.put('/api/learning/model')
    def import_model(body: TurtleInput):
        preview_model(body)
        def write():
            with store.lock:
                g = learning.parse_turtle(body.ttl)
                store.update(f'CLEAR SILENT GRAPH <{learning.LEARNING}>; INSERT DATA {{ GRAPH <{learning.LEARNING}> {{ {g.serialize(format="nt")} }} }}')
                return {'status': 'imported', 'graph': str(learning.LEARNING)}
        return safe(write)

    @app.delete('/api/learning/model')
    def reset_model():
        def reset():
            with store.lock:
                store.update(f'CLEAR SILENT GRAPH <{learning.LEARNING}>')
            return {'status': 'reset'}
        return safe(reset)

    @app.get('/api/learning/queries')
    def query_catalog():
        return {'items': learning.CATALOG, 'scope': '查询实时业务命名图，不随历史回放切换。最多返回 100 行。'}

    @app.post('/api/learning/query')
    def run_query(body: QueryInput):
        spec = next(item for item in learning.CATALOG if item['id'] == body.query_id)
        if any(not getattr(body, p) for p in spec['parameters']):
            raise HTTPException(422, '请先选择查询需要的无人机或阵地')
        def read():
            with store.lock:
                sparql = learning.preset_query(body.query_id, store.config, body.target_id, body.position_id)
                result = store.query(sparql)
            return {'query_id': body.query_id, 'sparql': sparql, 'variables': result['head']['vars'],
                    'rows': result['results']['bindings'], 'note': spec['note'],
                    'executed_at': datetime.now().astimezone().isoformat()}
        return safe(read)

    @app.get('/api/learning/validation/examples')
    def validation_examples():
        from datetime import timezone
        from .domain import Track, observation_graphs
        from rdflib import Literal, XSD
        config = settings.initial_config()
        state, history = observation_graphs(Track(target_id='example-drone', lon=116.408,
            lat=39.9045, speed=2, timestamp=datetime(2026, 10, 22, tzinfo=timezone.utc)), config)
        valid = state + history + store.config_graph(config)
        invalid = valid.__class__()
        invalid += valid
        obs = next(invalid.subjects(RDF.type, CU.Observation))
        invalid.remove((obs, CU.timestamp, None))
        invalid.set((obs, CU.lon, Literal('不是数值')))
        assessment = next(invalid.subjects(RDF.type, CU.Assessment))
        invalid.add((assessment, CU.toPosition, CU.extraPosition))
        return {'valid': valid.serialize(format='turtle'), 'invalid': invalid.serialize(format='turtle'),
                'shapes': (settings.ontology_dir / 'shapes.ttl').read_text(),
                'note': '异常样例包含缺失观测时间、经度类型错误、同一评估关联两个阵地。'}

    def check_graph(g, scope):
        if not validation_lock.acquire(blocking=False):
            raise HTTPException(429, '已有校验正在运行，请稍后重试')
        try:
            return {**learning.validate_facts(g, settings.ontology_dir), 'scope': scope}
        finally:
            validation_lock.release()

    @app.post('/api/learning/validation')
    def validate_sample(body: TurtleInput):
        try:
            g = learning.parse_turtle(body.ttl)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return safe(lambda: check_graph(g, '编辑器中的 RDF 样例；未写入业务数据库'))

    @app.post('/api/learning/validation/current')
    def validate_current():
        def read():
            with store.lock:
                g = learning.current_graph(store, settings.ontology_dir)
            return check_graph(g, '当前最多 100 架无人机的最新事实及当前阵地；不随回放切换，不含全部历史')
        return safe(read)

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
