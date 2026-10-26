#!/usr/bin/env bash
# macOS / Linux: ./start-local.sh [start|stop|status|logs]
set -Eeuo pipefail
cd "$(dirname "$0")"

action="${1:-start}"
case "$action" in
  start|stop|status|logs) ;;
  -h|--help|help)
    printf '用法：./start-local.sh [start|stop|status|logs]\n'
    printf 'start 构建并启动全部服务及模拟器；stop 停止但保留数据卷。\n'
    exit 0 ;;
  *) printf '未知操作：%s\n' "$action" >&2; exit 2 ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  printf '未找到 docker 命令，请先安装并启动 Docker Desktop / Docker Engine。\n' >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  printf '未找到 Docker Compose 插件，请更新 Docker Desktop / Docker Engine。\n' >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  if [[ "$(uname -s)" == Darwin ]] && command -v open >/dev/null 2>&1; then
    printf 'Docker Desktop 尚未启动，正在尝试打开并等待 Docker 引擎…\n'
    open -a Docker || true
  else
    printf 'Docker 引擎尚未启动，请启动 Docker 后重新执行。\n' >&2
    exit 1
  fi
  ready=false
  for ((attempt=1; attempt<=60; attempt++)); do
    if docker info >/dev/null 2>&1; then ready=true; break; fi
    if (( attempt % 10 == 0 )); then printf '仍在等待 Docker（%s/60）…\n' "$attempt"; fi
    sleep 3
  done
  if [[ "$ready" != true ]]; then
    printf '等待 Docker 超时，请在 Docker Desktop 中检查引擎状态后重试。\n' >&2
    exit 1
  fi
fi

case "$action" in
  stop)
    docker compose --profile demo down
    printf '服务已停止；Fuseki 与 MQTT 数据卷已保留。\n'
    exit 0 ;;
  status) docker compose --profile demo ps -a; exit 0 ;;
  logs) docker compose --profile demo logs --tail=100 -f app simulator; exit 0 ;;
esac

if [[ ! -f .env ]]; then
  cp .env.example .env
  printf '已从 .env.example 建立本地 .env；以后不会覆盖你的配置。\n'
fi

show_failure() {
  printf '\n启动失败。请查看下面的容器状态与最近日志；若是镜像拉取超时，检查 Docker Desktop 的网络代理。\n' >&2
  docker compose --profile demo ps -a >&2 || true
  docker compose --profile demo logs --tail=60 app fuseki mqtt simulator >&2 || true
}
trap show_failure ERR

printf '正在构建本地镜像…\n'
docker compose build
printf '正在启动 MQTT、Fuseki 和 Web 服务（等待健康检查）…\n'
docker compose up -d --wait --wait-timeout 300
printf '正在启动演示模拟器…\n'
docker compose --profile demo up -d --force-recreate simulator
docker compose --profile demo ps

binding="$(docker compose port app 8000)"
port="${binding##*:}"
if [[ ! "$port" =~ ^[0-9]+$ ]]; then port=8092; fi
url="http://localhost:${port}"
printf '\n启动完成：%s\n' "$url"
printf '查看日志：./start-local.sh logs；停止并保留数据：./start-local.sh stop\n'
if [[ "$(uname -s)" == Darwin ]] && command -v open >/dev/null 2>&1; then
  open "$url" || true
fi
