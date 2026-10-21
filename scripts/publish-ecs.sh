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
printf -v PREPARE 'umask 077; mkdir -p %q' "$ECS_DEPLOY_PATH/incoming/$RELEASE_ID"
"${AUTH[@]}" ssh "${SSH_OPTIONS[@]}" -p "$ECS_PORT" "$REMOTE" "$PREPARE"
"${AUTH[@]}" scp "${SSH_OPTIONS[@]}" -P "$ECS_PORT" bundle.tar "$REMOTE:$ECS_DEPLOY_PATH/incoming/$RELEASE_ID/bundle.tar"
BUNDLE_SHA=$(sha256sum bundle.tar | awk '{print $1}')
printf -v COMMAND 'bash -s -- %q %q %q %q %q' "$ECS_DEPLOY_PATH" "$RELEASE_ID" "$BUNDLE_SHA" "$TARGET_ARCH" "$RUN_SIMULATOR"
"${AUTH[@]}" ssh "${SSH_OPTIONS[@]}" -p "$ECS_PORT" "$REMOTE" "$COMMAND" < scripts/deploy-ecs.sh
