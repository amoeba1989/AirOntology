#!/usr/bin/env bash
# 在ECS上由SSH运行。参数：部署根目录、发布编号、包SHA256、架构、是否启动模拟器。
set -Eeuo pipefail
umask 077
ROOT=${1:?缺少部署目录}
RELEASE_ID=${2:?缺少发布编号}
BUNDLE_SHA=${3:?缺少校验值}
ARCH=${4:?缺少架构}
DEMO=${5:-true}
[[ "$ROOT" =~ ^/[A-Za-z0-9/_-]+$ && "$ROOT" != / ]] || { echo '部署路径不合法'; exit 1; }
[[ "$RELEASE_ID" =~ ^[a-f0-9]{40}-[0-9]+-[0-9]+$ ]] || exit 1
[[ "$BUNDLE_SHA" =~ ^[a-f0-9]{64}$ ]] || exit 1
[[ "$ARCH" == amd64 || "$ARCH" == arm64 ]] || exit 1
[[ "$DEMO" == true || "$DEMO" == false ]] || exit 1
echo "[$(date -Is)] 开始部署，先检查内存与磁盘"
free -h || true
uptime || true
AVAILABLE_KB=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
if [[ -n "$AVAILABLE_KB" ]] && (( AVAILABLE_KB < 524288 )); then
  echo '可用内存不足512MiB，暂停部署。请先停止其他业务服务，再重新运行；避免镜像导入拖垮ECS。'
  exit 1
fi
command -v docker >/dev/null
command -v flock >/dev/null
docker compose version >/dev/null
SERVER_ARCH=$(docker info --format '{{.Architecture}}')
case "$SERVER_ARCH" in x86_64) SERVER_ARCH=amd64;; aarch64) SERVER_ARCH=arm64;; esac
[[ "$SERVER_ARCH" == "$ARCH" ]] || { echo "架构不一致：镜像=$ARCH ECS=$SERVER_ARCH"; exit 1; }
mkdir -p "$ROOT/releases" "$ROOT/shared" "$ROOT/backups"
exec 9>"$ROOT/deploy.lock"
flock -n 9 || { echo '另一部署正在运行'; exit 1; }
RELEASE="$ROOT/releases/$RELEASE_ID"
[[ ! -e "$RELEASE" ]] || { echo '发布目录已存在'; exit 1; }
PACKAGE="$ROOT/incoming/$RELEASE_ID/bundle.tar"
printf '%s  %s\n' "$BUNDLE_SHA" "$PACKAGE" | sha256sum -c -
mkdir "$RELEASE"
echo "[$(date -Is)] 上传校验通过，开始解包"
tar -xf "$PACKAGE" -C "$RELEASE" --no-same-owner
[[ -f "$RELEASE/images.env" && -f "$RELEASE/compose.ecs.yaml" && -f "$RELEASE/images.tar.gz" ]]
if [[ ! -f "$ROOT/shared/.env" ]]; then
  if [[ -f "$ROOT/.env" ]]; then cp "$ROOT/.env" "$ROOT/shared/.env";
  else cp "$RELEASE/.env.example" "$ROOT/shared/.env"; fi
  chmod 600 "$ROOT/shared/.env"
fi
# 单独的image env不可由用户.env覆盖，确保部署的就是通过测试的镜像版本。
compose_at() {
  local directory=$1; shift
  docker compose --project-name airontology --project-directory "$directory" \
    --env-file "$ROOT/shared/.env" --env-file "$directory/images.env" -f "$directory/compose.ecs.yaml" "$@"
}
echo "[$(date -Is)] 解包完成，验证部署配置"
compose_at "$RELEASE" config --quiet
# 导入失败不触碰正在运行的服务。
echo "[$(date -Is)] 开始导入镜像；此阶段消耗内存和磁盘IO"
docker load -i "$RELEASE/images.tar.gz"
echo "[$(date -Is)] 镜像导入完成"
[[ ! -e "$ROOT/current" || -L "$ROOT/current" ]] || { echo 'current必须为发布软链接'; exit 1; }
PREVIOUS=''
if [[ -L "$ROOT/current" ]]; then PREVIOUS=$(readlink -f "$ROOT/current"); fi
RESTORE_NEEDED=false
recover() {
  local code=$?
  trap - ERR
  if [[ "$RESTORE_NEEDED" == true ]]; then
    echo '部署失败，打印候选服务日志并尝试恢复上一发布（不回滚数据库）'
    compose_at "$RELEASE" --profile demo ps -a || true
    docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' || true
    for service in mqtt fuseki app; do
      container=$(compose_at "$RELEASE" ps -aq "$service")
      if [[ -n "$container" ]]; then
        docker inspect --format '{{json .State.Health}}' "$container" || true
      fi
    done
    compose_at "$RELEASE" --profile demo logs --tail=100 mqtt app fuseki || true
    if [[ -n "$PREVIOUS" && -f "$PREVIOUS/compose.ecs.yaml" ]]; then
      compose_at "$PREVIOUS" up -d --no-build --pull never --wait --wait-timeout 900 || true
      if [[ -f "$PREVIOUS/demo.enabled" ]]; then
        compose_at "$PREVIOUS" --profile demo up -d --no-build --pull never simulator || true
      fi
    else
      compose_at "$RELEASE" --profile demo stop app simulator || true
      echo '没有受此工作流管理的上一发布，请根据日志处理；数据库备份已保留。'
    fi
  fi
  exit "$code"
}
trap recover ERR
echo 'ECS资源概况：'
free -h || true
uptime || true
df -h "$ROOT" || true
RESTORE_NEEDED=true
# 保留原airontology项目和命名数据卷，先停写再备份TDB2。
compose_at "$RELEASE" --profile demo stop simulator app fuseki
BACKUP="$ROOT/backups/$RELEASE_ID"
mkdir "$BACKUP"
cp "$ROOT/shared/.env" "$BACKUP/runtime.env"
chmod 600 "$BACKUP/runtime.env"
if [[ -n "$(compose_at "$RELEASE" ps -aq fuseki)" ]]; then
  compose_at "$RELEASE" cp fuseki:/data "$BACKUP/fuseki-data"
  echo "已保存停止写入后的Fuseki备份：$BACKUP/fuseki-data"
fi
echo "[$(date -Is)] 开始启动服务并等待健康检查"
compose_at "$RELEASE" up -d --no-build --pull never --wait --wait-timeout 900
# 在应用容器内检查JSON健康状态，不依赖ECS公网访问应用端口。
compose_at "$RELEASE" exec -T app python -c \
  'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/health")); assert d["status"]=="ok",d; print("应用和依赖健康检查通过")' </dev/null
if [[ "$DEMO" == true ]]; then
  compose_at "$RELEASE" --profile demo up -d --no-build --pull never simulator
  touch "$RELEASE/demo.enabled"
fi
ln -sfn "$RELEASE" "$ROOT/current.next"
mv -Tf "$ROOT/current.next" "$ROOT/current"
RESTORE_NEEDED=false
trap - ERR
# 镜像已导入，只清理本次传输包；保留发布配置、备份及镜像用于恢复。
rm -f "$RELEASE/images.tar.gz" "$PACKAGE"
printf '部署成功：%s\n发布目录：%s\n' "$RELEASE_ID" "$RELEASE"
compose_at "$RELEASE" ps
