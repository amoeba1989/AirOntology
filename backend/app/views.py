"""把RDF对象与关系转为中文界面需要的JSON，不另存一套态势数据库。"""
from datetime import datetime, timezone
from rdflib import RDF
from .domain import CU, LEVELS


def text(g, s, key, default=''):
    value = g.value(s, CU[key])
    return str(value) if value is not None else default


def number(g, s, key):
    return float(text(g, s, key, '0'))


def assessment_view(g, s):
    observation = g.value(s, CU.basedOnObservation)
    rule = g.value(s, CU.usedRule)
    target = g.value(s, CU.ofTarget)
    level = text(g, s, 'hasDistanceLevel').split('#')[-1]
    label, color = LEVELS.get(level, ('未知', '#87939e'))
    distance = number(g, s, 'distanceToPosition')
    thresholds = [number(g, rule, key) for key in ('highThreshold', 'mediumThreshold', 'lowThreshold')]
    if level == 'HighAttention':
        reason = f'距离 {distance:.1f} 米 ≤ {thresholds[0]:g} 米'
    elif level == 'MediumAttention':
        reason = f'{thresholds[0]:g} 米 < 距离 {distance:.1f} 米 ≤ {thresholds[1]:g} 米'
    elif level == 'LowAttention':
        reason = f'{thresholds[1]:g} 米 < 距离 {distance:.1f} 米 ≤ {thresholds[2]:g} 米'
    else:
        reason = f'距离 {distance:.1f} 米 > {thresholds[2]:g} 米'
    return {'id': str(s).split('#')[-1], 'uri': str(s), 'target_id': str(target).split('#')[-1],
        'target_name': text(g, observation, 'name'), 'position_id': text(g, s, 'positionId'),
        'position_name': text(g, s, 'positionName'), 'position_lon': number(g, s, 'positionLon'),
        'position_lat': number(g, s, 'positionLat'), 'distance': distance,
        'level': level, 'level_label': label, 'color': color, 'reason': reason,
        'timestamp': text(g, s, 'timestamp'), 'observation_id': str(observation).split('#')[-1],
        'source': text(g, observation, 'source'), 'data_mode':text(g,observation,'dataMode','unverified'), 'rule_version': text(g, rule, 'ruleVersion'),
        'thresholds': thresholds, 'stale_seconds': number(g, rule, 'staleSeconds'),
        'observation': {'id': str(observation).split('#')[-1], 'lon': number(g, observation, 'lon'),
                        'lat': number(g, observation, 'lat'), 'speed': number(g, observation, 'speed'),
                        'timestamp': text(g, observation, 'timestamp'), 'source': text(g, observation, 'source'), 'data_mode':text(g,observation,'dataMode','unverified')}}


def situation_view(g, config, at=None):
    reference = at or datetime.now(timezone.utc)
    targets, assessments = [], []
    positions = {p.id: p.model_dump() for p in config.positions} if not at else {}
    for target, obs in g.subject_objects(CU.latestObservation):
        stamp = text(g, obs, 'timestamp')
        observed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        age = max(0, (reference-observed).total_seconds())
        evaluations = []
        for subject in g.objects(target, CU.latestAssessment):
            entry = assessment_view(g, subject)
            if not at and entry['position_id'] not in positions:
                continue
            if at:
                positions[entry['position_id']] = {'id':entry['position_id'], 'name':entry['position_name'],
                    'lon':entry['position_lon'], 'lat':entry['position_lat']}
            entry['stale'] = age > (entry['stale_seconds'] if at else config.stale_seconds)
            entry['config_pending'] = not at and entry['rule_version'] != config.version
            evaluations.append(entry)
        evaluations.sort(key=lambda item:item['distance'])
        nearest = evaluations[0] if evaluations else None
        targets.append({'id':str(target).split('#')[-1], 'uri':str(target), 'name':text(g, obs, 'name'),
            'lon':number(g, obs, 'lon'), 'lat':number(g, obs, 'lat'), 'speed':number(g, obs, 'speed'),
            'timestamp':stamp, 'source':text(g, obs, 'source'), 'data_mode':text(g,obs,'dataMode','unverified'), 'observation_id':str(obs).split('#')[-1],
            'age_seconds':round(age,1), 'stale':age > (nearest['stale_seconds'] if at and nearest else config.stale_seconds),
            'assessments':evaluations, 'nearest_assessment':nearest})
        assessments.extend(evaluations)
    targets.sort(key=lambda item:item['id'])
    assessments.sort(key=lambda item:(item['position_id'],item['distance']))
    return {'mode':'replay' if at else 'live', 'at':reference.isoformat(),
        'positions':list(positions.values()), 'targets':targets, 'assessments':assessments,
        'thresholds':assessments[0]['thresholds'] if at and assessments else [config.high_threshold,config.medium_threshold,config.low_threshold],
        'config_version':config.version, 'stale_seconds':config.stale_seconds,
        'note':'回放使用保留的历史观测及规则快照' if at else '距离排序仅表示距离远近，不代表综合威胁'}
