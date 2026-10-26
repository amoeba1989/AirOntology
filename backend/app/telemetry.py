"""Bounded simulation telemetry adapter. Four business types; no detection/causal rules."""
import json
from datetime import datetime, timezone
from typing import Literal as Choice
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from rdflib import Graph, Literal, RDF, RDFS, XSD, Namespace
from .domain import CU, Track, graph
from .models import ID_PATTERN, valid_identifier

DEVICE_GRAPH='urn:airontology:devices'
NS=Namespace('urn:airontology:telemetry:')
REGISTRY=NS.registry
FRAME=NS.latestFrame
KINDS={'uav':CU.UAV,'radar':CU.RadarSensor,'jammer':CU.Jammer}
LABELS={'uav':'无人机','radar':'雷达','jammer':'干扰器'}
BLOCKS={'transform':1,'motion':2,'flight':4,'faction':8,'rf_link':16,'health':32,'jammer':64}


def utcnow(): return datetime.now(timezone.utc)
def canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


class Input(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

    @field_validator('*')
    @classmethod
    def timezone_required(cls,value):
        if isinstance(value,datetime):
            if value.tzinfo is None: raise ValueError('发布时间必须包含时区')
            if (value-utcnow()).total_seconds()>30: raise ValueError('发布时间超前30秒')
            return value.astimezone(timezone.utc)
        return value


class Registration(Input):
    handle:int=Field(ge=0)
    id:str=Field(pattern=ID_PATTERN)
    name:str=Field(min_length=1,max_length=80)
    kind:Choice['uav','radar','jammer']
    platform:Choice['quadrotor']|None=None
    deployed_at:str|None=Field(default=None,pattern=ID_PATTERN)
    parameters:dict=Field(default_factory=dict)

    @field_validator('id')
    @classmethod
    def identifier(cls,value):return valid_identifier(value)

    @model_validator(mode='after')
    def constraints(self):
        if self.platform and self.kind!='uav':raise ValueError('平台子类型仅适用于无人机')
        if len(canonical(self.parameters).encode())>8192:raise ValueError('单设备配置超过8KB')
        return self


class Registry(Input):
    type:Choice['device_registry']='device_registry'
    run_id:str=Field(pattern=ID_PATTERN)
    published_at:datetime
    data_mode:Choice['simulated']='simulated'
    source:str=Field(min_length=1,max_length=120)
    devices:list[Registration]=Field(min_length=1,max_length=104)

    @model_validator(mode='after')
    def unique(self):
        if len({d.handle for d in self.devices})!=len(self.devices) or len({d.id for d in self.devices})!=len(self.devices):
            raise ValueError('实体句柄或业务编号重复')
        return self


class Transform(Input):
    latitude_deg:float=Field(ge=-90,le=90)
    longitude_deg:float=Field(ge=-180,le=180)
    altitude_m:float|None=None
    yaw_deg:float|None=None
    pitch_deg:float|None=None
    roll_deg:float|None=None


class Motion(Input):
    speed_mps:float=Field(ge=0)
    mode:int=Field(ge=0,le=6)


class Flight(Input):
    airspeed_mps:float=Field(ge=0)


class Faction(Input):
    side:int=Field(ge=0,le=2)


class RFLink(Input):
    gnss_locked:bool|None=None
    rc_linked:bool|None=None
    telemetry_linked:bool|None=None
    gnss_sir_db:float|None=None
    rc_sir_db:float|None=None


class Health(Input):
    hp:float|None=None
    max_hp:float|None=None
    destroyed:bool|None=None


class Jammer(Input):
    enabled:bool
    emitting:bool
    style:int=Field(ge=0,le=2)
    eirp_dbm:float|None=None
    freq_hz:float|None=Field(default=None,ge=0)
    bandwidth_hz:float|None=Field(default=None,ge=0)
    boresight_yaw_deg:float|None=None
    boresight_pitch_deg:float|None=None
    half_angle_deg:float|None=None
    sidelobe_gain_dbi:float|None=None


class Entity(Input):
    id:int=Field(ge=0)
    name:str=Field(max_length=80)
    blocks:int=Field(ge=0,le=127)
    transform:Transform|None=None
    motion:Motion|None=None
    flight:Flight|None=None
    faction:Faction|None=None
    rf_link:RFLink|None=None
    health:Health|None=None
    jammer:Jammer|None=None

    @model_validator(mode='after')
    def mask(self):
        for key,bit in BLOCKS.items():
            if bool(self.blocks&bit)!=(getattr(self,key) is not None):
                raise ValueError('块位与内容不一致：'+key)
        return self


class Payload(Input):
    type:Choice['telemetry']='telemetry'
    tick:int=Field(ge=0)
    client:str=Field(max_length=100)
    sim_time_s:float=Field(ge=0)
    scenario_id:int=Field(ge=0)
    scenario_name:str=Field(max_length=80)
    entity_count:int=Field(ge=0)
    reported_count:int=Field(ge=0,le=104)
    step_ms:float=Field(ge=0)
    entities:list[Entity]=Field(max_length=104)

    @model_validator(mode='after')
    def counts(self):
        if self.reported_count!=len(self.entities) or self.reported_count>self.entity_count:
            raise ValueError('实体数量与报文内容不一致')
        if len({e.id for e in self.entities})!=len(self.entities):raise ValueError('帧内实体句柄重复')
        return self


class Frame(Input):
    # Added transport envelope; payload preserves the uploaded telemetry format.
    type:Choice['telemetry_frame']='telemetry_frame'
    run_id:str=Field(pattern=ID_PATTERN)
    published_at:datetime
    data_mode:Choice['simulated']='simulated'
    payload:Payload


def read_graph(store):
    return store.construct(f'CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{DEVICE_GRAPH}> {{ ?s ?p ?o }} }}')


def read_json(g,subject):
    raw=g.value(subject,CU.recordJson)
    return json.loads(str(raw)) if raw is not None else None


def add(g,subject,key,value,datatype=XSD.string):
    if value is not None:g.add((subject,CU[key],Literal(value,datatype=datatype)))


def register(store,record):
    with store.lock:
        g=read_graph(store);old=read_json(g,REGISTRY);value=record.model_dump(mode='json')
        if old:
            if old==value:return {'status':'unchanged'}
            if old['run_id']==record.run_id:raise ValueError('同一模拟运行的登记不可改写，请使用新的运行编号')
            if datetime.fromisoformat(old['published_at'].replace('Z','+00:00'))>=record.published_at:
                return {'status':'ignored_old_registry'}
        positions={p.id for p in store.config.positions}
        for device in record.devices:
            if device.id in positions:raise ValueError('设备编号与阵地冲突')
            if device.deployed_at and device.deployed_at not in positions:raise ValueError('部署关系引用了不存在的阵地：'+device.deployed_at)
        out=graph();add(out,REGISTRY,'recordJson',canonical(value));add(out,REGISTRY,'receivedAt',utcnow(),XSD.dateTime)
        for d in record.devices:
            s=CU[d.id];out.add((s,RDF.type,KINDS[d.kind]));out.add((s,RDFS.label,Literal(d.name,lang='zh')))
            if d.kind=='uav':out.add((s,RDF.type,CU.BlueDevice))  # legacy code compatibility, not faction
            if d.platform=='quadrotor':out.add((s,RDF.type,CU.QuadrotorUAV))
            if d.kind=='radar':
                out.add((s,RDF.type,CU.SensorDevice))
                add(out,s,'sensorKind','radar');add(out,s,'reportedDeviceStatus','unknown')
                add(out,s,'reportedAt',record.published_at,XSD.dateTime);add(out,s,'receivedAt',utcnow(),XSD.dateTime)
            add(out,s,'name',d.name);add(out,s,'deviceKind',d.kind);add(out,s,'dataMode','simulated')
            add(out,s,'sourceHandle',d.handle,XSD.integer);add(out,s,'sourceRunId',record.run_id)
            add(out,s,'configurationJson',canonical(d.parameters));add(out,s,'configurationSource',record.source)
            if d.deployed_at:out.add((s,CU.deployedAt,CU[d.deployed_at]))
        # This graph is only the simulator's bounded current registry/state, not raw evidence history.
        store.update(f'CLEAR SILENT GRAPH <{DEVICE_GRAPH}>; INSERT DATA {{ GRAPH <{DEVICE_GRAPH}> {{ {out.serialize(format="nt")} }} }}')
        return {'status':'registered','count':len(record.devices)}


FIELD_MAP={
    'transform':{'latitude_deg':'lat','longitude_deg':'lon','altitude_m':'altitudeMeters','yaw_deg':'yawDegrees','pitch_deg':'pitchDegrees','roll_deg':'rollDegrees'},
    'motion':{'speed_mps':'groundSpeed','mode':'motionMode'},
    'flight':{'airspeed_mps':'airSpeed'},
    'faction':{'side':'factionCode'},
    'rf_link':{'gnss_locked':'gnssLocked','rc_linked':'rcLinked','telemetry_linked':'telemetryLinked','gnss_sir_db':'gnssRatioDb','rc_sir_db':'rcRatioDb'},
    'health':{'hp':'hitPoints','max_hp':'maxHitPoints','destroyed':'reportedDestroyed'},
    'jammer':{'enabled':'emitterEnabled','emitting':'emitterEmitting','style':'emissionStyle','eirp_dbm':'reportedEirpDbm','freq_hz':'emissionFrequencyHz','bandwidth_hz':'emissionBandwidthHz','boresight_yaw_deg':'boresightYaw','boresight_pitch_deg':'boresightPitch','half_angle_deg':'beamHalfAngle','sidelobe_gain_dbi':'sidelobeGain'},
}
BOOL_FIELDS={'gnssLocked','rcLinked','telemetryLinked','reportedDestroyed','emitterEnabled','emitterEmitting'}
INT_FIELDS={'motionMode','factionCode','emissionStyle'}


def ingest(store,frame):
    with store.lock:
        g=read_graph(store);registry=read_json(g,REGISTRY)
        if not registry or registry['run_id']!=frame.run_id:raise ValueError('未登记本次模拟运行，先发送设备登记消息')
        old=read_json(g,FRAME);value=frame.model_dump(mode='json');p=frame.payload
        if old:
            if old==value:return {'status':'unchanged'}
            if p.tick<old['payload']['tick']:return {'status':'ignored_old_frame'}
            if p.tick==old['payload']['tick']:raise ValueError('同一帧号内容冲突')
            if p.scenario_id!=old['payload']['scenario_id']:raise ValueError('切换想定须使用新运行编号和登记')
            if p.sim_time_s<old['payload']['sim_time_s'] or frame.published_at<=datetime.fromisoformat(old['published_at'].replace('Z','+00:00')):
                raise ValueError('仿真时间或发布时间倒退')
        configured={d['handle']:d for d in registry['devices']}
        # Validate all references before projecting any target into legacy distance evaluation.
        tracks=[]
        for item in p.entities:
            if item.id not in configured:raise ValueError('未登记的实体句柄：'+str(item.id))
            if item.jammer and configured[item.id]['kind']!='jammer':raise ValueError('发射状态与登记设备类型不符')
        out=graph();received=utcnow();add(out,FRAME,'recordJson',canonical(value));add(out,FRAME,'receivedAt',received,XSD.dateTime)
        deletes=[f'{FRAME.n3()} ?p ?o']
        for item in p.entities:
            d=configured[item.id];s=NS['state-'+d['id']];entity=CU[d['id']]
            out.add((s,RDF.type,CU.DeviceState));out.add((s,CU.stateOfDevice,entity));out.add((entity,CU.latestDeviceState,s))
            add(out,s,'recordJson',canonical(item.model_dump(mode='json',exclude_none=True)))
            add(out,s,'receivedAt',received,XSD.dateTime);add(out,s,'publishedAt',frame.published_at,XSD.dateTime)
            add(out,s,'sourceRunId',frame.run_id);add(out,s,'sourceTick',p.tick,XSD.integer)
            add(out,s,'simulationTimeSeconds',p.sim_time_s,XSD.double);add(out,s,'dataMode','simulated')
            add(out,s,'presentBlockMask',item.blocks,XSD.integer)
            for block,mapping in FIELD_MAP.items():
                obj=getattr(item,block)
                if obj is not None:
                    for field,prop in mapping.items():
                        v=getattr(obj,field)
                        datatype=XSD.boolean if prop in BOOL_FIELDS else XSD.integer if prop in INT_FIELDS else XSD.double
                        add(out,s,prop,v,datatype)
            deletes.append(f'{s.n3()} ?p ?o')
            if d['kind']=='uav' and item.transform and item.motion:
                # published_at is explicit UTC added by this wall-clock demo publisher, NOT sim_time_s.
                tracks.append(Track(target_id=d['id'],name=d['name'],lon=item.transform.longitude_deg,
                    lat=item.transform.latitude_deg,speed=item.motion.speed_mps,timestamp=frame.published_at,
                    source=f'模拟态势适配 run={frame.run_id[:12]} tick={p.tick}',data_mode='simulated'))
        store.write_tracks(tracks)
        update='; '.join(f'DELETE WHERE {{ GRAPH <{DEVICE_GRAPH}> {{ {pattern} }} }}' for pattern in deletes)
        store.update(update+f'; INSERT DATA {{ GRAPH <{DEVICE_GRAPH}> {{ {out.serialize(format="nt")} }} }}')
        return {'status':'saved','reported_count':p.reported_count,'tick':p.tick}


def view(store):
    # The device graph is replaced in one Fuseki update after track writes. A
    # concurrent read can see the previous complete frame without waiting for
    # the simulation worker's full frame processing under store.lock.
    g=read_graph(store);registry=read_json(g,REGISTRY);frame=read_json(g,FRAME)
    positions={p.id:p.model_dump() for p in store.config.positions}
    devices=[];now=utcnow();present={e['id'] for e in frame['payload']['entities']} if frame else set()
    for d in (registry or {}).get('devices',[]):
        s=NS['state-'+d['id']];raw=read_json(g,s);published=str(g.value(s,CU.publishedAt) or '')
        age=(now-datetime.fromisoformat(published.replace('Z','+00:00'))).total_seconds() if published else None
        current=d['handle'] in present
        item=d|{'uri':str(CU[d['id']]),'kind_label':LABELS[d['kind']],'data_mode':'simulated','state':raw,
            'published_at':published,'received_at':str(g.value(s,CU.receivedAt) or ''),'state_tick':str(g.value(s,CU.sourceTick)) if g.value(s,CU.sourceTick) is not None else '',
            'in_latest_frame':current,'stale':age is None or age>store.config.stale_seconds or age< -2,
            'position':positions.get(d['deployed_at']),'configuration_source':(registry or {}).get('source','')}
        item['status_label']='尚未收到状态' if raw is None else '本帧未上报，保留上次状态' if not current else '状态已过期' if item['stale'] else '当前帧已上报'
        devices.append(item)
    return {'devices':devices,'positions':list(positions.values()),'registry':registry,'frame':frame,
        'received_at':str(g.value(FRAME,CU.receivedAt) or ''),'topic':store.settings.mqtt_telemetry_topic,
        'note':'模拟数据；部署关系来自显式配置。未上报不等于不存在，不据此生成探测或干扰因果关系。'}


def facts(store):
    with store.lock:return read_graph(store)+store.config_graph(store.config)


def deployment_query(position_id=None):
    # IDs are validated at API entry; use URI serialization rather than interpolating free text.
    from .domain import CONFIG
    selector=f'VALUES ?position {{ {CU[position_id].n3()} }}' if position_id else ''
    return f'''PREFIX cu: <{CU}>
SELECT ?device ?name ?kind ?position ?positionName WHERE {{
 {selector}
 GRAPH <{DEVICE_GRAPH}> {{ ?device cu:deployedAt ?position; cu:name ?name; cu:deviceKind ?kind . }}
 GRAPH <{CONFIG}> {{ ?position a cu:Position; cu:name ?positionName . }}
}} ORDER BY ?position ?device LIMIT 104'''


TERMS={str(CU[x]) for x in ['UAV','QuadrotorUAV','Jammer','DeviceState','deployedAt','latestDeviceState','stateOfDevice','deviceKind','configurationJson','configurationSource','sourceHandle','sourceRunId','sourceTick','publishedAt','simulationTimeSeconds','presentBlockMask']+list({p for mapping in FIELD_MAP.values() for p in mapping.values()})}
