"""Ontology learning views: bounded reads, fixed queries and SHACL without inference."""
from datetime import datetime, timezone
from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef
from pyshacl import validate
from .domain import CU, SCHEMA, STATE, HISTORY, CONFIG, graph

LEARNING = URIRef(str(CU) + 'graph/learning-schema')
SH = Namespace('http://www.w3.org/ns/shacl#')
KINDS = [(OWL.Class, '类'), (OWL.ObjectProperty, '对象属性'), (OWL.DatatypeProperty, '数据属性')]
PREFIX = f'PREFIX cu: <{CU}>\nPREFIX rdfs: <{RDFS}>\n'


def label(g, subject):
    labels = list(g.objects(subject, RDFS.label))
    return str(next((v for v in labels if v.language == 'zh'), labels[0] if labels else subject))


def dictionary(g):
    items = []
    for rdf_type, kind in KINDS:
        for subject in sorted(set(g.subjects(RDF.type, rdf_type)), key=str):
            items.append({'uri': str(subject), 'id': str(subject).split('#')[-1], 'kind': kind,
                          'label': label(g, subject), 'comment': str(g.value(subject, RDFS.comment) or ''),
                          'domain': [str(v) for v in g.objects(subject, RDFS.domain)],
                          'range': [str(v) for v in g.objects(subject, RDFS.range)]})
    return items


def parse_turtle(ttl):
    # Only in-memory Turtle parsing; no URL input, imports or JSON-LD contexts.
    try:
        g = graph().parse(data=ttl, format='turtle', publicID=str(CU))
    except Exception as error:
        raise ValueError('TTL 语法错误，请检查前缀、分号、句号和引号') from error
    if len(g) > 3000:
        raise ValueError('学习样例最多包含 3000 条三元组')
    return g


def model_graph(store, directory):
    imported = store.construct(f'CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{LEARNING}> {{ ?s ?p ?o }} }}')
    return (imported, 'learning') if len(imported) else (Graph().parse(directory / 'cu_ontology.ttl', format='turtle'), 'business')


def validate_model(g):
    items = dictionary(g)
    if not items or len(items) > 200:
        raise ValueError('模型需声明 1～200 个 OWL 类或属性')
    if any(g.triples((None, OWL.imports, None))):
        raise ValueError('请导出完整 Turtle 模型；学习导入不加载 owl:imports 外部文件')
    if any(not isinstance(s, URIRef) or not list(g.objects(s, RDFS.label))
           for kind, _ in KINDS for s in g.subjects(RDF.type, kind)):
        raise ValueError('每个类和属性都需要 URI 和 rdfs:label 名称')
    return items


def current_graph(store, directory):
    """A bounded current projection, not the full historical database."""
    # Select first 100 targets explicitly. The same set bounds all joined facts.
    roots = f'''{{ SELECT ?target WHERE {{ GRAPH <{STATE}> {{ ?target a cu:BlueDevice }} }}
                ORDER BY ?target LIMIT 100 }}
       GRAPH <{STATE}> {{ ?target cu:latestObservation ?obs; cu:latestAssessment ?assessment }}
       GRAPH <{HISTORY}> {{ ?assessment cu:usedRule ?rule }}'''
    g = store.construct(PREFIX + f'''CONSTRUCT {{ ?target a cu:BlueDevice; cu:latestObservation ?obs;
         cu:latestAssessment ?assessment . ?s ?p ?o }} WHERE {{ {roots}
         VALUES ?which {{ 1 2 3 }}
         BIND(IF(?which=1, ?obs, IF(?which=2, ?assessment, ?rule)) AS ?s)
         GRAPH <{HISTORY}> {{ ?s ?p ?o }} }}''')
    g += store.config_graph(store.config)
    g += Graph().parse(directory / 'initial_data.ttl', format='turtle')
    return g


def term_view(model, facts, term):
    subject = URIRef(term)
    item = next((item for item in dictionary(model) if item['uri'] == term), None)
    if item is None:
        raise ValueError('词典中没有这个术语')
    snippet = graph()
    for triple in model.triples((subject, None, None)):
        snippet.add(triple)
    relations = []
    if item['kind'] == '类':
        candidates = sorted(set(facts.subjects(RDF.type, subject)), key=str)
        for prop, _, endpoint in model.triples((None, RDFS.domain, subject)):
            relations.append({'direction': '从此类出发', 'uri': str(prop), 'label': label(model, prop),
                              'other': [label(model, v) for v in model.objects(prop, RDFS.range)]})
        for prop, _, endpoint in model.triples((None, RDFS.range, subject)):
            relations.append({'direction': '指向此类', 'uri': str(prop), 'label': label(model, prop),
                              'other': [label(model, v) for v in model.objects(prop, RDFS.domain)]})
        examples = [{'subject': str(s), 'predicate': str(RDF.type), 'object': term,
                     'label': label(facts, s)} for s in candidates[:20]]
    else:
        triples = sorted(facts.triples((None, subject, None)), key=lambda t: tuple(map(str, t)))
        candidates = triples
        examples = [{'subject': str(s), 'predicate': term, 'object': str(o),
                     'label': label(facts, s)} for s, _, o in triples[:20]]
    return {**item, 'ttl': snippet.serialize(format='turtle'), 'relations': relations,
            'examples': examples, 'count': len(candidates),
            'scope': '当前最多 100 架无人机的最新观测、评估、规则及当前阵地；不含全部历史。'}


CATALOG = [
    {'id': 'current', 'title': '当前有哪些无人机？', 'concept': 'GRAPH（指定命名图）、SELECT（选择结果列）', 'parameters': [],
     'note': '读取 state 当前状态图；包含数据过期的目标，时间列可用于判断新旧。'},
    {'id': 'nearby', 'title': '选中阵地距离阈值内有哪些无人机？', 'concept': '跨图关联、FILTER（筛选）、ORDER BY（排序）', 'parameters': ['position_id'],
     'note': '关联 state 当前指针与 history 评估；只返回有效时间内、当前规则版本且在低关注阈值内的结果。'},
    {'id': 'evidence', 'title': '选中无人机的评估依据是什么？', 'concept': '对象属性连接观测、阵地和规则', 'parameters': ['target_id'],
     'note': '读取该无人机最新评估的原始依据；时间和规则版本可能已过期，不自动判为当前有效告警。'},
    {'id': 'history', 'title': '选中无人机最近上报过哪些位置？', 'concept': '历史图、时间排序、LIMIT（限制数量）', 'parameters': ['target_id'],
     'note': '最多显示最近 100 条仍保留的观测，不包含已清理数据。'},
    {'id': 'graphs', 'title': 'TBox、当前状态和历史数据分别存在哪里？', 'concept': '命名图、COUNT（计数）、GROUP BY（分组）', 'parameters': [],
     'note': '统计四个业务命名图中的三元组；不包含独立学习模型图。'},
]


def preset_query(query_id, config, target_id=None, position_id=None):
    # Parameters are validated IDs at the API boundary; never accept a SPARQL string.
    if query_id == 'current':
        body = f'''SELECT ?target ?name ?time ?lon ?lat WHERE {{ GRAPH <{STATE}> {{
 ?target a cu:BlueDevice; cu:name ?name; cu:timestamp ?time; cu:lon ?lon; cu:lat ?lat
}} }} ORDER BY ?target LIMIT 100'''
    elif query_id == 'nearby':
        from rdflib import Literal, XSD
        cutoff = datetime.now(timezone.utc).timestamp() - config.stale_seconds
        stamp = Literal(datetime.fromtimestamp(cutoff, timezone.utc), datatype=XSD.dateTime).n3()
        body = f'''SELECT ?target ?position ?assessment ?distance ?time WHERE {{
 GRAPH <{STATE}> {{ ?target cu:latestAssessment ?assessment }}
 GRAPH <{HISTORY}> {{ ?assessment cu:toPosition ?position; cu:distanceToPosition ?distance;
   cu:timestamp ?time; cu:usedRule <{CU[config.version]}> }}
 FILTER (?position = <{CU[position_id]}> && ?distance <= {config.low_threshold} && ?time >= {stamp})
}} ORDER BY ?distance LIMIT 100'''
    elif query_id == 'evidence':
        body = f'''SELECT ?target ?assessment ?position ?observation ?rule ?distance ?time WHERE {{
 VALUES ?target {{ <{CU[target_id]}> }}
 GRAPH <{STATE}> {{ ?target cu:latestAssessment ?assessment }}
 GRAPH <{HISTORY}> {{ ?assessment cu:toPosition ?position; cu:basedOnObservation ?observation;
   cu:usedRule ?rule; cu:distanceToPosition ?distance; cu:timestamp ?time }}
}} ORDER BY ?position LIMIT 100'''
    elif query_id == 'history':
        body = f'''SELECT ?target ?observation ?time ?lon ?lat WHERE {{
 VALUES ?target {{ <{CU[target_id]}> }}
 GRAPH <{HISTORY}> {{ ?observation a cu:Observation; cu:ofTarget ?target; cu:timestamp ?time;
   cu:lon ?lon; cu:lat ?lat }}
}} ORDER BY DESC(?time) LIMIT 100'''
    elif query_id == 'graphs':
        body = f'''SELECT ?graph (COUNT(*) AS ?triples) WHERE {{
 VALUES ?graph {{ <{SCHEMA}> <{STATE}> <{HISTORY}> <{CONFIG}> }}
 GRAPH ?graph {{ ?s ?p ?o }}
}} GROUP BY ?graph ORDER BY ?graph LIMIT 4'''
    else:
        raise ValueError('未知的查询模板')
    return PREFIX + body


def validate_facts(facts, directory):
    shapes = Graph().parse(directory / 'shapes.ttl', format='turtle')
    conforms, report, _ = validate(facts, shacl_graph=shapes, inference='none',
                                   advanced=False, js=False, do_owl_imports=False)
    results = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        results.append({'focus': str(report.value(result, SH.focusNode) or ''),
                        'path': str(report.value(result, SH.resultPath) or ''),
                        'message': str(report.value(result, SH.resultMessage) or '不符合约束'),
                        'constraint': str(report.value(result, SH.sourceConstraintComponent) or ''),
                        'shape': str(report.value(result, SH.sourceShape) or ''),
                        'severity': str(report.value(result, SH.resultSeverity) or '')})
    results.sort(key=lambda r: (r['focus'], r['path'], r['message']))
    focus_count = len(set(s for kind in (CU.Observation, CU.Assessment, CU.Position)
                          for s in facts.subjects(RDF.type, kind)))
    return {'conforms': bool(conforms), 'results': results[:100], 'result_count': len(results),
            'focus_count': focus_count, 'triple_count': len(facts),
            'report_ttl': report.serialize(format='turtle'), 'inference': 'none',
            'note': '仅检查显式声明为观测、评估、阵地的实例；无对应实例不代表业务数据完整。最多展示 100 条错误。'}
