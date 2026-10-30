import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import threading
import re
import httpx
from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse, Response, FileResponse
from starlette.concurrency import run_in_threadpool
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
from . import agent
from . import evidence
from . import telemetry
from pydantic import ValidationError


class TurtleInput(BaseModel):
    ttl: str = Field(min_length=1, max_length=32768)


class QueryInput(BaseModel):
    query_id: str = Field(pattern='^(current|nearby|evidence|history|graphs)$')
    target_id: str | None = Field(default=None, pattern=ID_PATTERN)
    position_id: str | None = Field(default=None, pattern=ID_PATTERN)


class AgentQuestion(BaseModel):
    question_id: str = Field(pattern='^(attention|nearest|high_zone)$')
    position_id: str = Field(pattern=ID_PATTERN)
    limit: int = Field(default=10, ge=1, le=10)

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

    app = FastAPI(title='AirOntology 无人机本体工作台', version='2.4.0', lifespan=lifespan)
    app.state.store, app.state.consumer = store, consumer
    validation_lock = threading.Lock()
    agent_slots = threading.BoundedSemaphore(2)

    @app.get('/api/devices')
    def devices():
        return safe(lambda:telemetry.view(store))

    @app.get('/api/devices/ttl',response_class=PlainTextResponse)
    def devices_ttl():
        return PlainTextResponse(safe(lambda:telemetry.facts(store).serialize(format='turtle')),media_type='text/turtle')

    @app.get('/api/devices/deployments')
    def device_deployments(position_id:str|None=Query(default=None,pattern=ID_PATTERN)):
        query=telemetry.deployment_query(position_id)
        result=safe(lambda:store.query(query))
        return {'sparql':query,'variables':result['head']['vars'],'rows':result['results']['bindings']}

    @app.post('/api/devices/validate')
    def devices_validate():
        return safe(lambda:check_graph(telemetry.facts(store),'模拟设备、部署关系与最新状态；仅校验结构'))

    @app.get('/api/evidence')
    def evidence_view():
        return safe(lambda:evidence.view(store))

    @app.get('/api/evidence/ttl',response_class=PlainTextResponse)
    def evidence_ttl():
        return PlainTextResponse(safe(lambda:evidence.read_graph(store).serialize(format='turtle')),media_type='text/turtle')

    @app.post('/api/evidence/validate')
    def validate_evidence():
        return safe(lambda:check_graph(evidence.read_graph(store),'多源证据图；校验结构约束，不证明传感器或算法性能'))

    @app.post('/api/evidence/demo')
    def evidence_demo():
        try:
            return evidence.seed_demo(store)
        except evidence.EvidenceConflict as error:
            raise HTTPException(409,str(error)) from error
        except Exception as error:
            logging.exception('示例写入失败')
            raise HTTPException(503,'证据存储暂不可用，部分示例可能已写入，请先刷新') from error

    @app.get('/api/evidence/examples')
    def evidence_examples():
        return evidence.examples()

    @app.post('/api/evidence/{kind}')
    def ingest_evidence(kind:str=PathParam(pattern='^(devices|observations|judgements|regions|authorizations)$'),body:dict=None):
        try:
            import json
            if len(json.dumps(body,ensure_ascii=False).encode())>65536:
                raise ValueError('证据记录超过64KB')
            record=evidence.MODELS[kind].model_validate(body)
            return evidence.save(store,kind,record)
        except ValidationError as error:
            details='；'.join('.'.join(map(str,e['loc']))+': '+e['msg'] for e in error.errors())
            raise HTTPException(422,details) from error
        except evidence.EvidenceConflict as error:
            raise HTTPException(409,str(error)) from error
        except ValueError as error:
            raise HTTPException(422,str(error)) from error
        except Exception as error:
            logging.exception('证据写入失败')
            raise HTTPException(503,'证据存储暂不可用') from error

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
                'fuseki':fuseki, 'mqtt':status, 'version':'2.4.0'}

    @app.get('/api/map/config')
    def map_config():
        enabled=bool(settings.amap_js_key and settings.amap_security_js_code.get_secret_value())
        return {'enabled':enabled, 'key':settings.amap_js_key if enabled else ''}

    @app.api_route('/_AMapService/{path:path}',methods=['GET','POST'])
    async def amap_service(path:str,request:Request):
        code=settings.amap_security_js_code.get_secret_value()
        if not settings.amap_js_key or not code:
            raise HTTPException(404,'高德地图尚未配置')
        if not re.fullmatch(r'v[1-9]/[A-Za-z0-9_/-]{1,100}',path):
            raise HTTPException(404,'无效地图服务路径')
        if request.query_params.get('key') != settings.amap_js_key:
            raise HTTPException(403,'地图 key 不匹配')
        base='https://webapi.amap.com/' if path.startswith('v4/map/styles') else 'https://restapi.amap.com/'
        params=[(k,v) for k,v in request.query_params.multi_items() if k!='jscode']+[('jscode',code)]
        try:
            async with httpx.AsyncClient(timeout=15,trust_env=False) as client:
                upstream=await client.request(request.method,base+path,params=params,
                    content=await request.body() if request.method=='POST' else None,
                    headers={'Content-Type':request.headers.get('content-type','application/octet-stream')})
        except httpx.HTTPError as error:
            logging.warning('高德地图服务转发失败：%s',type(error).__name__)
            raise HTTPException(502,'地图服务暂不可用') from error
        return Response(content=upstream.content,status_code=upstream.status_code,
                        media_type=upstream.headers.get('content-type','application/json'))

    @app.get('/api/agent/questions')
    def agent_questions():
        return {'items':agent.QUESTIONS, 'llm_configured':bool(settings.deepseek_api_key.get_secret_value()),
                'scope':agent.LIMIT_NOTE}

    @app.post('/api/agent/ask')
    async def ask_agent(body: AgentQuestion, request: Request):
        if not agent_slots.acquire(blocking=False):
            raise HTTPException(429, '已有态势分析正在运行，请稍后重试')
        try:
            snapshot = await run_in_threadpool(agent.build_analysis, store, settings,
                body.question_id, body.position_id, body.limit)
        except ValueError as error:
            agent_slots.release()
            raise HTTPException(422, str(error)) from error
        except asyncio.CancelledError:
            agent_slots.release()
            raise
        except Exception:
            agent_slots.release()
            logging.exception('态势分析快照生成失败')
            raise HTTPException(503, '态势数据服务暂不可用，请稍后重试')

        async def stream():
            try:
                async for chunk in agent.answer_events(snapshot, settings, request):
                    yield chunk
            finally:
                agent_slots.release()
        return StreamingResponse(stream(), media_type='text/event-stream',
            headers={'Cache-Control':'no-cache', 'X-Accel-Buffering':'no'})

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

    @app.get('/api/ontology/topology')
    def ontology_topology():
        from .topology import topology_view
        def read():
            with store.lock:
                return topology_view(store, settings.ontology_dir)
        return safe(read)

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
                    if uri in telemetry.TERMS or uri==str(CU.RadarSensor):
                        facts=telemetry.facts(store)
                        if uri in {str(CU.lat),str(CU.lon),str(CU.UAV)}:facts+=learning.current_graph(store,settings.ontology_dir)
                        if uri==str(CU.RadarSensor):facts+=evidence.read_graph(store)
                        result=learning.term_view(model,facts,uri)
                        result['scope']='模拟设备显式台账与有界最新状态；部署关系不是按距离推断。'
                        return result
                    if uri in evidence.TERMS:
                        facts=store.construct(f'CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{evidence.EVIDENCE_GRAPH}> {{ ?s ?p ?o }} }}')
                        result=learning.term_view(model,facts,uri)
                        result['scope']='有界多源证据图；包含来源声明、模拟观测及未确认判断，不表示已验证的无人机目标。'
                        return result
                    if uri in agent.ANALYSIS_TERMS:
                        from .domain import SCHEMA
                        facts = store.construct(f'CONSTRUCT {{ ?s ?p ?o }} WHERE {{ VALUES ?g {{ <{SCHEMA}> <{agent.ANALYSIS_GRAPH}> }} GRAPH ?g {{ ?s ?p ?o }} }}')
                        result = learning.term_view(model, facts, uri)
                        result['scope'] = '最近一次固定分析快照及业务排序策略，不是全部历史；先打开智能态势问答可生成分析实例。'
                        return result
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
        @app.get('/back', include_in_schema=False)
        @app.get('/back/', include_in_schema=False)
        def learning_page():
            return FileResponse(static_dir/'index.html')

        app.mount('/',StaticFiles(directory=static_dir,html=True),name='frontend')
    return app


app=create_app()
