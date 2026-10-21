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
