# GitHub Actions 部署到阿里云 ECS

工作流：`.github/workflows/deploy-ecs.yml`，显示名称 **Deploy AirOntology to ECS**。

## 1. 工作方式

在GitHub runner上测试并构建三个最终镜像，启动完整服务完成冒烟检查，再将确切镜像打包，通过SSH上传ECS。ECS执行docker load并启动，不从Docker Hub、npm、PyPI或Apache下载项目运行依赖，也不需要配置GitHub仓库拉取密钥。

目前只提供手动触发，且只允许main分支。界面可选择amd64/arm64和是否启动模拟器。常见Intel/AMD ECS选择amd64；`uname -m`为aarch64选择arm64。工作流会再次核对ECS架构，不匹配时不停止现有服务。

## 2. ECS准备

ECS需安装Docker和Docker Compose插件，SSH用户能执行docker命令且能写入部署目录；系统需有bash、tar、gzip、sha256sum、flock。Ubuntu通常已包含这些系统工具。服务器需要有足够空间存放运行镜像、传输包和数据库备份。

在ECS的终端检查：

```bash
docker info
docker compose version
uname -m
```

默认部署到 `/opt/airontology`。若SSH用户不是root，先由有权限的用户创建并授权该目录。例如在准备作为部署用户的终端中：

```bash
sudo mkdir -p /opt/airontology
sudo chown "$USER":"$(id -gn)" /opt/airontology
```

确保GitHub runner可以通过ECS的公网地址/域名访问SSH端口。若安全组只允许你的Mac IP访问，GitHub runner也会被阻止，需按实际网络方案调整规则或使用受控的自托管runner。

## 3. 选择登录方式

支持密码和SSH密钥两种方式，任选其一。若同时配置，优先使用密钥。

**密码方式：** 将ECS登录密码保存为GitHub仓库Secret `ECS_PASSWORD`，不需要生成密钥。ECS需已允许所选用户通过密码SSH登录；工作流不会自动修改服务器SSH认证策略。

**密钥方式：** 按下面步骤生成专用密钥，并保存为 `ECS_SSH_KEY`。

### 创建专用SSH密钥

在Mac终端生成专用于此部署的密钥，不覆盖已有密钥：

```bash
ssh-keygen -t ed25519 -f ~/.ssh/airontology_actions -C airontology-github-actions -N ""
cat ~/.ssh/airontology_actions.pub
```

将上面公钥的一整行追加到ECS部署用户的 `~/.ssh/authorized_keys`，目录权限700、文件权限600。可通过阿里云控制台终端操作，不需要把私钥发到聊天中。

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
# 使用编辑器把Mac生成的.pub公钥追加到下面文件，不覆盖原内容
nano ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

然后在Mac测试，替换实际用户和地址：

```bash
ssh -i ~/.ssh/airontology_actions 用户@ECS地址
```

密钥方式使用无口令的专用密钥，不支持带私钥口令的交互解锁；密码方式通过sshpass环境变量传递，不写入命令行参数或仓库。

## 4. 配置GitHub Secrets

仓库打开 **Settings → Secrets and variables → Actions → Secrets → New repository secret**。

| Secret名称 | 内容 |
| --- | --- |
| ECS_HOST | ECS公网IPv4地址或域名，不含http://、端口或用户名 |
| ECS_USER | SSH登录用户，例如root或ubuntu |
| ECS_SSH_KEY | 密钥方式填写专用SSH私钥完整内容，包含BEGIN/END行 |
| ECS_PASSWORD | 密码方式填写ECS登录密码；与ECS_SSH_KEY任选一项 |
| ECS_KNOWN_HOSTS | 经核实的服务器SSH主机公钥条目 |

Mac上密钥方式复制私钥到剪贴板后直接粘贴进ECS_SSH_KEY：

```bash
pbcopy < ~/.ssh/airontology_actions
```

### 获取并核对主机公钥

在Mac执行（替换实际地址和端口）：

```bash
ssh-keyscan -t ed25519 -p 22 ECS地址 > /tmp/airontology-known-hosts
ssh-keygen -lf /tmp/airontology-known-hosts
```

通过阿里云控制台终端在ECS核对其指纹：

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

确认SHA256指纹一致后，复制整个known_hosts文件内容到ECS_KNOWN_HOSTS：

```bash
pbcopy < /tmp/airontology-known-hosts
```

工作流启用严格主机校验，不会在运行时自动信任未知服务器。非22端口的known_hosts条目包含 `[地址]:端口`，应按实际SSH端口生成。

## 5. 可选Variables

同一页面切到 **Variables → New repository variable**：

| 名称 | 默认值/含义 |
| --- | --- |
| ECS_PORT | 默认22 |
| ECS_DEPLOY_PATH | 默认/opt/airontology；绝对路径，仅字母、数字、下划线、短横线和斜杠 |
| VITE_TILE_URL | 自有WGS84兼容瓦片URL；为空使用默认底图 |
| VITE_TILE_ATTRIBUTION | 对应底图署名；为空使用默认署名 |

应用端口、绑定地址等运行配置位于ECS的 `/opt/airontology/shared/.env`。首次部署从现有部署根目录的.env复制（若存在），否则使用仓库.env.example；后续不覆盖此文件。

默认只监听 `127.0.0.1:8092`，因此部署成功后不能直接从公网IP打开8092。可沿用Nginx反向代理，或在Mac开SSH隧道：

```bash
ssh -L 8092:127.0.0.1:8092 用户@ECS地址
```

再打开 `http://localhost:8092`。

## 6. 执行部署

1. 打开仓库 **Actions**。
2. 选择 **Deploy AirOntology to ECS**。
3. 点击 **Run workflow**，分支选择main。
4. 选择实际ECS架构；按演示需要勾选启动模拟器。
5. 执行并查看各步骤日志。

流程：测试 → 构建 → 完整服务检查 → 上传 → 校验 → 导入镜像 → 停写备份 → 启动 → 健康检查 → 切换current。

首次构建可能较慢，镜像传输时间取决于ECS带宽。当前任务超时60分钟。工作流只部署通过本次测试的提交，不在ECS执行git pull，避免部署到不同版本。

## 7. 数据、发布目录与恢复

目录结构：

```text
/opt/airontology/
├── shared/.env          # 持久运行配置
├── releases/发布编号/    # Compose、镜像标签与消息服务配置
├── current              # 最近成功发布的软链接
├── backups/发布编号/     # 停写后的Fuseki备份与运行环境配置
└── incoming/发布编号/    # 传输暂存，成功后移除大包
```

项目名称固定为airontology，沿用原来的命名数据卷。脚本不执行down -v或镜像/数据卷prune。更新包含短暂停机：停止写入和Fuseki后备份TDB2，再启动新服务。

失败时保留日志、备份和镜像，尝试启动current指向的上一版服务；没有上一版工作流发布时，停止候选应用并报告失败。自动恢复只恢复服务版本，不自动覆盖数据库；若升级修改了数据模式，应根据备份人工决定数据恢复，不能假定旧代码一定兼容新数据。

发布配置、备份及旧镜像不会自动删除，需要按实际磁盘空间定期管理。

### 常用ECS管理命令

在ECS终端使用完整路径：

```bash
release=$(readlink -f /opt/airontology/current)
docker compose --project-name airontology --project-directory "$release" \
  --env-file /opt/airontology/shared/.env --env-file "$release/images.env" \
  -f "$release/compose.ecs.yaml" logs --tail=100 app
```

## 8. 首次启动修复

根据上一版GitHub Actions真实容器日志，修复Fuseki首次启动时/data/database目录不存在的问题。镜像入口现在会先创建目录，再启动Fuseki；同时兼容旧的空数据卷。

## 9. 验证范围

部署脚本提供4项假Docker流程测试，覆盖正常发布、失败恢复、架构不匹配和首次发布；它们不代替真实ECS测试。真正部署需要配置ECS_HOST、ECS_USER、ECS_KNOWN_HOSTS及一种认证Secret后手动运行，当前没有执行或宣称完成服务器部署。


## 10. 小规格ECS启动超时

已根据真实部署日志修正ECS启动等待预算：Compose部署及恢复等待上限由180秒调整为900秒。Fuseki健康检查提供300秒启动宽限期，再进行重试；小规格或繁忙服务器无需在3分钟时被提前判定失败。

Fuseki默认JVM参数改为 `-Xms64m -Xmx512m -XX:ActiveProcessorCount=2`，容器内存上限默认1g，可在shared/.env通过FUSEKI_JVM_ARGS与FUSEKI_MEMORY_LIMIT覆盖。4GB是旧配置的最大堆上限，不表示故障时实际已用4GB，也不能据此认定OOM。

失败日志现在包含内存、负载、磁盘、容器资源和各服务健康检查结果。若900秒仍无法就绪，应根据实际资源负载、健康检查日志和容器日志继续判断，不能仅无限延长等待时间。

修复后从Actions页面新建一次main分支的Run workflow；旧任务的Re-run jobs仍使用旧提交，不会采用新配置。部署未成功之前，不会生成current成功发布链接。


## TDB2 磁盘维护

持续更新与删除 RDF 历史会让 TDB2 的底层文件继续增长。记录数量上限不等于磁盘空间上限。部署流程安装 `airontology-maintenance.timer`，每五分钟检查一次；数据目录超过 256MiB 时通过 Fuseki 管理 API 执行在线压缩，并等待任务成功。只有压缩成功后才由 Fuseki 删除旧存储代，不删除逻辑 RDF 事实。维护与部署共享锁，避免并行操作。

- 查看状态：`systemctl status airontology-maintenance.timer`
- 查看结果：`journalctl -u airontology-maintenance.service -n 30`
- 立即验证：`python3 /opt/airontology/shared/maintain-ecs.py /opt/airontology --force`

仍需监控系统盘剩余容量；定时压缩不能替代备份。参考：https://jena.apache.org/documentation/fuseki2/fuseki-server-protocol.html

## 配置 DeepSeek 解读

将 DeepSeek API 密钥保存为仓库 Actions Secret `DEEPSEEK_API_KEY`，然后在 main 分支手动运行 **ECS maintenance** 并选择 `configure`。该流程通过已校验的 SSH 连接把密钥写入 ECS 的 `shared/.env`，权限设为 600，只重启应用容器，并检查 `/api/agent/questions` 返回 `llm_configured: true`。密钥不进入代码、构建镜像或 Actions 日志。后续普通部署继续沿用此持久配置；更换密钥时更新 Secret 并重新运行配置流程。

`llm_configured: true` 只表示服务已读取密钥。还需在态势问答中实际提问，并看到 **DeepSeek 流式解读**，才能确认远端 API 调用成功。若出现解读错误，规则卡片仍会保留，可根据 DeepSeek 账户余额、密钥状态和 ECS 出站网络排查。

## 日常工作流与运维

- 新功能推送开发分支，向 `main` 创建 PR 后自动运行 **Verify AirOntology**；该工作流也可手动运行。
- 合并后，手动运行 **Deploy AirOntology to ECS**，选择 `main`、服务器架构和是否启动模拟器。部署仍会独立测试并验证即将上传的镜像。
- 排障时手动运行 **ECS maintenance**：`diagnose` 为只读检查；`recover` 会重启服务并暂停模拟器；`resume` 将模拟间隔设为 15 秒并恢复模拟器；`configure` 使用既有 Secret 配置 DeepSeek。
- 运维与部署共享并发锁，避免互相覆盖。

## 10. 部署速度与耗时排查

2026-11-07 的部署 #18（`fa45580`）成功，用时 4 分 53 秒。主要步骤：后端依赖与测试 109 秒、前端检查 14 秒、镜像构建和完整服务验证 46 秒、打包 12 秒、SSH 上传及 ECS 发布 103 秒。这是优化前的实测基线，不是部署时间承诺。

工作流的提速措施：

- 后端测试使用两个独立进程执行（`pytest -n 2`），保留全部用例；仅在 GitHub runner 并行，不增加 ECS 的负担。本机仍可使用普通 `pytest` 串行运行。
- pip 与 npm 下载缓存减少重复下载；Docker Buildx 使用 GitHub Actions 缓存，分别保存应用和 Fuseki 镜像层，并按 CPU 架构隔离。缓存缺失时正常重建，缓存导出失败不阻断发布。默认分支的缓存可供 PR 读取，PR 的缓存不会直接成为主分支部署缓存。
- 前端单元测试仍执行；生产打包只在 Docker 中执行一次。完整服务验证通过 `--no-build` 使用刚构建的镜像，之后上传同一批镜像。
- runner 有 `pigz` 时以两个线程压缩传输包，否则使用原有 `gzip`；ECS 解包方式不变。
- `Summary` 增加传输包字节数、SSH 准备与上传秒数、ECS 校验/导入/备份/切换秒数。构建缓存命中可在 **Build images with cache** 日志中查看 `CACHED`。

第一次使用新流程需要建立缓存，未必更快；应比较后续缓存命中的多次运行。具体步骤的耗时仍在任务详情中显示。缓存机制参考 [Docker 官方说明](https://docs.docker.com/build/cache/backends/gha/)。

本版仍完整上传三类镜像，保留一致性数据库备份、健康检查、部署锁和失败恢复。若上传持续占主要时间，再评估镜像仓库分层拉取；若 ECS 备份或启动慢，优先检查数据库体积、磁盘和内存。不要通过跳过备份或缩短健康等待来制造“更快”的结果。
