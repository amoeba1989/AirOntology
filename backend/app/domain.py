from datetime import datetime, timezone
from typing import Literal as Choice
from urllib.parse import quote
import hashlib
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pyproj import Geod
from rdflib import Graph, Namespace, Literal, RDF, XSD
from .models import valid_identifier

CU = Namespace('http://counteruav.org/counterUav#')
SCHEMA = 'urn:airontology:schema'
STATE = 'urn:airontology:state'
HISTORY = 'urn:airontology:history'
CONFIG = 'urn:airontology:config'
GEOD = Geod(ellps='WGS84')
LEVELS = {
    'HighAttention': ('高关注', '#e45555'),
    'MediumAttention': ('中关注', '#ed9b32'),
    'LowAttention': ('低关注', '#3899ce'),
    'OutsideThreshold': ('阈值外', '#5aab87'),
}


class Track(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='ignore')
    target_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(default='', max_length=80)
    source: str = Field(default='MQTT', min_length=1, max_length=100)
    data_mode: Choice['simulated','unverified','operational'] = 'unverified'
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    speed: float = Field(ge=0)
    timestamp: datetime

    @field_validator('target_id')
    @classmethod
    def identifier(cls, value):
        return valid_identifier(value)

    @field_validator('timestamp')
    @classmethod
    def valid_time(cls, value):
        if value.tzinfo is None:
            raise ValueError('观测时间必须包含时区')
        if (value - datetime.now(timezone.utc)).total_seconds() > 30:
            raise ValueError('观测时间不能超过当前时间30秒')
        return value.astimezone(timezone.utc)


def uri(identifier):
    return CU[quote(identifier, safe='')]


def classify(distance, rule):
    if distance <= rule.high_threshold:
        return 'HighAttention'
    if distance <= rule.medium_threshold:
        return 'MediumAttention'
    if distance <= rule.low_threshold:
        return 'LowAttention'
    return 'OutsideThreshold'


def evaluate(track, settings):
    # 保留第一版计算函数，供单点调用；第二版逐阵地调用同一分类函数。
    _, _, distance = GEOD.inv(track.lon, track.lat, settings.position_lon, settings.position_lat)
    return distance, classify(distance, settings)


def graph():
    result = Graph()
    result.bind('cu', CU)
    return result


def add_values(g, subject, values):
    for key, value, datatype in values:
        g.add((subject, CU[key], Literal(value, datatype=datatype)))


def observation_graphs(track, config):
    """观测ID由目标+时间确定；同一观测的每个阵地有独立评估。"""
    target = uri(track.target_id)
    stamp = track.timestamp.isoformat()
    digest = hashlib.sha256(f'{track.target_id}|{stamp}'.encode()).hexdigest()[:24]
    observation = CU['obs-' + digest]
    rule = CU[config.version]
    state, history = graph(), graph()
    name = track.name or f'无人机{track.target_id.removeprefix("drone")}'
    state.add((target, RDF.type, CU.BlueDevice))
    state.add((target, CU.latestObservation, observation))
    values = [('name', name, XSD.string), ('lon', track.lon, XSD.double),
              ('lat', track.lat, XSD.double), ('speed', track.speed, XSD.double),
              ('timestamp', track.timestamp, XSD.dateTime), ('source', track.source, XSD.string),
              ('dataMode',track.data_mode,XSD.string)]
    add_values(state, target, values)
    history.add((observation, RDF.type, CU.Observation))
    history.add((observation, CU.ofTarget, target))
    add_values(history, observation, values)
    history.add((rule, RDF.type, CU.DistanceRule))
    add_values(history, rule, [('ruleVersion', config.version, XSD.string),
        ('highThreshold', config.high_threshold, XSD.double),
        ('mediumThreshold', config.medium_threshold, XSD.double),
        ('lowThreshold', config.low_threshold, XSD.double),
        ('staleSeconds', config.stale_seconds, XSD.double)])
    for point in config.positions:
        _, _, distance = GEOD.inv(track.lon, track.lat, point.lon, point.lat)
        assessment = CU['eval-' + hashlib.sha256(f'{digest}|{point.id}|{config.version}'.encode()).hexdigest()[:24]]
        state.add((target, CU.latestAssessment, assessment))
        history.add((assessment, RDF.type, CU.Assessment))
        history.add((assessment, CU.ofTarget, target))
        history.add((assessment, CU.toPosition, uri(point.id)))
        history.add((assessment, CU.basedOnObservation, observation))
        history.add((assessment, CU.usedRule, rule))
        history.add((assessment, CU.hasDistanceLevel, CU[classify(distance, config)]))
        add_values(history, assessment, [('distanceToPosition', distance, XSD.double),
            ('timestamp', track.timestamp, XSD.dateTime), ('positionId', point.id, XSD.string),
            ('positionName', point.name, XSD.string), ('positionLon', point.lon, XSD.double),
            ('positionLat', point.lat, XSD.double)])
    return state, history
