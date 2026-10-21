# AirOntology · 无人机本体工作台 V2

通过“MQTT观测 → Python计算 → RDF事实 → Fuseki查询 → Leaflet展示”理解本体。第二版把无人机、观测、评估、阵地和规则分开建模，不启用自动推理。

## 第二版能做什么

- 模拟3架无人机，首次启动默认配置2个固定阵地；每架目标对每个阵地独立评估。
- 点击阵地查看无人机距离排序，点击无人机查看各阵地评估。
- 查看评估依据：原始观测、来源、时间、当时阵地坐标、规则版本和阈值。
- 查看中文本体结构、定义TTL和选中目标实例TTL。
- 加载选中目标的有界历史，拖动时间轴、播放、暂停、返回实时。
- 页面维护阵地、阈值、过期时间和历史保留数量；配置持久化，旧评估不改写。

**距离关注等级只表示距离阈值分级，不是综合威胁判断。**

## GitHub Actions部署ECS

已提供手动部署工作流 **Deploy AirOntology to ECS**：在GitHub完成镜像构建与测试，通过SSH上传三个最终镜像，ECS导入后启动。服务器无需访问Docker Hub拉取镜像。支持架构检查、停写备份、健康检查和失败后尝试恢复上一发布。

先按照 [ECS自动部署说明](docs/ECS自动部署.md) 配置4项GitHub Secrets，再从Actions页面触发。

## 一、运行和更新

需要Docker Desktop（Mac）或Docker Engine及Compose（Linux）。首次构建需要访问Docker Hub、npm、PyPI及Apache归档站。

```bash
git clone git@github.com:amoeba1989/AirOntology.git
cd AirOntology
cp .env.example .env
docker compose build
docker compose up -d --wait
docker compose --profile demo up -d simulator
```

Mac浏览器打开 `http://localhost:8092`。ECS默认仅监听本机，可使用SSH隧道或参考 `deploy/nginx.conf.example` 配置独立域名根路径反向代理。

已有第一版项目：

```bash
cd AirOntology
# 如有自行修改，先提交或妥善保存修改，再拉取。
git pull --ff-only
docker compose build
docker compose up -d --wait
docker compose --profile demo up -d --force-recreate simulator
```

本次同时修复Fuseki首次启动时数据库目录未创建的问题，请重建Fuseki和应用镜像。

第一次升级前建议停止服务并备份数据。第一版已有最新位置会自动补齐观测和评估，无法恢复第一版未保存的历史。详情见 [第二版说明](docs/第二版说明.md)。不要执行 `down -v`，除非确实要删除数据。

Docker拉取成功但构建报认证失败/TLS超时属于构建网络问题，本次功能升级不保证解决该环境问题。Mac应在Docker Desktop配置可用代理；终端代理测试不能完全代表构建器网络。

### 操作命令

```bash
# 状态和日志
docker compose ps -a
docker compose logs --tail=100 app simulator

# 暂停/恢复真实消息模拟；页面回放暂停不会停止MQTT接入
docker compose --profile demo stop simulator
docker compose --profile demo up -d simulator

# 只停止服务，保留数据
docker compose --profile demo down

# 完整服务验收（本机有Python时）
python3 scripts/smoke.py
```

默认服务端口8092。配置界面没有登录鉴权，适用于本机或受限演示环境，不应直接向不受控访问者开放配置接口。

## 二、建议演示顺序

1. 在地图和对象下拉框选择无人机001，再选择一号、二号阵地，对比独立评估。
2. 查看选中阵地的距离排序，点击“查看评估”。解释面板会锁定该条记录。
3. 对照“观测标识 → 评估记录 → 阵地 → 规则版本”，说明结果来源。
4. 切换中文结构和TTL，认识Observation（观测）、Assessment（评估）、DistanceRule（规则）。
5. 运行约20秒后点击“加载选中目标历史”，播放或拖动时间轴；此时实时接入仍继续。
6. 返回实时，在配置中调整阵地或阈值；下一条观测采用新版本，旧评估保留原坐标和规则。
7. 停止模拟器，超过配置的过期时间后页面显示过期。

回放按选中目标保留的观测时间推进，在每个时间点显示各目标当时最近的一条观测。不存在该时刻之前的保留观测时，该目标不会出现。所有回放接口均为只读，不会重新发布MQTT消息。

## 三、本体模型与数据

| 类 | 中文含义 |
| --- | --- |
| BlueDevice | 持续存在的无人机目标 |
| Position | 阵地 |
| Observation | 某来源在某时刻上报的观测 |
| Assessment | 一条观测针对一个阵地的距离与等级评估 |
| DistanceRule | 使用的规则快照 |
| DistanceLevel | 高、中、低关注和阈值外四种等级的类别 |

无人机通过latestObservation关联最新观测，通过latestAssessment关联多个当前评估；评估通过basedOnObservation、toPosition、usedRule分别关联观测、阵地和规则。

| Fuseki命名图 | 用途 |
| --- | --- |
| urn:airontology:schema | 静态本体定义与等级实例 |
| urn:airontology:config | 当前运行配置及阵地 |
| urn:airontology:state | 无人机最新状态和观测/评估指针 |
| urn:airontology:history | 有界观测、评估及不可变规则快照 |

每目标默认保留300条观测，可在10～1000之间配置。清理观测时同步清理其评估，未引用的规则也清理。不是永久审计存储，目标持续上报时默认约保留5分钟。

规则版本是完整配置的内容摘要；位置、阈值、过期时间或保留数量变化均可能产生新版本。旧评估保存计算时的阵地名称、坐标、阈值和观测来源。配置只作用于下一条有效新观测，等待期间显示“旧配置/待新观测”。

`.env`中的阵地和阈值仅在数据库没有运行配置时作为初始值。后续以页面持久化配置为准，重启不会用环境变量覆盖它。

## 四、MQTT报文

主题：`counteruav/track/blue`。

```json
{
  "target_id": "drone001",
  "name": "无人机001",
  "source": "固定航线模拟器",
  "lon": 116.4074,
  "lat": 39.9042,
  "speed": 12.5,
  "timestamp": "2026-10-21T10:30:00Z"
}
```

name与source可省略。经纬度为WGS84，速度单位为米/秒，时间必须带时区，实际消息请使用当前时间。拒绝非法数值、过远未来时间、重复及乱序覆盖；业务编号不能与阵地编号和本体保留标识冲突。

地图底图默认OpenStreetMap，无法访问时仍显示对象和网格背景。通过 `.env` 中的 `VITE_TILE_URL` 和 `VITE_TILE_ATTRIBUTION` 更换有使用权限的WGS84兼容瓦片，再重建应用镜像。国内GCJ-02底图不能直接与WGS84坐标混用。

## 五、接口

| 接口 | 用途 |
| --- | --- |
| GET /api/health | 服务健康与消息处理状态 |
| GET /api/config | 当前配置和版本 |
| PUT /api/config | 携带expected_version保存配置，冲突返回409 |
| GET /api/situation | 当前多目标多阵地态势 |
| GET /api/situation?at=时间 | 指定时间的历史快照；时间需URL编码 |
| GET /api/targets/{id} | 指定目标，可加at参数 |
| GET /api/targets/{id}/ttl | 目标关联实例TTL，可加at参数 |
| GET /api/assessments/{id} | 评估及观测、规则依据 |
| GET /api/assessments/{id}/ttl | 单条评估关联事实TTL |
| GET /api/history?target_id=编号&limit=300 | 保留的观测和评估，时间升序 |
| GET /api/ontology | 中文本体结构 |
| GET /api/ontology/ttl | 静态本体TTL |
| GET /docs | FastAPI交互接口文档 |

时间参数示例：`2026-10-21T10%3A30%3A00Z`，前端自动编码。

## 六、本地开发与测试

Python 3.12、Node.js 22。Compose运行依赖服务：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d mqtt fuseki
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-dev.txt
PYTHONPATH=backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

新终端分别运行 `python simulator/main.py` 与前端：

```bash
cd frontend
npm ci
npm run dev
```

测试：

```bash
# 仓库根目录
PYTHONPATH=backend python -m pytest backend/tests -q
cd frontend
npm test
npm run build
```

前端自动测试采用模拟API与DOM环境，验证交互，不代替真实浏览器视觉验收。后端用RDFLib执行实际SPARQL进行测试，并另行与真实Fuseki联调。应用使用单Uvicorn worker，配置写入和MQTT处理在进程内串行协调；不是多实例部署方案。

具体学习说明见 [本体学习说明](docs/本体学习说明.md)，升级和限制见 [第二版说明](docs/第二版说明.md)。
