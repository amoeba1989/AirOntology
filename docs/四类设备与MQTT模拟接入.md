# V2.4：四类对象与 MQTT 模拟接入

这一版用于学习“设备配置和态势消息，怎样变成本体中的实体、属性与关系”。保留无人机、阵地、雷达、干扰器四类业务对象；增加的 `DeviceState`（设备状态）只是记录状态的技术对象。不启用推理引擎。

## 1. 运行后能看到什么

默认两个阵地、10 架无人机、两部雷达、两部干扰器。阵地来自项目已有配置；模拟器通过 MQTT 登记其余设备，每两秒发送一帧态势。雷达、干扰器使用不同地图图标，点击进入“设备与阵地关系”。过期或本帧未上报的设备会弱化显示。历史回放只展示无人机历史，设备面板明确标注仍为最新状态。

页面可以查看：设备清单、显式部署关系、初始配置、实时状态、来源 MQTT JSON、本体字段映射、设备 RDF / TTL，以及固定 SPARQL 查询和 SHACL 结构校验。

```bash
git pull --ff-only
docker compose build
docker compose up -d --wait
docker compose --profile demo up -d --force-recreate simulator
docker compose --profile demo logs --tail=30 simulator app
```

默认本机访问 `http://localhost:8092`。上述命令是本地 Compose 更新方法，ECS 发布仍使用已有部署工作流；不要在已有配置上覆盖 `.env`，也不要删除数据卷。

## 2. 两种 MQTT 消息分别负责什么

| 主题（Topic，消息主题） | 内容 | 用途 |
| --- | --- | --- |
| `counteruav/demo/devices` | `device_registry`，设备登记 | 业务编号、仿真实体句柄、设备类型、初始参数、明确的阵地归属 |
| `counteruav/demo/telemetry` | `telemetry_frame`，态势帧 | 本帧各实体的位置、运动、阵营、链路、健康、干扰器发射状态 |

两个主题可通过 `MQTT_REGISTRY_TOPIC`、`MQTT_TELEMETRY_TOPIC` 修改。登记采用 QoS 1 并保留消息，态势采用 QoS 1 且不保留。模拟器每 15 帧重发登记，断线重连先重发登记。旧版航迹、原始观测主题继续兼容。

**来源边界：** 上传文件定义了态势 `payload` 的字段和分块形式；本项目额外设计了设备登记消息，以及包含 `run_id`（本次运行编号）、`published_at`（UTC 发布时间）、`data_mode`（数据模式）的传输外层。不要认为这些新增字段原本就在外部系统里。后续接入外部仿真器时，需要适配层提供或映射这些信息。

设备登记的简化示例：

```json
{
  "handle": 1001,
  "id": "radar001",
  "name": "雷达001",
  "kind": "radar",
  "deployed_at": "pos001",
  "parameters": {"enabled": true}
}
```

这里 `handle` 对应一次仿真运行中的实体句柄；`id` 是本体使用的稳定业务编号。`deployed_at` 是我们显式声明的演示台账关系，**原文件没有直接证明该设备属于该阵地**。未登记归属就不生成部署关系。`parameters.enabled` 是初始配置，不证明设备此刻工作正常。

阵地编号必须已经存在。模拟器按环境变量生成初始阵地与登记关系；如果你在页面删除或更改了阵地编号，需同步调整模拟台账，否则接入会拒绝不存在的阵地引用。不会按距离自动找一个阵地替代。

## 3. 一条数据怎样变成本体

| 步骤 | 技术及中文含义 | 对应代码 |
| --- | --- | --- |
| 生成设备登记、态势 | Python 模拟器 | `backend/app/demo_telemetry.py` |
| 发布到消息代理 | MQTT 发布/订阅、Paho 客户端 | `simulator/main.py`、`backend/app/consumer.py` |
| 检查并转换字段 | Pydantic 数据验证、RDFLib 三元组构造 | `backend/app/telemetry.py` |
| 说明类与关系含义 | OWL 类、对象属性、数据属性 | `ontology/cu_ontology.ttl` |
| 保存设备及状态事实 | Fuseki，RDF 存储与查询服务 | 命名图 `urn:airontology:devices` |
| 回答归属问题 | SPARQL，RDF 查询语言 | `deployment_query()`、`/api/devices/deployments` |
| 检查关系结构 | SHACL，RDF 数据约束 | `ontology/shapes.ttl`、`/api/devices/validate` |
| 地图与学习界面 | Leaflet、Vue | `frontend/src/main.js`、`frontend/src/devices.js` |

类定义属于 **TBox（术语与模型定义）**：

```turtle
@prefix cu: <http://counteruav.org/counterUav#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

cu:Jammer a owl:Class ; rdfs:label "干扰器"@zh .
cu:deployedAt a owl:ObjectProperty ;
    rdfs:label "部署于"@zh ; rdfs:range cu:Position .
```

具体设备与关系属于 **ABox（实例事实）**，下面是简化示例：

```turtle
@prefix cu: <http://counteruav.org/counterUav#> .
@prefix state: <urn:airontology:telemetry:> .

cu:pos001 a cu:Position .
cu:radar001 a cu:RadarSensor ; cu:deployedAt cu:pos001 .
cu:jammer001 a cu:Jammer ;
    cu:deployedAt cu:pos001 ;
    cu:latestDeviceState state:state-jammer001 .
state:state-jammer001 a cu:DeviceState ;
    cu:stateOfDevice cu:jammer001 ;
    cu:emitterEnabled true ;
    cu:emitterEmitting false .
```

含义：一号雷达、一号干扰器部署于一号阵地；干扰器有一份最新状态，其中总开关已开启、当前没有实际发射。实际入库还包含帧号、发布时间、接收时间、仿真时间和原始字段。

无人机用 `UAV`（无人机）表达，四旋翼用其子类 `QuadrotorUAV` 表达。保留旧 `BlueDevice` 标记以兼容已有代码；它不用于判断仿真红蓝阵营。接收机、GNSS（卫星导航）、RC（遥控）、Telemetry（遥测）的配置和状态先保留为无人机字段，不创建没有独立编号的设备实体。

## 4. 状态更新约定

- 新运行必须先登记。重复消息幂等；旧帧忽略，同帧不同内容拒绝。未登记句柄、非法经纬度、分块位与内容不一致等会被拒绝。
- `sim_time_s` 是仿真秒数，不能当成现实 UTC 时间。模拟器额外提供 UTC 发布时间，服务端另存接收时间。
- 实体本帧未出现：保留上次状态，并标注“本帧未上报”。不能据此认定实体被删除或摧毁。
- 实体出现但某状态块缺失：本次状态不写该字段；缺失不补 `false`，也不冒充当前仍有旧值。
- 雷达态势仅含位置和阵营，不产生具体探测结果；其登记状态为未知。干扰器的开启与发射分别存储。
- 演示中干扰器每五帧切换发射状态，不计算射频传播或作用效果。无人机链路保持连通、比值为占位值，不能用作算法性能数据。
- 无人机位置和地速投影到已有航迹流程，继续距离分级和历史回放。地速与空速分别保存；演示未建风场，两者取相同值。

## 5. 存储边界与后续规则

设备图只保留一份登记、最新完整态势帧和每设备最新状态；最多 104 台设备，单条 MQTT 新消息限制 256KB。无人机历史继续受已有保留数量约束，不新增无限增长的设备帧历史。

切换运行会替换设备图；旧航迹不在这一步清空，未继续上报的旧目标会按已有过期逻辑显示。原始证据模块是另一条数据通路，本次态势不会自动生成其中的探测或融合判断。

当前为单写入工作线程。一个完整态势帧投影到多个旧航迹与设备图时，不是跨请求数据库事务；中途失败会重试，靠运行号、帧号及航迹时间去重。页面短时间内可能看到部分航迹先更新。正式高频接入时可进一步改为批量事务与消息积压监控。

后续添加关系规则前，应先明确对应业务问题、输入证据、规则条件及结论边界。例如“雷达观测了哪个对象”需要具体观测记录；“某干扰器导致链路中断”需要额外作用证据，不能只凭同时发射和链路失联生成因果关系。本版先把可核对的设备类型、部署、设备与状态关系做通。
