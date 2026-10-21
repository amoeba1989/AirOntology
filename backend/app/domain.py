from datetime import datetime, timezone
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pyproj import Geod
from rdflib import Graph, Namespace, Literal, RDF, XSD

CU = Namespace('http://counteruav.org/counterUav#')
SCHEMA = 'urn:airontology:schema'
STATE = 'urn:airontology:state'
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
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    speed: float = Field(ge=0)
    timestamp: datetime

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


def evaluate(track, settings):
    _, _, distance = GEOD.inv(track.lon, track.lat, settings.position_lon, settings.position_lat)
    if distance <= settings.high_threshold:
        level = 'HighAttention'
    elif distance <= settings.medium_threshold:
        level = 'MediumAttention'
    elif distance <= settings.low_threshold:
        level = 'LowAttention'
    else:
        level = 'OutsideThreshold'
    return distance, level


def track_graph(track, settings):
    distance, level = evaluate(track, settings)
    graph = Graph()
    graph.bind('cu', CU)
    subject = uri(track.target_id)
    graph.add((subject, RDF.type, CU.BlueDevice))
    for name, value, datatype in [
        ('name', '无人机001' if track.target_id == 'drone001' else f'无人机 {track.target_id}', XSD.string), ('lon', track.lon, XSD.double),
        ('lat', track.lat, XSD.double), ('speed', track.speed, XSD.double),
        ('distanceToPosition', distance, XSD.double), ('timestamp', track.timestamp, XSD.dateTime),
    ]:
        graph.add((subject, CU[name], Literal(value, datatype=datatype)))
    graph.add((subject, CU.monitoredAgainst, uri(settings.position_id)))
    graph.add((subject, CU.hasDistanceLevel, CU[level]))
    return graph
