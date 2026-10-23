"""Separate sensor reports from uncertain judgements. No fusion/identification algorithm."""
import json
from datetime import datetime, timezone
from typing import Literal as Choice
from urllib.parse import quote
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from rdflib import Graph, Literal, RDF, RDFS, XSD, Namespace
from .domain import CU, graph
from .models import ID_PATTERN

EVIDENCE_GRAPH = 'urn:airontology:evidence'
EV = Namespace('urn:airontology:evidence:')
CLASSES = {'devices':CU.SensorDevice, 'observations':CU.SensorObservation,
           'judgements':CU.EvidenceJudgement, 'regions':CU.EvidenceRegion,
           'authorizations':CU.AuthorizationRecord}
LIMITS = {'devices':30, 'observations':200, 'judgements':100, 'regions':20, 'authorizations':100}
STATUS = {'suspected':'疑似', 'pending':'待核实', 'insufficient':'证据不足', 'conflict':'证据冲突'}
LAYERS = {'association':'观测关联', 'identification':'无人机识别', 'intrusion':'异常闯入条件'}
MODE = {'simulated':'模拟数据', 'unverified':'来源待核实', 'operational':'业务接入声明（未独立验证）'}


def now():
    return datetime.now(timezone.utc)


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = Field(pattern=ID_PATTERN)
    data_mode: Choice['simulated','unverified','operational'] = 'unverified'

    @field_validator('*')
    @classmethod
    def aware_dates(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError('时间必须包含时区')
            return value.astimezone(timezone.utc)
        return value


class Device(EvidenceInput):
    name: str = Field(min_length=1, max_length=80)
    sensor_kind: Choice['radar','radio','camera','infrared']
    reported_status: Choice['normal','fault','unknown'] = 'unknown'
    coverage: Choice['unknown','insufficient','reported_available'] = 'unknown'
    reported_at: datetime
    valid_for_seconds: int = Field(default=60, ge=2, le=3600)
    source: str = Field(min_length=1, max_length=120)

    @model_validator(mode='after')
    def clock(self):
        if (self.reported_at-now()).total_seconds()>30:
            raise ValueError('设备状态时间不能超前当前时间30秒')
        return self


class SensorObservation(EvidenceInput):
    device_id: str = Field(pattern=ID_PATTERN)
    observed_at: datetime
    valid_for_seconds: int = Field(default=60, ge=2, le=3600)
    outcome: Choice['detected','not_detected','unknown']
    crs: Choice['WGS84','unknown'] = 'unknown'
    lon: float | None = Field(default=None, ge=-180, le=180)
    lat: float | None = Field(default=None, ge=-90, le=90)
    horizontal_error_m: float | None = Field(default=None, ge=0, le=100000)
    quality: Choice['usable','invalid','unknown'] = 'unknown'
    features: str = Field(default='', max_length=500)
    raw_evidence_ref: str = Field(min_length=1, max_length=500)
    reported_target_ref: str | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def coordinates(self):
        if (self.lon is None) != (self.lat is None):
            raise ValueError('经度与纬度必须同时提供')
        if self.lon is not None and self.crs != 'WGS84':
            raise ValueError('本版本仅接收明确为 WGS84 的经纬度；未知坐标系请不填经纬度')
        if (self.observed_at - now()).total_seconds() > 30:
            raise ValueError('观测时间不能超前当前时间30秒')
        return self


class Region(EvidenceInput):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    geometry_ref: str = Field(min_length=1, max_length=500)
    # Store a geometry reference, do not pretend to have validated containment.


class Authorization(EvidenceInput):
    target_ref: str = Field(pattern=ID_PATTERN)
    region_id: str = Field(pattern=ID_PATTERN)
    status: Choice['authorized','unauthorized','unknown'] = 'unknown'
    valid_from: datetime
    valid_until: datetime
    authority: str = Field(min_length=1, max_length=120)
    evidence_ref: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def period(self):
        if self.valid_until <= self.valid_from:
            raise ValueError('授权有效期结束时间必须晚于开始时间')
        return self


class Judgement(EvidenceInput):
    layer: Choice['association','identification','intrusion']
    status: Choice['suspected','pending','insufficient','conflict']
    target_ref: str = Field(pattern=ID_PATTERN)
    observation_ids: list[str] = Field(default_factory=list, max_length=20)
    judgement_ids: list[str] = Field(default_factory=list, max_length=10)
    conditions: str = Field(min_length=1, max_length=1000)
    uncertainty: str = Field(min_length=1, max_length=1000)
    method_name: str = Field(min_length=1, max_length=120)
    method_version: str = Field(min_length=1, max_length=80)
    source: Choice['operator','external_algorithm']
    validation_ref: str | None = Field(default=None, max_length=500)
    independence_note: str = Field(min_length=1, max_length=500)
    score: float | None = Field(default=None, ge=-1e12, le=1e12)
    score_meaning: str | None = Field(default=None, max_length=500)
    generated_at: datetime
    region_id: str | None = Field(default=None, pattern=ID_PATTERN)
    authorization_id: str | None = Field(default=None, pattern=ID_PATTERN)

    @model_validator(mode='after')
    def evidence_rules(self):
        import re
        if any(not re.fullmatch(ID_PATTERN, key) for key in self.observation_ids+self.judgement_ids):
            raise ValueError('证据编号格式不正确')
        if len(set(self.observation_ids)) != len(self.observation_ids) or len(set(self.judgement_ids)) != len(self.judgement_ids):
            raise ValueError('同一输入证据不能重复计数')
        if self.score is not None and not self.score_meaning:
            raise ValueError('算法分数必须说明含义；本版本不将分数解释为概率')
        if not self.observation_ids and self.status != 'insufficient':
            raise ValueError('没有观测输入时只能登记为证据不足')
        if self.layer == 'intrusion' and not self.region_id:
            raise ValueError('闯入层判断必须指定区域；区域几何关系仍需独立算法或规则验证')
        if (self.generated_at - now()).total_seconds() > 30:
            raise ValueError('判断生成时间不能超前当前时间30秒')
        return self


MODELS = {'devices':Device,'observations':SensorObservation,'judgements':Judgement,
          'regions':Region,'authorizations':Authorization}


def uri(kind, identifier):
    return EV[kind + ':' + quote(identifier, safe='')]


def read_graph(store):
    return store.construct(f'CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{EVIDENCE_GRAPH}> {{ ?s ?p ?o }} }}')


def records(g, kind):
    values = []
    for subject in g.subjects(RDF.type, CLASSES[kind]):
        raw = g.value(subject, CU.recordJson)
        if raw is not None:
            item = json.loads(str(raw))
            item['uri'] = str(subject)
            item['received_at'] = str(g.value(subject, CU.receivedAt) or '')
            values.append(item)
    return sorted(values, key=lambda v:(v['received_at'],v['id']), reverse=True)


class EvidenceConflict(ValueError):
    pass


def save(store, kind, record):
    with store.lock:
        g = read_graph(store)
        subject = uri(kind, record.id)
        canonical = json.dumps(record.model_dump(mode='json'),sort_keys=True,ensure_ascii=False,separators=(',',':'))
        previous = g.value(subject, CU.recordJson)
        if previous is not None:
            if str(previous) == canonical:
                return {'id':record.id, 'uri':str(subject), 'status':'unchanged'}
            if kind != 'devices':
                raise EvidenceConflict('原始观测与判断记录不可覆盖；相同编号内容不同，请使用新编号并保留原记录')
            old = Device.model_validate_json(str(previous))
            if record.reported_at <= old.reported_at:
                raise EvidenceConflict('设备旧状态不能覆盖较新的状态')
        elif len(list(g.subjects(RDF.type, CLASSES[kind]))) >= LIMITS[kind]:
            raise EvidenceConflict('已达到本学习环境的记录上限，未删除任何仍用于追溯的证据')
        if kind == 'observations':
            if (uri('devices',record.device_id),RDF.type,CU.SensorDevice) not in g:
                raise ValueError('来源设备尚未登记；请先登记设备，不能凭观测虚构设备状态')
        if kind == 'authorizations' and (uri('regions',record.region_id),RDF.type,CU.EvidenceRegion) not in g:
            raise ValueError('授权所关联的区域尚未登记')
        if kind == 'judgements':
            for input_kind, ids in [('observations',record.observation_ids),('judgements',record.judgement_ids)]:
                for key in ids:
                    if (uri(input_kind,key),RDF.type,CLASSES[input_kind]) not in g:
                        raise ValueError('引用的输入证据不存在：'+key)
            if record.region_id and (uri('regions',record.region_id),RDF.type,CU.EvidenceRegion) not in g:
                raise ValueError('关联区域尚未登记')
            if record.authorization_id:
                auth = next((a for a in records(g,'authorizations') if a['id']==record.authorization_id), None)
                if not auth or auth['target_ref'] != record.target_ref or auth['region_id'] != record.region_id:
                    raise ValueError('授权记录必须与本判断的疑似目标和区域匹配')
            for key in record.judgement_ids:
                other = json.loads(str(g.value(uri('judgements',key),CU.recordJson)))
                if other['target_ref'] != record.target_ref:
                    raise ValueError('不能把其他疑似目标的判断作为本目标已成立的前提')
        out = graph()
        out.add((subject,RDF.type,CLASSES[kind]))
        out.add((subject,CU.recordJson,Literal(canonical,datatype=XSD.string)))
        out.add((subject,CU.receivedAt,Literal(now(),datatype=XSD.dateTime)))
        out.add((subject,CU.dataMode,Literal(record.data_mode,datatype=XSD.string)))
        def add(key,value,datatype=None):
            if value is not None:
                out.add((subject,CU[key],Literal(value,datatype=datatype)))
        if hasattr(record,'valid_for_seconds'): add('validForSeconds',record.valid_for_seconds,XSD.integer)
        if kind == 'devices':
            subclasses={'radar':CU.RadarSensor,'radio':CU.RadioSensor,'camera':CU.CameraSensor,'infrared':CU.InfraredSensor}
            out.add((subject,RDF.type,subclasses[record.sensor_kind]))
            add('name',record.name,XSD.string); add('sensorKind',record.sensor_kind,XSD.string)
            add('reportedDeviceStatus',record.reported_status,XSD.string)
            add('reportedCoverage',record.coverage,XSD.string); add('reportedAt',record.reported_at,XSD.dateTime)
            add('evidenceSource',record.source,XSD.string)
        elif kind == 'observations':
            out.add((subject,CU.fromDevice,uri('devices',record.device_id)))
            add('observedAt',record.observed_at,XSD.dateTime); add('coordinateSystem',record.crs,XSD.string)
            add('lon',record.lon,XSD.double); add('lat',record.lat,XSD.double)
            add('horizontalErrorMeters',record.horizontal_error_m,XSD.double)
            add('detectionOutcome',record.outcome,XSD.string); add('inputQuality',record.quality,XSD.string)
            add('observedFeatures',record.features,XSD.string); add('rawEvidenceRef',record.raw_evidence_ref,XSD.string)
            add('reportedTargetRef',record.reported_target_ref,XSD.string)
            add('deviceStateAtReceipt',str(g.value(uri('devices',record.device_id),CU.recordJson)),XSD.string)
        elif kind == 'regions':
            add('name',record.name,XSD.string); add('regionDescription',record.description,XSD.string)
            add('geometryRef',record.geometry_ref,XSD.string)
        elif kind == 'authorizations':
            out.add((subject,CU.authorizationRegion,uri('regions',record.region_id)))
            add('subjectReference',record.target_ref,XSD.string); add('authorizationStatus',record.status,XSD.string)
            add('validFrom',record.valid_from,XSD.dateTime); add('validUntil',record.valid_until,XSD.dateTime)
            add('authoritySource',record.authority,XSD.string); add('rawEvidenceRef',record.evidence_ref,XSD.string)
        elif kind == 'judgements':
            subclasses={'association':CU.AssociationJudgement,'identification':CU.IdentificationJudgement,'intrusion':CU.IntrusionConditionJudgement}
            out.add((subject,RDF.type,subclasses[record.layer]))
            hypothesis = uri('hypotheses',record.target_ref)
            out.add((hypothesis,RDF.type,CU.SuspectedTarget))
            out.add((subject,CU.judgesHypothesis,hypothesis))
            for key in record.observation_ids:
                out.add((subject,CU.inputObservation,uri('observations',key)))
            for key in record.judgement_ids:
                out.add((subject,CU.inputJudgement,uri('judgements',key)))
            if record.region_id: out.add((subject,CU.concernsRegion,uri('regions',record.region_id)))
            if record.authorization_id: out.add((subject,CU.usesAuthorization,uri('authorizations',record.authorization_id)))
            for key,value in [('judgementLayer',record.layer),('reportedJudgementStatus',record.status),
                ('applicableConditions',record.conditions),('uncertaintyNote',record.uncertainty),
                ('methodName',record.method_name),('methodVersion',record.method_version),
                ('evidenceSource',record.source),('validationRef',record.validation_ref),
                ('independenceNote',record.independence_note),('scoreMeaning',record.score_meaning)]:
                add(key,value,XSD.string)
            add('algorithmScore',record.score,XSD.double); add('generatedAt',record.generated_at,XSD.dateTime)
        if previous is not None:
            store.update(f'DELETE WHERE {{ GRAPH <{EVIDENCE_GRAPH}> {{ {subject.n3()} ?p ?o }} }}; INSERT DATA {{ GRAPH <{EVIDENCE_GRAPH}> {{ {out.serialize(format="nt")} }} }}')
        else:
            store.update(f'INSERT DATA {{ GRAPH <{EVIDENCE_GRAPH}> {{ {out.serialize(format="nt")} }} }}')
        return {'id':record.id,'uri':str(subject),'status':'saved'}


def view(store):
    with store.lock:
        g = read_graph(store)
    result = {kind:records(g,kind) for kind in CLASSES}
    reference = now()
    def fresh(stamp, seconds):
        age = (reference-datetime.fromisoformat(stamp.replace('Z','+00:00'))).total_seconds()
        return -2 <= age <= seconds
    for device in result['devices']:
        device['status_fresh'] = fresh(device['reported_at'],device['valid_for_seconds'])
        device['effective_status'] = device['reported_status'] if device['status_fresh'] else 'unknown'
        device['effective_coverage'] = device['coverage'] if device['status_fresh'] else 'unknown'
    devices = {d['id']:d for d in result['devices']}
    for obs in result['observations']:
        obs['fresh'] = fresh(obs['observed_at'],obs['valid_for_seconds'])
        obs['device_name'] = devices[obs['device_id']]['name']
        obs['device_state_at_receipt'] = json.loads(str(g.value(uri('observations',obs['id']),CU.deviceStateAtReceipt) or '{}'))
        # Positive evidence is still an observation, not drone identification.
        obs['mode_consistent'] = obs['data_mode']==devices[obs['device_id']]['data_mode']
        obs['usable_positive'] = obs['fresh'] and obs['outcome']=='detected' and obs['quality']=='usable' and devices[obs['device_id']]['effective_status']=='normal' and obs['mode_consistent']
    for device in result['devices']:
        recent = sorted([o for o in result['observations'] if o['device_id']==device['id']],key=lambda o:o['observed_at'],reverse=True)
        device['observation_note'] = ('设备状态未知或已过期' if device['effective_status']=='unknown' else
            '设备报告异常，不能据此断言区域内没有目标' if device['effective_status']=='fault' else
            '覆盖不足，不能据此断言区域内没有目标' if device['effective_coverage']=='insufficient' else
            '正常状态下未检出；未检出不等于目标不存在' if recent and recent[0]['fresh'] and recent[0]['outcome']=='not_detected' else
            '没有近期有效观测' if not recent or not recent[0]['fresh'] else '已有观测；关联与身份仍需独立验证')
    observations = {o['id']:o for o in result['observations']}
    authorizations = {a['id']:a for a in result['authorizations']}
    for auth in authorizations.values():
        start,end = (datetime.fromisoformat(auth[k].replace('Z','+00:00')) for k in ('valid_from','valid_until'))
        auth['effective_status'] = auth['status'] if start <= reference <= end else 'unknown'
    for judgement in result['judgements']:
        inputs = [observations[key] for key in judgement['observation_ids']]
        gaps = ['关联、识别和闯入条件是不同判断；当前未实现或验证融合/识别算法']
        effective = judgement['status']
        if not any(o['usable_positive'] for o in inputs):
            effective = 'insufficient'
            gaps.append('没有当前可用的正向观测；未检出、过期或设备状态未知都不能证明目标不存在')
        modes = {o['data_mode'] for o in inputs} | {judgement['data_mode']}
        for linked_kind,key in [('regions',judgement['region_id']),('authorizations',judgement['authorization_id'])]:
            modes.update(r['data_mode'] for r in result[linked_kind] if r['id']==key)
        modes.update(r['data_mode'] for r in result['judgements'] if r['id'] in judgement['judgement_ids'])
        if len(modes)>1:
            effective = 'conflict' if any(o['usable_positive'] for o in inputs) else 'insufficient'
            gaps.append('混合了不同数据声明类型，不能把模拟证据当作业务事实')
        if judgement['layer']=='association' and len(inputs)<2:
            effective = 'insufficient'; gaps.append('关联判断至少需要两条不同观测；数量本身也不能证明关联成立')
        if judgement['layer']=='intrusion':
            auth = authorizations.get(judgement['authorization_id'])
            auth_status = auth['effective_status'] if auth else 'unknown'
            judgement['authorization_status'] = auth_status
            if auth_status=='unknown':
                if effective not in ('insufficient','conflict'): effective='pending'
                gaps.append('授权待核实，不能据此判为未授权')
            elif auth_status=='authorized':
                if effective!='insufficient': effective='conflict'
                gaps.append('当前登记声明为有授权；不得将其解释为已确认未授权闯入')
            gaps.append('区域几何包含、目标身份及异常条件尚未独立验证')
        if judgement['source']=='external_algorithm' and not judgement['validation_ref']:
            gaps.append('算法验证依据尚未提供；分数不是概率')
        judgement['current_status'] = effective
        judgement['current_label'] = STATUS[effective]
        judgement['layer_label'] = LAYERS[judgement['layer']]
        judgement['gaps'] = gaps
        judgement['validation_state'] = 'not_independently_verified'
    result.update({'at':reference.isoformat(),'limits':LIMITS,'modes':MODE,
        'note':'仅登记来源观测与未确认的判断，未实现多传感器融合、无人机识别或黑飞定性算法。没有有效观测只能报告信息不足。'})
    return result


def seed_demo(store):
    stamp = now()
    suffix = uuid4().hex[:12]
    devices=[]; observations=[]; judgements=[]
    for kind,name in [('radar','雷达'),('radio','无线电'),('camera','摄像头'),('infrared','红外')]:
        devices.append(Device(id='demo-'+kind,name='模拟'+name,sensor_kind=kind,reported_status='normal',
            coverage='unknown',reported_at=stamp,source='手工演示数据',data_mode='simulated'))
    for i,device in enumerate(devices):
        observations.append(SensorObservation(id=f'demo-obs-{suffix}-{i}',device_id=device.id,
            observed_at=stamp,outcome='not_detected' if i==3 else 'detected',crs='WGS84',
            lon=116.408+i*.0002,lat=39.9045,horizontal_error_m=30,quality='usable',
            features='模拟观测，不代表真实设备能力',raw_evidence_ref=f'urn:demo:{suffix}:{i}',data_mode='simulated'))
    region=Region(id='demo-region-'+suffix,name='模拟区域',description='仅登记区域引用，未计算包含关系',geometry_ref='urn:demo:geometry',data_mode='simulated')
    for layer,status in [('association','suspected'),('identification','insufficient'),('intrusion','pending')]:
        judgements.append(Judgement(id=f'demo-judgement-{suffix}-{layer}',layer=layer,status=status,
            target_ref='demo-hypothesis-'+suffix,observation_ids=[o.id for o in observations[:2]],
            conditions='仅用手工模拟记录展示三层判断；没有执行传感器关联或识别算法',
            uncertainty='不能认定同一目标、无人机身份或未授权闯入',method_name='手工演示占位记录',
            method_version='demo-v1',source='operator',independence_note='来源相关性未知，不按数量叠加可信度',
            generated_at=stamp,region_id=region.id if layer=='intrusion' else None,data_mode='simulated'))
    with store.lock:
        existing = read_graph(store)
        # Preflight quotas before any example record is written.
        for kind, count in [('observations',4),('judgements',3),('regions',1)]:
            if len(list(existing.subjects(RDF.type,CLASSES[kind])))+count > LIMITS[kind]:
                raise EvidenceConflict('模拟数据会超过保留上限，未导入')
        new_devices = sum((uri('devices',d.id),RDF.type,CU.SensorDevice) not in existing for d in devices)
        if len(list(existing.subjects(RDF.type,CU.SensorDevice)))+new_devices>LIMITS['devices']:
            raise EvidenceConflict('设备登记已达到上限，未导入模拟数据')
        for record in devices: save(store,'devices',record)
        save(store,'regions',region)
        for record in observations: save(store,'observations',record)
        for record in judgements: save(store,'judgements',record)
    return {'status':'saved','data_mode':'simulated','observations':4,'judgements':3}

# Terms whose examples come from the separate evidence named graph.
TERMS = {str(CU[name]) for name in ('SensorDevice', 'RadarSensor', 'RadioSensor', 'CameraSensor', 'InfraredSensor', 'SensorObservation', 'SuspectedTarget', 'EvidenceJudgement', 'AssociationJudgement', 'IdentificationJudgement', 'IntrusionConditionJudgement', 'EvidenceRegion', 'AuthorizationRecord', 'fromDevice', 'inputObservation', 'inputJudgement', 'judgesHypothesis', 'concernsRegion', 'usesAuthorization', 'authorizationRegion', 'dataMode', 'recordJson', 'receivedAt', 'sensorKind', 'reportedDeviceStatus', 'reportedCoverage', 'reportedAt', 'evidenceSource', 'observedAt', 'coordinateSystem', 'horizontalErrorMeters', 'detectionOutcome', 'inputQuality', 'observedFeatures', 'rawEvidenceRef', 'reportedTargetRef', 'regionDescription', 'geometryRef', 'subjectReference', 'authorizationStatus', 'validFrom', 'validUntil', 'authoritySource', 'judgementLayer', 'reportedJudgementStatus', 'applicableConditions', 'uncertaintyNote', 'methodName', 'methodVersion', 'validationRef', 'independenceNote', 'algorithmScore', 'scoreMeaning', 'generatedAt')}


def examples():
    """Editable examples, never automatically ingested."""
    stamp=now()
    from datetime import timedelta
    common={'data_mode':'simulated'}
    return {
        'devices':Device(id='sample-radar',name='模拟雷达',sensor_kind='radar',reported_at=stamp,source='手工示例',reported_status='normal',**common).model_dump(mode='json'),
        'observations':SensorObservation(id='sample-observation',device_id='sample-radar',observed_at=stamp,outcome='detected',crs='WGS84',lon=116.408,lat=39.9045,horizontal_error_m=30,quality='usable',raw_evidence_ref='urn:demo:raw-reference',**common).model_dump(mode='json'),
        'regions':Region(id='sample-region',name='模拟区域',description='仅登记引用，未计算空间包含',geometry_ref='urn:demo:geometry',**common).model_dump(mode='json'),
        'authorizations':Authorization(id='sample-auth',target_ref='sample-hypothesis',region_id='sample-region',status='unknown',valid_from=stamp,valid_until=stamp+timedelta(hours=1),authority='待核实登记',evidence_ref='urn:demo:auth-reference',**common).model_dump(mode='json'),
        'judgements':Judgement(id='sample-judgement',layer='identification',status='insufficient',target_ref='sample-hypothesis',observation_ids=['sample-observation'],conditions='尚未选择或验证识别算法',uncertainty='单条检测不能证明是无人机',method_name='人工登记',method_version='v1',source='operator',independence_note='独立性未知，数量不等于可信度',generated_at=stamp,**common).model_dump(mode='json')}

TERMS.update({str(CU.deviceStateAtReceipt),str(CU.validForSeconds)})
