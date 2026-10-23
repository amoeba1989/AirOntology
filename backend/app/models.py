"""第二版业务模型：配置有版本，观测和评估分别建模。"""
import hashlib
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

ID_PATTERN = r'^[A-Za-z0-9_-]{1,100}$'


RESERVED = {'runtime', 'BlueDevice', 'Position', 'DistanceLevel', 'Observation', 'Assessment', 'DistanceRule',
            'HighAttention', 'MediumAttention', 'LowAttention', 'OutsideThreshold', 'name', 'lon', 'lat',
            'speed', 'timestamp', 'source', 'distanceToPosition', 'positionId', 'positionName', 'positionLon',
            'positionLat', 'ruleVersion', 'highThreshold', 'mediumThreshold', 'lowThreshold', 'staleSeconds',
            'configJson', 'latestObservation', 'latestAssessment', 'ofTarget', 'toPosition', 'basedOnObservation',
            'usedRule', 'hasDistanceLevel'}

RESERVED.update({'analysisPosition', 'AttentionRankingPolicy', 'SituationAnalysis', 'RankedCandidate', 'sortKeys', 'levelOrder', 'hasCandidate', 'usedRankingPolicy', 'basedOnAssessment', 'previousObservation', 'rank', 'levelPriority', 'closingSpeed', 'etaToHighAttention', 'targetIdentifier', 'missingEta', 'maxTrendGapSeconds', 'attention-policy-v1', 'nearest-policy-v1'})

RESERVED.update({'algorithmScore', 'methodName', 'horizontalErrorMeters', 'authorizationRegion', 'usesAuthorization', 'judgementLayer', 'SensorDevice', 'receivedAt', 'scoreMeaning', 'evidenceSource', 'fromDevice', 'subjectReference', 'CameraSensor', 'SuspectedTarget', 'applicableConditions', 'inputObservation', 'AssociationJudgement', 'RadarSensor', 'recordJson', 'dataMode', 'InfraredSensor', 'inputJudgement', 'coordinateSystem', 'validFrom', 'judgesHypothesis', 'concernsRegion', 'IntrusionConditionJudgement', 'uncertaintyNote', 'observedFeatures', 'RadioSensor', 'SensorObservation', 'reportedCoverage', 'reportedAt', 'reportedTargetRef', 'generatedAt', 'detectionOutcome', 'rawEvidenceRef', 'IdentificationJudgement', 'validationRef', 'independenceNote', 'inputQuality', 'validUntil', 'reportedJudgementStatus', 'AuthorizationRecord', 'observedAt', 'authoritySource', 'EvidenceJudgement', 'reportedDeviceStatus', 'geometryRef', 'sensorKind', 'authorizationStatus', 'methodVersion', 'regionDescription', 'EvidenceRegion'})

def valid_identifier(value):
    if value in RESERVED or value.startswith(('obs-', 'eval-', 'rule-', 'analysis-', 'rank-')):
        raise ValueError('编号与本体保留名称冲突，请使用drone001、pos001等业务编号')
    return value


class Position(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)

    @field_validator('id')
    @classmethod
    def identifier(cls, value):
        return valid_identifier(value)


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    positions: list[Position] = Field(min_length=1, max_length=10)
    high_threshold: float = Field(gt=0)
    medium_threshold: float = Field(gt=0)
    low_threshold: float = Field(gt=0, le=100000)
    stale_seconds: float = Field(ge=2, le=3600)
    history_limit: int = Field(default=300, ge=10, le=1000)

    @model_validator(mode='after')
    def valid(self):
        if not self.high_threshold < self.medium_threshold < self.low_threshold:
            raise ValueError('距离阈值必须满足：高 < 中 < 低')
        if len({p.id for p in self.positions}) != len(self.positions):
            raise ValueError('阵地编号不能重复')
        return self

    @property
    def version(self):
        canonical = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        return 'rule-' + hashlib.sha256(canonical.encode()).hexdigest()[:16]


class ConfigChange(BaseModel):
    expected_version: str
    config: RuntimeConfig

RESERVED.update({'deviceStateAtReceipt','validForSeconds'})
