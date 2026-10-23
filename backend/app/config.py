from pathlib import Path
from urllib.parse import urlsplit
from pydantic import model_validator
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', allow_inf_nan=False)
    fuseki_url: str = 'http://localhost:3030/counteruav'
    mqtt_host: str = 'localhost'
    mqtt_port: int = 1883
    mqtt_topic: str = 'counteruav/track/blue'
    mqtt_observation_topic: str = 'counteruav/observation/raw'
    mqtt_registry_topic: str = 'counteruav/demo/devices'
    mqtt_telemetry_topic: str = 'counteruav/demo/telemetry'
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
    history_limit: int = 300
    deepseek_api_key: SecretStr = SecretStr('')
    deepseek_base_url: str = 'https://api.deepseek.com'
    deepseek_model: str = 'deepseek-flash'

    def initial_config(self):
        from .models import Position, RuntimeConfig
        from .domain import GEOD
        lon, lat, _ = GEOD.fwd(self.position_lon, self.position_lat, 90, 450)
        second_id = "pos002" if self.position_id != "pos002" else "pos003"
        return RuntimeConfig(positions=[
            Position(id=self.position_id, name=self.position_name, lon=self.position_lon, lat=self.position_lat),
            Position(id=second_id, name="二号阵地", lon=lon, lat=lat),
        ], high_threshold=self.high_threshold, medium_threshold=self.medium_threshold,
           low_threshold=self.low_threshold, stale_seconds=self.stale_seconds, history_limit=self.history_limit)

    @model_validator(mode='after')
    def validate_config(self):
        topics=[self.mqtt_topic,self.mqtt_observation_topic,self.mqtt_registry_topic,self.mqtt_telemetry_topic]
        if len(set(topics))!=4:raise ValueError('四个接入主题不能相同')
        endpoint = urlsplit(self.deepseek_base_url)
        if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError('DeepSeek地址必须是无用户名、密码或查询参数的HTTPS接口地址')
        if not 0 < self.high_threshold < self.medium_threshold < self.low_threshold:
            raise ValueError('距离阈值必须满足 0 < 高 < 中 < 低')
        if not -180 <= self.position_lon <= 180 or not -90 <= self.position_lat <= 90:
            raise ValueError('阵地经纬度超出范围')
        if self.stale_seconds <= 0 or self.queue_size < 1:
            raise ValueError('过期时间和队列长度必须大于零')
        return self
