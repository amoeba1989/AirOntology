# AirOntology · 无人机本体工作台

![AirOntology：连接无人机态势、地理信息与知识图谱](docs/images/airontology-overview-cn.png)

> **让无人机态势看得见，让数据关系和判断依据讲得清。**

[在线体验](http://182.92.185.115:8092/) · [本体拓扑](http://182.92.185.115:8092/back) · [接口文档](http://182.92.185.115:8092/docs) · [本地快速开始](#快速开始)

AirOntology 是一个用于学习和演示无人机态势与知识图谱的项目。它将模拟设备消息、距离规则、RDF 本体和地图展示串成一条可追溯的数据链，帮助理解 **OWL / RDF、SPARQL、SHACL 与 GIS 前端如何协同工作**。

项目把分散的目标、阵地、设备和观测组织成可查询的关系：你可以在地图上查看目标与距离，在拓扑中探索本体和实例，并沿着评估结果找到观测及规则依据。它适合无人机态势场景的原型验证、本体学习和演示。

> 当前主要面向开发、学习和演示。默认航迹及设备数据是模拟数据；距离关注等级是阈值分级，不能直接解释为综合威胁、真实探测结果或违法判断。

## 功能概览

当前版本 **v2.5.2**；系统各页面右下角显示前端版本与后端版本差异。规则引擎使用说明见[规则引擎第一版](docs/规则引擎第一版.md)。

- **态势地图**：展示无人机、阵地、设备、轨迹及距离圈；按阵地查看距离评估，支持历史回放和运行参数配置。
- **本体拓扑工作台**：在 `/back` 查看 TBox 类与继承、ABox 实例关系，以及类和实例的类型对照；支持搜索、聚焦邻居、查看属性、来源和 SHACL 约束。拓扑来自业务模型及有界 RDF 快照，不进行 OWL 自动推理。
- **本体学习与校验**：查看术语和 Turtle 定义、隔离导入学习模型、运行预设 SPARQL 查询、查看 SHACL 校验报告。原学习工具可从拓扑工作台进入。
- **智能态势问答**：使用预设问题和本体策略筛选、排序目标，展示结果依据及 RDF 证据；可选使用 DeepSeek 解释。没有配置密钥时使用规则结果。
- **规则引擎**：在 `/rules` 配置观测过期、雷达上报中断及圆形区域进出规则；支持只读快照试运行、版本发布、恢复草稿和事件证据。原阵地与距离配置统一迁入该入口。
- **设备与多源证据**：接收设备登记、遥测及原始观测，展示设备与阵地关系，并记录来源、不确定性和待核实判断。

证据登记不等于自动完成多源融合、身份识别或区域包含判断。更多范围和限制见[多源证据说明](docs/多源证据增量实现说明.md)。

## 架构

```text
模拟器 / MQTT 数据源
        │ 观测与设备消息
        ▼
  FastAPI + Python ── 距离评估、规则、校验与问答
        │
        ▼
 Apache Jena Fuseki ── RDF 命名图与 SPARQL
        │
        ▼
 Vue 3 + Leaflet ── 态势地图、本体拓扑与学习工具
```

模型定义位于 [`ontology/`](ontology/)，实时数据与有界历史由 Fuseki 保存。业务逻辑、数据模型和设备处理位于 [`backend/app/`](backend/app/)，前端位于 [`frontend/`](frontend/)，模拟器位于 [`simulator/`](simulator/)。

| 技术 | 作用 |
| --- | --- |
| Vue 3、Vite、Leaflet | 页面、交互和地图 |
| FastAPI、Pydantic、RDFLib | 接口、数据校验和 RDF 处理 |
| Apache Jena Fuseki、SPARQL | RDF 存储与查询 |
| OWL / RDFS、SHACL | 业务模型定义与数据约束 |
| Mosquitto、MQTT | 设备和观测消息接入 |
| Docker Compose、GitHub Actions | 本地运行、测试与 ECS 部署 |

## 快速开始

需要 Docker Desktop 或 Docker Engine + Compose；首次构建需要访问镜像与依赖源。

```bash
git clone https://github.com/amoeba1989/AirOntology.git
cd AirOntology
./start-local.sh
```

macOS 也可以双击 `start-local.command`，Windows 可运行 `start-local.bat`。脚本首次运行会从 `.env.example` 创建 `.env`，构建并启动服务与模拟器。打开：

- 态势地图：<http://localhost:8092/>
- 本体拓扑工作台：<http://localhost:8092/back>
- 规则引擎：<http://localhost:8092/rules>
- API 文档：<http://localhost:8092/docs>

如果修改了端口，以启动脚本输出为准。常用操作：

```bash
./start-local.sh status  # 查看状态
./start-local.sh logs    # 查看日志
./start-local.sh stop    # 停止服务，保留数据卷
```

本地 Compose 默认模拟 20 架目标、每 2 秒更新一次，包含远距离通行和环绕巡查等合成航线；ECS 配置默认 10 架。实际运行值可能由环境配置覆盖。参数见 [`.env.example`](.env.example)；高德底图配置见[说明](docs/高德卫星底图与状态排查.md)。

暂时无法启动 Docker 时，可使用[内存 RDF 本地预览](docs/本体证据问答本地预览.md)。预览不连接 Fuseki、MQTT 或 ECS，退出后数据清空。

## 本体与数据范围

TBox 定义业务类、属性及约束；ABox 是目标、阵地、观测和评估等实例事实。典型关系为：

```text
无人机 ──最新观测──▶ 观测
   └──当前评估──▶ 评估 ──针对──▶ 阵地
                        ├──依据──▶ 观测
                        └──采用──▶ 规则快照
```

| 命名图 | 内容 |
| --- | --- |
| `urn:airontology:schema` | 业务模型及基础实例 |
| `urn:airontology:config` | 当前配置和阵地 |
| `urn:airontology:state` | 最新状态及观测、评估指针 |
| `urn:airontology:history` | 有界历史观测、评估与规则快照 |
| `urn:airontology:devices` / `urn:airontology:evidence` | 设备和多源证据 |

拓扑页面读取当前状态、设备、配置、证据和关联的最新观测及评估，最多读取 4000 行，**不代表完整历史或数据库总量**；页面快照需手动刷新。历史默认每个目标保留 300 条观测，可配置，不是永久审计存储。详见[技术栈与实现指南](docs/本体技术栈与代码实现指南.md)。

## 开发与测试

项目 CI 使用 Python 3.12 和 Node.js 22。可先启动开发依赖，再分别运行后端和前端：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d mqtt fuseki
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-dev.txt
PYTHONPATH=backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```bash
python simulator/main.py
# 再开一个终端
cd frontend
npm ci
npm run dev
```

运行测试与构建：

```bash
PYTHONPATH=backend python -m pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run build
```

CI 还会构建 Compose 服务并运行 `python scripts/smoke.py`。前端 DOM 测试不能替代真实浏览器的视觉检查。

## ECS 部署

日常使用两条 GitHub Actions：**Verify AirOntology** 在向 `main` 提交 PR 时检查代码（也可手动运行）；**Deploy AirOntology to ECS** 手动部署 `main`。部署时：工作流先测试、构建和验证镜像，再经 SSH 上传；部署脚本包含备份、健康检查及失败恢复步骤。首次配置、所需 Secrets、架构选择和恢复方式见 [ECS 自动部署说明](docs/ECS自动部署.md)。

部署使用 GitHub `main`，不等同于 Mac 上当前分支的未合并改动。部署后应查看 Actions 运行结果与 `/api/health`，再检查实际页面。

需要排障时，手动运行 **ECS maintenance** 并选择 `diagnose`（只读诊断）、`recover`（重启服务并暂停模拟器）、`resume`（以 15 秒间隔恢复模拟器）或 `configure`（配置 DeepSeek）。操作互斥，使用现有 Secrets；`configure` 需要 DeepSeek Secret。

## 主要接口

项目使用 FastAPI 自动生成交互式 Swagger UI：本地启动后打开 [http://localhost:8092/docs](http://localhost:8092/docs)，线上演示可访问 [Swagger 接口文档](http://182.92.185.115:8092/docs)。也可通过 `/redoc` 查看另一种文档排版，通过 `/openapi.json` 获取机器可读的接口定义；端口以实际运行配置为准。

在 Swagger 中展开接口可查看参数、请求结构和响应模型。`GET` 通常用于读取数据；`POST`、`PUT` 和 `DELETE` 可能产生实际修改，请先确认接口用途，再使用 “Try it out”。当前线上接口未配置登录鉴权，不建议在公开环境中提交敏感数据或执行修改操作。

| 接口 | 用途 |
| --- | --- |
| `GET /api/health` | 服务健康状态 |
| `GET /api/situation`、`GET /api/history` | 当前态势与有界历史 |
| `GET /api/config`、`PUT /api/config` | 读取与更新运行配置 |
| `GET /api/ontology/topology` | 本体及实例拓扑快照 |
| `GET /api/learning/queries`、`POST /api/learning/query` | 预设只读查询 |
| `POST /api/learning/validation/current` | 当前事实 SHACL 校验 |
| `GET /api/devices`、`GET /api/evidence` | 设备与证据 |
| `GET /api/agent/questions`、`POST /api/agent/ask` | 预设问题与流式回答 |

完整请求结构以运行中的 `/docs` 为准。

## 使用边界与安全

- 配置界面及接口目前没有登录鉴权，适合本机或受控演示环境；对外提供服务前应配置认证和访问控制。
- 模拟航迹、设备状态和演示证据不能当作真实业务数据。地图坐标转换及卫星底图配置见对应文档。
- DeepSeek 是可选功能；启用后，相关事实和证据会发送给所配置的模型服务。模型文字不等于经过验证的推理结论。
- 不要将 `.env`、API 密钥、SSH 私钥或服务器密码提交到仓库。停止服务请使用脚本或 `docker compose down`；`down -v` 会删除数据卷。

## 文档索引

- [本体技术栈与代码实现指南](docs/本体技术栈与代码实现指南.md)
- [态势大屏与航迹模拟](docs/态势大屏与航迹模拟.md)
- [本体学习工作台](docs/本体学习工作台.md)
- [本体证据问答](docs/本体证据问答本地预览.md)
- [四类设备与 MQTT 模拟接入](docs/四类设备与MQTT模拟接入.md)
- [多源证据增量实现](docs/多源证据增量实现说明.md)
- [ECS 自动部署](docs/ECS自动部署.md)
- [后续迭代路线](docs/后续迭代路线.md)
