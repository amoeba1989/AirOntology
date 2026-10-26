#!/usr/bin/env bash
# 在 ECS 上运行；不把密钥写入命令行、日志或发布目录。
set -Eeuo pipefail
umask 077
ROOT=${1:?缺少部署目录}
KEY_FILE=${2:?缺少密钥文件}
[[ "$ROOT" =~ ^/[A-Za-z0-9/_-]+$ && "$ROOT" != / ]] || exit 1
[[ "$KEY_FILE" =~ ^"$ROOT"/incoming/deepseek-[0-9]+/deepseek\.key$ ]] || exit 1
[[ -f "$KEY_FILE" && ! -L "$KEY_FILE" ]] || exit 1
ENV_FILE="$ROOT/shared/.env"
RELEASE=$(readlink -f "$ROOT/current")
[[ -f "$ENV_FILE" && -f "$RELEASE/compose.ecs.yaml" && -f "$RELEASE/images.env" ]] || exit 1
exec 9>"$ROOT/deploy.lock"
flock -n 9 || { echo '另一部署正在运行'; exit 1; }
BACKUP=$(mktemp "$ROOT/shared/.env.backup.XXXXXX")
cp -p "$ENV_FILE" "$BACKUP"
cleanup() { rm -f "$KEY_FILE" "$BACKUP"; rmdir "$(dirname "$KEY_FILE")" 2>/dev/null || true; }
trap cleanup EXIT

python3 - "$ENV_FILE" "$KEY_FILE" <<'PY'
import os, pathlib, re, sys, tempfile
env_file, key_file = map(pathlib.Path, sys.argv[1:])
key = key_file.read_text().strip()
if not re.fullmatch(r'sk-[A-Za-z0-9_-]+', key):
    raise SystemExit('DeepSeek 密钥格式无效')
lines = [line for line in env_file.read_text().splitlines() if not re.match(r'^\s*DEEPSEEK_API_KEY\s*=', line)]
lines.append('DEEPSEEK_API_KEY=' + key)
fd, name = tempfile.mkstemp(prefix='.env.next.', dir=env_file.parent)
try:
    with os.fdopen(fd, 'w') as stream:
        stream.write('\n'.join(lines) + '\n')
    os.chmod(name, 0o600)
    os.replace(name, env_file)
finally:
    if os.path.exists(name): os.unlink(name)
PY

compose() {
  docker compose --project-name airontology --project-directory "$RELEASE" \
    --env-file "$ENV_FILE" --env-file "$RELEASE/images.env" -f "$RELEASE/compose.ecs.yaml" "$@"
}
if ! compose up -d --no-deps --force-recreate --wait --wait-timeout 600 app || \
   ! compose exec -T app python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/agent/questions")); assert d["llm_configured"] is True' </dev/null; then
  cp -p "$BACKUP" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  compose up -d --no-deps --force-recreate --wait --wait-timeout 600 app || true
  echo 'DeepSeek 配置验证失败，已尝试恢复原配置'
  exit 1
fi
echo 'DeepSeek 密钥已写入 ECS 私有配置，应用健康且已识别配置'
