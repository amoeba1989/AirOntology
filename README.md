# AirOntology · 无人机本体工作台

一个用于学习 RDF/OWL 的最小业务闭环：MQTT实时观测 → Python距离计算 → RDF实例更新 → Fuseki查询 → Leaflet地图展示。

第一版支持一架模拟无人机、一个固定阵地、水平距离分级、中文本体结构、定义TTL与实时实例TTL查看。计算由Python完成，不启用自动推理。只保留最新状态，等级仅表示距离关注程度。

## 一、ECS快速部署

前置条件：Linux ECS已安装Git、Docker及Docker Compose插件，可访问Docker镜像仓库、npm、PyPI及Apache归档站。建议至少2核4GB内存，首次构建会下载依赖。

```bash
sudo mkdir -p /opt/airontology
sudo chown "$USER":"$(id -gn)" /opt/airontology
git clone git@github.com:amoeba1989/AirOntology.git /opt/airontology
cd /opt/airontology
cp .env.example .env
docker compose config --quiet
docker compose build
docker compose up -d --wait
docker compose --profile demo up -d simulator
curl -fsS http://127.0.0.1:8092/api/health
```

如果ECS没有GitHub SSH访问权限，可以将clone地址换成 `https://github.com/amoeba1989/AirOntology.git`。

默认应用地址：`http://127.0.0.1:8092`。默认只监听ECS本机，MQTT和Fuseki不发布宿主机端口。

### 从自己的电脑打开

推荐先使用SSH隧道：在自己电脑终端执行以下命令，将`用户`和`ECS地址`替换成实际值。

```bash
ssh -L 8092:127.0.0.1:8092 用户@ECS地址
```

随后用电脑浏览器打开 `http://localhost:8092`。

长期使用可以参考 `deploy/nginx.conf.example` 设置独立域名反向代理，代理到 `127.0.0.1:8092`。应用按域名根路径部署。配置域名及证书后使用HTTPS。

如需临时直接通过ECS IP访问，可在 `.env` 中设置 `BIND_ADDRESS=0.0.0.0`，执行 `docker compose up -d app`，并在安全组允许自己IP访问8092端口。此演示版没有登录鉴权，访问范围应按实际演示需要设置。

### 演示与日常操作

```bash
# 查看运行状态和日志
docker compose ps
docker compose logs --tail=100 app simulator

# 暂停模拟，超过默认5秒后页面显示数据过期
docker compose --profile demo stop simulator

# 恢复模拟
docker compose --profile demo up -d simulator

# 停止服务；保留数据卷
docker compose --profile demo down

# 更新代码及镜像，并启动演示
git pull --ff-only
docker compose build
docker compose up -d --wait
docker compose --profile demo up -d --force-recreate simulator
```

不要执行 `docker compose down -v`，除非确实需要清空持久化数据。

更改阵地配置后需重建应用容器，并重启模拟器。旧距离在新观测到来时重新计算。第一版固定阵地编号建议保持不变。

## 二、页面使用

1. **实时态势**：阵地、无人机、距离连线、100/200/300米参考圈；支持地图缩放、定位全景和跟随目标。
2. **对象详情**：显示编号、位置、速度、距离、等级、关联阵地和最新观测时间。
3. **中文结构**：查看“类、对象属性、数据属性”，中文名称与英文标识对应。
4. **本体定义TTL**：查看静态结构，理解类别和属性的定义。
5. **当前实例TTL**：从Fuseki查询无人机最新事实，并附关联阵地、等级信息。

模拟器每秒发布一条位置，目标在约20～380米间往返，约72秒一个完整周期。页面每秒轮询接口。

默认底图使用OpenStreetMap。底图不可访问时会提示，目标和阵地仍可显示在网格背景上。可以在 `.env` 中替换 `VITE_TILE_URL` 和 `VITE_TILE_ATTRIBUTION` 为有权使用的WGS84兼容瓦片源，然后执行 `docker compose build app` 和 `docker compose up -d app`。国内GCJ-02底图需要另行做显示坐标转换，不能直接混用。

## 三、本体和存储

- `ontology/cu_ontology.ttl`：本体结构，定义无人机、阵地、等级及属性关系。
- `ontology/initial_data.ttl`：高、中、低、阈值外四个等级实例；固定阵地根据配置生成。
- `urn:airontology:schema`：Fuseki命名图，保存模型和基础实例。
- `urn:airontology:state`：Fuseki命名图，保存目标最新状态。
- Fuseki采用TDB2持久化数据库，数据放在Docker卷中。

业务命名空间：`http://counteruav.org/counterUav#`，简写为 `cu:`。

| 类 | 中文含义 |
| --- | --- |
| BlueDevice | 无人机目标 |
| Position | 阵地 |
| DistanceLevel | 距离关注等级 |

| 等级实例 | 中文含义 | 默认规则 |
| --- | --- | --- |
| HighAttention | 高关注 | 距离≤100米 |
| MediumAttention | 中关注 | 100米<距离≤200米 |
| LowAttention | 低关注 | 200米<距离≤300米 |
| OutsideThreshold | 阈值外 | 距离>300米 |

OWL定义不会自动执行距离计算。Python根据坐标计算水平大地距离，再写入RDF事实。等级实例属于具体取值，并非等级子类。

目标URI由固定命名空间和受校验的目标编号生成。使用一次SPARQL DELETE/INSERT更新最新状态，并在数据库中比较时间戳，避免重复或乱序报文覆盖新状态。服务重启后仍使用数据库中的时间进行判断。

## 四、MQTT报文

主题：`counteruav/track/blue`。

```json
{
  "target_id": "drone001",
  "lon": 116.4074,
  "lat": 39.9042,
  "speed": 12.5,
  "timestamp": "2026-10-21T10:30:00Z"
}
```

经纬度为WGS84，速度单位为米/秒，时间必须带时区。目标编号允许字母、数字、下划线和短横线。经纬度需在合法范围，速度非负，拒绝NaN等非有限值。超过当前时间30秒的未来报文会被拒绝，因此ECS时间应准确。示例时间仅说明格式，实际发布请使用当前时间。

可以在内部容器中通过 `mosquitto_pub` 发布自有测试报文，或在后续接真实设备时调整接入配置。高度字段可附带，但第一版不使用。

## 五、接口

| 接口 | 用途 |
| --- | --- |
| GET /api/health | MQTT及Fuseki状态、队列和错误计数 |
| GET /api/ontology | 本体中文结构 |
| GET /api/ontology/ttl | 静态本体定义文本 |
| GET /api/situation | 阵地及最新目标态势 |
| GET /api/targets/{id} | 指定目标详情 |
| GET /api/targets/{id}/ttl | 指定目标实例及关联信息 |
| GET /docs | FastAPI交互接口文档 |

`/api/health`在依赖故障时返回HTTP 200和`status=degraded`，Docker健康检查会检查JSON状态并标记不健康。MQTT队列溢出和非法报文有计数；写入失败最多重试3次，并在日志和健康信息中显示。演示版不提供消息零丢失保证。

## 六、本地开发及测试

Python 3.12、Node.js 22、Java 17（本地直接启动Fuseki时需要）。

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-dev.txt

# 仅启动依赖服务
docker compose -f compose.yaml -f compose.dev.yaml up -d mqtt fuseki
```

上面的 `compose.dev.yaml` 已为MQTT映射 `127.0.0.1:1883:1883`、为Fuseki映射 `127.0.0.1:3030:3030`，仅限本机访问。也可以直接在本机启动两个服务。

```bash
# 在仓库根目录，后端使用localhost依赖服务
PYTHONPATH=backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 新终端启动前端，Vite自动代理/api到8000
cd frontend
npm ci
npm run dev

# 仓库根目录，新终端启动模拟器
python simulator/main.py

# 后端测试和前端构建
PYTHONPATH=backend python -m pytest backend/tests -q
cd frontend
npm run build
```

应用必须使用单个Uvicorn worker，避免同一进程组重复消费MQTT。Web源码与后端一起构建进应用镜像，不依赖浏览器从CDN下载Vue或Leaflet。

## 七、目录与后续计划

- `backend/app`：配置、校验、空间计算、RDF存取、MQTT消费和API。
- `backend/tests`：核心测试。
- `frontend`：Vue与Leaflet工作台。
- `ontology`：模型定义与基础实例。
- `simulator`：固定航线模拟器。
- `deploy`：Fuseki镜像、消息服务和Nginx配置。
- `docs/开发计划.md`：第一版详细计划与第二版简要计划。
- `docs/本体学习说明.md`：中文术语与代码对应关系。

第二版考虑多目标、多阵地、独立评估记录、历史回放和关系图。当前模型的距离和等级针对单阵地，多阵地需要先引入独立评估对象，不能直接在无人机上堆多个距离值。
