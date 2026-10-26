#!/usr/bin/env bash
# 在 GitHub runner 上运行；密钥只通过私有临时文件和已校验的 SSH 连接传输。
set -Eeuo pipefail
umask 077
: "${ECS_HOST:?缺少 ECS_HOST}"
: "${ECS_USER:?缺少 ECS_USER}"
: "${ECS_KNOWN_HOSTS:?缺少 ECS_KNOWN_HOSTS}"
: "${DEEPSEEK_API_KEY:?缺少 DEEPSEEK_API_KEY}"
[[ -n "${ECS_SSH_KEY:-}" || -n "${ECS_PASSWORD:-}" ]] || { echo '缺少 ECS SSH 认证'; exit 1; }
[[ "$DEEPSEEK_API_KEY" =~ ^sk-[A-Za-z0-9_-]+$ ]] || { echo 'DeepSeek 密钥格式无效'; exit 1; }
[[ "$ECS_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || exit 1
[[ "$ECS_USER" =~ ^[a-z_][a-z0-9_-]*$ ]] || exit 1
ECS_PORT=${ECS_PORT:-22}
ECS_DEPLOY_PATH=${ECS_DEPLOY_PATH:-/opt/airontology}
[[ "$ECS_PORT" =~ ^[0-9]+$ ]] && (( ECS_PORT >= 1 && ECS_PORT <= 65535 )) || exit 1
[[ "$ECS_DEPLOY_PATH" =~ ^/[A-Za-z0-9/_-]+$ && "$ECS_DEPLOY_PATH" != / ]] || exit 1
[[ "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ ]] || exit 1

KEY_DIR=$(mktemp -d)
REMOTE_UPLOADED=false
cleanup() {
  if [[ "$REMOTE_UPLOADED" == true ]]; then
    printf -v REMOVE 'rm -f %q; rmdir %q 2>/dev/null || true' "$REMOTE_DIR/deepseek.key" "$REMOTE_DIR"
    "${AUTH[@]}" ssh "${SSH_OPTIONS[@]}" -p "$ECS_PORT" "$REMOTE" "$REMOVE" >/dev/null 2>&1 || true
  fi
  rm -rf "$KEY_DIR"
}
trap cleanup EXIT
chmod 700 "$KEY_DIR"
printf '%s\n' "$ECS_KNOWN_HOSTS" > "$KEY_DIR/known_hosts"
printf '%s\n' "$DEEPSEEK_API_KEY" > "$KEY_DIR/deepseek.key"
chmod 600 "$KEY_DIR/known_hosts" "$KEY_DIR/deepseek.key"
SSH_OPTIONS=(-o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KEY_DIR/known_hosts" -o ConnectTimeout=20 -o ServerAliveInterval=20 -o ServerAliveCountMax=6)
AUTH=()
if [[ -n "${ECS_SSH_KEY:-}" ]]; then
  printf '%s\n' "$ECS_SSH_KEY" > "$KEY_DIR/ssh.key"
  chmod 600 "$KEY_DIR/ssh.key"
  SSH_OPTIONS+=(-i "$KEY_DIR/ssh.key" -o BatchMode=yes -o IdentitiesOnly=yes)
else
  command -v sshpass >/dev/null || { echo '密码模式需要 sshpass'; exit 1; }
  export SSHPASS="$ECS_PASSWORD"
  AUTH=(sshpass -e)
  SSH_OPTIONS+=(-o BatchMode=no -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive -o NumberOfPasswordPrompts=1)
fi

REMOTE="$ECS_USER@$ECS_HOST"
REMOTE_DIR="$ECS_DEPLOY_PATH/incoming/deepseek-$GITHUB_RUN_ID"
printf -v PREPARE 'umask 077; mkdir -p %q' "$REMOTE_DIR"
"${AUTH[@]}" ssh "${SSH_OPTIONS[@]}" -p "$ECS_PORT" "$REMOTE" "$PREPARE"
"${AUTH[@]}" scp "${SSH_OPTIONS[@]}" -P "$ECS_PORT" "$KEY_DIR/deepseek.key" "$REMOTE:$REMOTE_DIR/deepseek.key"
REMOTE_UPLOADED=true
printf -v COMMAND 'bash -s -- %q %q' "$ECS_DEPLOY_PATH" "$REMOTE_DIR/deepseek.key"
"${AUTH[@]}" ssh "${SSH_OPTIONS[@]}" -p "$ECS_PORT" "$REMOTE" "$COMMAND" < scripts/apply-deepseek-ecs.sh
