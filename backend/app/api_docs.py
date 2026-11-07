"""面向 Swagger / ReDoc 的中文接口说明，不改变接口行为。"""
from fastapi.routing import APIRoute

# 顺序依次为用途及需要特别说明的行为。
DOCS = {
 '/api/devices': ('查看设备与最新状态', '读取设备登记信息及最近状态。'),
 '/api/devices/ttl': ('导出设备 RDF', '以 Turtle 格式读取设备事实。'),
 '/api/devices/deployments': ('查询设备部署关系', '可按阵地编号筛选；返回 SPARQL 和查询结果。'),
 '/api/devices/validate': ('校验设备数据', '使用 SHACL 校验设备图结构；不证明设备实际工作正常。'),
 '/api/evidence': ('查看多源证据', '读取已登记的设备、观测和判断等证据。'),
 '/api/evidence/ttl': ('导出证据 RDF', '以 Turtle 格式读取多源证据图。'),
 '/api/evidence/validate': ('校验证据结构', '检查结构约束，不验证传感器性能或判断真实性。'),
 '/api/evidence/demo': ('写入演示证据', '会向数据库写入模拟数据；仅在需要演示数据时调用。'),
 '/api/evidence/examples': ('查看证据请求示例', '返回各类证据记录的示例，不写入数据库。'),
 '/api/evidence/{kind}': ('登记一条证据', '写入指定类型的证据。kind 及请求字段可参考 /api/evidence/examples。'),
 '/api/health': ('检查服务健康状态', '返回应用、Fuseki 与 MQTT 的状态；degraded 表示至少一个依赖异常。'),
 '/api/map/config': ('查看地图配置状态', '返回高德地图是否已配置及前端所需配置。'),
 '/_AMapService/{path:path}': ('高德地图服务代理', '供地图组件内部调用；需要服务器完成高德地图配置。'),
 '/api/agent/questions': ('查看支持的态势问题', '返回预设问题及是否配置大模型；不代表模型服务一定可用。'),
 '/api/agent/ask': ('分析并解释态势', '按预设策略计算候选结果，并以 text/event-stream 流式返回；配置模型时可使用模型生成解释。'),
 '/api/config': ('读取阵地与规则配置', 'GET 读取当前配置；PUT 更新配置并要求提供当前版本号，更新会影响业务。'),
 '/api/ontology': ('查看业务本体术语', '读取业务本体中的类、对象属性和数据属性。'),
 '/api/ontology/ttl': ('导出业务本体', '以 Turtle 格式返回业务本体定义。'),
 '/api/ontology/topology': ('查看本体拓扑', '读取本体和有界实例关系快照，不代表全部历史。'),
 '/api/learning/dictionary': ('查看学习模型词典', '读取独立学习模型中的术语及 Turtle 定义。'),
 '/api/learning/term': ('查看术语详情', '按完整 URI 获取术语、相关实例和说明。'),
 '/api/learning/model/preview': ('预览学习模型', '解析并检查 Turtle，不写入数据库。'),
 '/api/learning/model': ('管理学习模型', 'PUT 替换独立学习模型；DELETE 清空该模型。操作会修改数据库，不修改业务本体文件。'),
 '/api/learning/queries': ('查看预设查询', '返回可用查询及所需参数。'),
 '/api/learning/query': ('执行预设查询', '查询实时业务数据，最多返回 100 行；只支持预设 query_id。'),
 '/api/learning/validation/examples': ('查看 RDF 校验样例', '返回正常及异常 Turtle 样例和 SHACL 约束。'),
 '/api/learning/validation': ('校验 RDF 样例', '校验提交的 Turtle 内容，不写入业务数据库。'),
 '/api/learning/validation/current': ('校验当前业务数据', '校验有界当前事实，不包含全部历史。'),
 '/api/situation': ('查看当前态势', '返回阵地、目标及相关评估；at 可指定带时区的历史回放时间。'),
 '/api/targets/{target_id}': ('查看目标详情', '按目标编号读取当前或指定时间的目标状态。'),
 '/api/targets/{target_id}/ttl': ('导出目标 RDF', '按目标编号以 Turtle 格式读取事实。'),
 '/api/assessments/{assessment_id}': ('查看距离评估', '按评估编号读取距离、等级和依据。历史数据可能已超出保留范围。'),
 '/api/assessments/{assessment_id}/ttl': ('导出评估 RDF', '以 Turtle 格式读取评估及其相关事实。'),
 '/api/history': ('查看目标历史观测', '按目标编号读取保留的观测，支持限制返回条数。'),
}


def describe_routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path in DOCS:
            route.summary, route.description = DOCS[route.path]
            if route.path == '/api/health':
                route.responses[200] = {
                    'description': '健康状态示例；实际状态和时间会变化。',
                    'content': {'application/json': {'example': {
                        'status': 'ok', 'fuseki': True,
                        'mqtt': {'connected': True, 'queue_size': 0, 'frame_pending': False,
                                 'superseded_frames': 0, 'rejected': 0, 'dropped': 0,
                                 'last_write': 1794067306.0, 'last_error': None},
                        'version': '2.4.0',
                    }}},
                }
