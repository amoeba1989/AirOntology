"""Synthetic messages for ontology learning; no radar detection or RF effect model."""
import math
from .domain import GEOD
from .telemetry import Registry, Registration, Frame, Payload, Entity, utcnow


def make_registry(settings,run_id,count=10,published_at=None):
    positions=settings.initial_config().positions
    devices=[Registration(handle=i,id=f'drone{i:03d}',name=f'无人机{i:03d}',kind='uav',platform='quadrotor',
        parameters={'platform':'quadrotor','cruise_speed_mps':12,'receiver':{'gnss':{'freq_hz':1575420000.0},'rc':{'freq_hz':2400000000.0}},'note':'模拟初始配置，接收参数不代表独立设备'}) for i in range(1,count+1)]
    for i,p in enumerate(positions,start=1):
        devices.append(Registration(handle=1000+i,id=f'radar{i:03d}',name=f'雷达{i:03d}',kind='radar',deployed_at=p.id,
            parameters={'enabled':True,'freq_hz':9500000000.0,'max_range_m':15000.0,'note':'配置声明；没有实时运行健康或探测结果'}))
        devices.append(Registration(handle=2000+i,id=f'jammer{i:03d}',name=f'干扰器{i:03d}',kind='jammer',deployed_at=p.id,
            parameters={'enabled':True,'freq_hz':2400000000.0,'bandwidth_hz':20000000.0,'note':'演示配置；发射状态轮播不计算目标效果'}))
    return Registry(run_id=run_id,published_at=published_at or utcnow(),source='明确登记的模拟设备台账 v1；部署关系仅供学习',devices=devices)


def make_frame(settings,registry,tick,interval=2,published_at=None,omit_handles=()):
    positions=settings.initial_config().positions
    origin=positions[0];by_id={p.id:p for p in positions};entities=[]
    for d in registry.devices:
        if d.handle in omit_handles:continue
        if d.kind=='uav':
            i=d.handle-1;bearing,phase=[(65,0),(110,2.1),(290,4.2)][i] if i<3 else ((37*i+25)%360,i*.63)
            distance=260+240*math.cos(tick*math.pi/36+phase)
            lon,lat,_=GEOD.fwd(origin.lon,origin.lat,bearing,distance)
            old=260+240*math.cos((tick-1)*math.pi/36+phase)
            speed=0 if tick==0 else abs(distance-old)/interval
            raw={'id':d.handle,'name':d.name,'blocks':63,
                'transform':{'latitude_deg':lat,'longitude_deg':lon,'altitude_m':80.0,'yaw_deg':bearing,'pitch_deg':0,'roll_deg':0},
                'motion':{'speed_mps':speed,'mode':6},'flight':{'airspeed_mps':speed},'faction':{'side':2},
                'rf_link':{'gnss_locked':True,'rc_linked':True,'telemetry_linked':True,'gnss_sir_db':0,'rc_sir_db':0},
                'health':{'hp':100,'max_hp':100,'destroyed':False}}
        else:
            point=by_id[d.deployed_at];lon,lat,_=GEOD.fwd(point.lon,point.lat,45 if d.kind=='radar' else 225,35)
            raw={'id':d.handle,'name':d.name,'blocks':9 if d.kind=='radar' else 73,
                'transform':{'latitude_deg':lat,'longitude_deg':lon,'altitude_m':80.0,'yaw_deg':0,'pitch_deg':0,'roll_deg':0},'faction':{'side':1}}
            if d.kind=='jammer':raw['jammer']={'enabled':True,'emitting':tick%10<5,'style':1,'eirp_dbm':59,
                'freq_hz':2400000000.0,'bandwidth_hz':20000000.0,'boresight_yaw_deg':135,'boresight_pitch_deg':0,'half_angle_deg':60,'sidelobe_gain_dbi':-10}
        entities.append(Entity(**raw))
    return Frame(run_id=registry.run_id,published_at=published_at or utcnow(),payload=Payload(tick=tick,client='airontology-demo',
        sim_time_s=tick*interval,scenario_id=1,scenario_name='four-device-ontology-demo',entity_count=len(registry.devices),
        reported_count=len(entities),step_ms=0,entities=entities))
