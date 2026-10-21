from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', allow_inf_nan=False)
    fuseki_url: str = 'http://localhost:3030/counteruav'
    mqtt_host: str = 'localhost'
    mqtt_port: int = 1883
    mqtt_topic: str = 'counteruav/track/blue'
    mqtt_client_id: str = 'airontology-consumer'
    position_id: str = 'pos001'
    position_name: str = '一号阵地'
    position_lon: float = 116.4077
    position_lat: float = 39.9045
    stale_seconds: float = 5
    high_threshold: float = 100
    medium_threshold: float = 200
    low_threshold: float = 300
    ontology_dir: Path = Path(__file__).resolve().parents[2] / 'ontology'
    queue_size: int = 1000

    @model_validator(mode='after')
    def validate_config(self):
        if not 0 < self.high_threshold < self.medium_threshold < self.low_threshold:
            raise ValueError('距离阈值必须满足 0 < 高 < 中 < 低')
        if not -180 <= self.position_lon <= 180 or not -90 <= self.position_lat <= 90:
            raise ValueError('阵地经纬度超出范围')
        if self.stale_seconds <= 0 or self.queue_size < 1:
            raise ValueError('过期时间和队列长度必须大于零')
        return self
