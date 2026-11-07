#!/usr/bin/env bash
# 在GitHub runner执行；私钥与known_hosts只写入临时目录。
set -Eeuo pipefail
: "${ECS_HOST:?请配置ECS_HOST Secret}"
: "${ECS_USER:?请配置ECS_USER Secret}"
if [[ -z "${ECS_SSH_KEY:-}" && -z "${ECS_PASSWORD:-}" ]]; then
  echo '请配置ECS_SSH_KEY或ECS_PASSWORD Secret'; exit 1
fi
: "${ECS_KNOWN_HOSTS:?请配置ECS_KNOWN_HOSTS Secret}"
: "${RELEASE_ID:?}" "${TARGET_ARCH:?}" "${RUN_SIMULATOR:?}"
ECS_PORT=${ECS_PORT:-22}
ECS_DEPLOY_PATH=${ECS_DEPLOY_PATH:-/opt/airontology}
[[ "$ECS_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || { echo 'ECS_HOST请填IPv4或域名，不含协议'; exit 1; }
[[ "$ECS_USER" =~ ^[a-z_][a-z0-9_-]*$ && "$ECS_PORT" =~ ^[0-9]+$ ]] || exit 1
(( ECS_PORT >= 1 && ECS_PORT <= 65535 )) || exit 1
[[ "$ECS_DEPLOY_PATH" =~ ^/[A-Za-z0-9/_-]+$ && "$ECS_DEPLOY_PATH" != / ]] || exit 1
[[ "$RELEASE_ID" =~ ^[a-f0-9]{40}-[0-9]+-[0-9]+$ ]] || exit 1
KEY_DIR=$(mktemp -d)
trap 'rm -rf "$KEY_DIR"' EXIT
chmod 700 "$KEY_DIR"
printf '%s\n' "$ECS_KNOWN_HOSTS" > "$KEY_DIR/known_hosts"
chmod 600 "$KEY_DIR/known_hosts"
SSH_OPTIONS=(-o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KEY_DIR/known_hosts" -o ConnectTimeout=20 -o ServerAliveInterval=20 -o ServerAliveCountMax=6)
AUTH=()
if [[ -n "${ECS_SSH_KEY:-}" ]]; then
  printf '%s\n' "$ECS_SSH_KEY" > "$KEY_DIR/key"
  chmod 600 "$KEY_DIR/key"
  SSH_OPTIONS+=(-i "$KEY_DIR/key" -o BatchMode=yes -o IdentitiesOnly=yes)
else
  command -v sshpass >/dev/null || { echo '密码模式需要sshpass'; exit 1; }
  export SSHPASS="$ECS_PASSWORD"
  AUTH=(sshpass -e)
  SSH_OPTIONS+=(-o BatchMode=no -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive -o NumberOfPasswordPrompts=1)
fi
REMOTE="$ECS_USER@$ECS_HOST"
BUNDLE_BYTES=$(wc -c < bundle.tar | tr -d '[:space:]')
echo "传输包大小：$BUNDLE_BYTES bytes"
UPLOAD_STARTED=$SECONDS
printf -v PREPARE 'umask 077; mkdir -p %q' "$ECS_DEPLOY_PATH/incoming/$RELEASE_ID"
"${AUTH[@]}" ssh "${SSH_OPTIONS[@]}" -p "$ECS_PORT" "$REMOTE" "$PREPARE"
"${AUTH[@]}" scp "${SSH_OPTIONS[@]}" -P "$ECS_PORT" bundle.tar "$REMOTE:$ECS_DEPLOY_PATH/incoming/$RELEASE_ID/bundle.tar"
UPLOAD_SECONDS=$((SECONDS - UPLOAD_STARTED))
echo "SSH准备与上传耗时：${UPLOAD_SECONDS}s"
BUNDLE_SHA=$(sha256sum bundle.tar | awk '{print $1}')
printf -v COMMAND 'bash -s -- %q %q %q %q %q' "$ECS_DEPLOY_PATH" "$RELEASE_ID" "$BUNDLE_SHA" "$TARGET_ARCH" "$RUN_SIMULATOR"
DEPLOY_STARTED=$SECONDS
"${AUTH[@]}" ssh "${SSH_OPTIONS[@]}" -p "$ECS_PORT" "$REMOTE" "$COMMAND" < scripts/deploy-ecs.sh
DEPLOY_SECONDS=$((SECONDS - DEPLOY_STARTED))
echo "ECS校验、导入、备份与切换耗时：${DEPLOY_SECONDS}s"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    printf '### ECS 发布耗时\n\n'
    printf '| 项目 | 实测值 |\n| --- | ---: |\n'
    printf '| 传输包 | %s bytes |\n' "$BUNDLE_BYTES"
    printf '| SSH准备与上传 | %s 秒 |\n' "$UPLOAD_SECONDS"
    printf '| ECS校验、导入、备份与切换 | %s 秒 |\n' "$DEPLOY_SECONDS"
    printf '\n构建缓存命中情况见 Build images with cache；首次运行需要建立缓存。\n'
  } >> "$GITHUB_STEP_SUMMARY"
fi
