"""Versioned, bounded rule evaluation. No executable user code or control actions."""
import copy
import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Literal as Choice
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rdflib import Literal
from .domain import GEOD, CU
from .views import situation_view
from . import telemetry
from .store import ConfigConflict

GRAPH = 'urn:airontology:rules'
SUBJECT = 'urn:airontology:rules:document'
KINDS = {'observation_stale': '观测过期', 'device_stale': '雷达上报中断', 'zone': '圆形区域进出'}


def now():
    return datetime.now(timezone.utc)


class Rule(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$', description='规则唯一编号')
    name: str = Field(min_length=1, max_length=80, description='中文规则名称')
    kind: Choice['observation_stale', 'device_stale', 'zone']
    enabled: bool = False
    source: str = Field(min_length=1, max_length=500, description='规则依据或来源，演示参数请注明')
    position_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,100}$', description='关联阵地；区域规则必填，雷达规则可用于限定部署阵地')
    seconds: float = Field(default=30, ge=2, le=3600, description='观测有效期或设备中断阈值，秒')
    radius: float = Field(default=300, gt=0, le=100000, description='圆形区域半径，米；使用当前阵地中心及 WGS84 水平距离')

    @model_validator(mode='after')
    def scope(self):
        if self.kind == 'zone' and not self.position_id:
            raise ValueError('圆形区域规则必须选择阵地')
        return self


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    rules: list[Rule] = Field(max_length=40)
    note: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def unique(self):
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError('规则编号重复')
        return self


class Trial(BaseModel):
    rules: list[Rule] = Field(max_length=40)
    at: datetime | None = Field(default=None, description='可选历史时刻；仅支持保留的无人机观测，雷达历史不支持')

    @model_validator(mode='after')
    def valid(self):
        if self.at and (self.at.tzinfo is None or self.at > now()):
            raise ValueError('试运行时间必须包含时区且不能晚于当前时间')
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError('规则编号重复')
        return self


def empty():
    return {'revision': 0, 'rules': [], 'versions': [], 'states': {}, 'events': [], 'results': [], 'evaluated_at': None}


def read(store):
    g = store.construct(f'CONSTRUCT {{ <{SUBJECT}> <{CU.ruleDocument}> ?v }} WHERE {{ GRAPH <{GRAPH}> {{ <{SUBJECT}> <{CU.ruleDocument}> ?v }} }}')
    from rdflib import URIRef
    value = g.value(URIRef(SUBJECT), CU.ruleDocument)
    return json.loads(str(value)) if value is not None else empty()


def write(store, doc):
    value = Literal(json.dumps(doc, ensure_ascii=False, allow_nan=False)).n3()
    store.update(f'DELETE WHERE {{ GRAPH <{GRAPH}> {{ <{SUBJECT}> <{CU.ruleDocument}> ?v }} }}; INSERT DATA {{ GRAPH <{GRAPH}> {{ <{SUBJECT}> <{CU.ruleDocument}> {value} }} }}')


def publish(store, change):
    with store.lock:
        doc = read(store)
        if doc['revision'] != change.expected_revision:
            raise ConfigConflict('规则已被更新，请重新加载；你的草稿仍保留在页面')
        positions = {p.id for p in store.config.positions}
        if any(r.position_id and r.position_id not in positions for r in change.rules):
            raise ValueError('规则引用的阵地不存在')
        doc['revision'] += 1
        doc['rules'] = [r.model_dump() for r in change.rules]
        doc['versions'] = (doc['versions'] + [{'revision': doc['revision'], 'at': now().isoformat(), 'note': change.note, 'rules': copy.deepcopy(doc['rules'])}])[-20:]
        # A revision boundary starts a new baseline, never fabricates an exit.
        doc['states'], doc['results'], doc['evaluated_at'] = {}, [], None
        write(store, doc)
        return public(doc)


def public(doc):
    return {k: v for k, v in doc.items() if k != 'states'}


def age(stamp, reference):
    if not stamp:
        return None
    return (reference - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds()


def evaluate(rules, snapshot, devices, reference, historical=False):
    """Pure snapshot evaluator; unknown is distinct from clear."""
    results = []
    positions = {p['id']: p for p in snapshot['positions']}
    for rule in rules:
        if not rule.enabled:
            continue
        entities = snapshot['targets'] if rule.kind != 'device_stale' else [d for d in devices if d['kind'] == 'radar' and (not rule.position_id or d.get('deployed_at') == rule.position_id)]
        if rule.kind == 'device_stale' and historical:
            entities = []
        if not entities:
            results.append({'rule_id': rule.id, 'rule_name': rule.name, 'entity_id': '—', 'status': 'unknown', 'reason': '不支持雷达历史试运行' if historical and rule.kind == 'device_stale' else '没有匹配的数据，无法判断', 'kind': rule.kind})
        for entity in entities:
            stamp = entity.get('published_at') if rule.kind == 'device_stale' else entity['timestamp']
            elapsed = age(stamp, reference)
            row = {'rule_id': rule.id, 'rule_name': rule.name, 'entity_id': entity['id'], 'kind': rule.kind,
                   'data_mode': entity.get('data_mode', 'unverified'), 'observed_at': stamp,
                   'observation_id': entity.get('observation_id'), 'source': entity.get('source') or entity.get('configuration_source'),
                   'basis': rule.source, 'parameters': rule.model_dump(), 'age_seconds': round(elapsed, 2) if elapsed is not None else None}
            status, reason = 'unknown', '尚无观测时间，无法判断'
            if elapsed is not None and elapsed < -2:
                reason = '设备时间超前，无法判断'
            elif elapsed is not None:
                if rule.kind in ('device_stale', 'observation_stale'):
                    status = 'matched' if elapsed > rule.seconds else 'clear'
                    reason = f'距最后上报 {elapsed:.1f} 秒，阈值 {rule.seconds:g} 秒'
                elif elapsed > rule.seconds:
                    reason = '位置观测过期，不能推断进入或离开'
                elif rule.position_id not in positions:
                    reason = '关联阵地不存在，无法判断'
                else:
                    point = positions[rule.position_id]
                    _, _, distance = GEOD.inv(entity['lon'], entity['lat'], point['lon'], point['lat'])
                    status = 'matched' if distance <= rule.radius else 'clear'
                    reason = f'水平距离 {distance:.1f} 米，圆形区域半径 {rule.radius:g} 米'
                    row.update(distance=distance, position=point, coordinates={'lon': entity['lon'], 'lat': entity['lat']})
            row.update(status=status, reason=reason)
            results.append(row)
    return results


def transition(doc, rows, reference, config_version):
    previous = doc['states']
    states = {}
    for row in rows:
        key = row['rule_id'] + ':' + row['entity_id']
        old = previous.get(key)
        # Geometry/config changes invalidate the old baseline.
        if old and old.get('config_version') != config_version:
            old = None
        # A long sampling/observation gap cannot establish a continuous crossing.
        if old and row['kind'] == 'zone' and row.get('parameters'):
            gap = age(old.get('evaluated_at'), reference)
            observation_gap = age(old.get('observed_at'), datetime.fromisoformat(row['observed_at'])) if row.get('observed_at') else None
            if gap is None or gap > row['parameters']['seconds'] or (observation_gap is not None and observation_gap > row['parameters']['seconds']):
                old = None
        status = row['status']
        row['revision'] = doc['revision']
        row['evaluated_at'] = reference.isoformat()
        state = {'status': status, 'config_version': config_version, 'evaluated_at': reference.isoformat(), 'observed_at': row.get('observed_at')}
        states[key] = state
        event = None
        if not old or old['status'] != status:
            if status == 'unknown':
                event = '无法判断'
            elif row['kind'] == 'zone':
                event = ('进入区域' if old and old['status'] == 'clear' else '首次确认在区域内' if not old else '重新确认在区域内') if status == 'matched' else ('离开区域' if old and old['status'] == 'matched' else None)
            elif status == 'matched':
                event = '触发提醒'
            elif old and old['status'] == 'matched':
                event = '恢复上报'
        if event:
            event_id = hashlib.sha256(f'{doc["revision"]}|{key}|{reference.isoformat()}'.encode()).hexdigest()[:24]
            doc['events'].append(dict(row, event=event, id=event_id, config_version=config_version))
    doc['events'] = doc['events'][-300:]
    doc['states'], doc['results'], doc['evaluated_at'] = states, rows, reference.isoformat()


class Engine:
    def __init__(self, store):
        self.store = store
        self.stop_event = threading.Event()
        self.error = None
        self.thread = None

    def trial(self, trial):
        with self.store.lock:
            reference = trial.at or now()
            snapshot = situation_view(self.store.snapshot_graph(trial.at), self.store.config, trial.at)
            devices = [] if trial.at else telemetry.view(self.store)['devices']
            return {'at': reference.isoformat(), 'results': evaluate(trial.rules, snapshot, devices, reference, bool(trial.at)),
                    'note': '只读快照试运行，不发布、不生成进出事件；历史仅含仍保留的无人机观测，使用草稿参数。'}

    def tick(self):
        with self.store.lock:
            doc = read(self.store)
            reference = now()
            snapshot = situation_view(self.store.snapshot_graph(), self.store.config)
            rows = evaluate([Rule.model_validate(r) for r in doc['rules']], snapshot, telemetry.view(self.store)['devices'], reference)
            transition(doc, rows, reference, self.store.config.version)
            write(self.store, doc)
        self.error = None

    def start(self):
        def work():
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception:
                    self.error = '规则执行失败；结果可能过期，请检查后端日志'
                    logging.exception('规则引擎执行失败')
                self.stop_event.wait(5)
        self.thread = threading.Thread(target=work, name='rule-engine', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
