#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_CONTAINER_NAME="${APP_CONTAINER_NAME:-helidata-ai-gateway}"
APP_IMAGE='helidata-ai-gateway:v1.0.2-offline'
INITIAL_FILE=''
cleanup() { unset PASSWORD CONFIRM_PASSWORD; }
trap cleanup EXIT
fail() { printf '错误：%s\n' "$*" >&2; exit 1; }
for tool in docker sha256sum realpath find flock; do command -v "$tool" >/dev/null 2>&1 || fail "缺少命令 $tool，请先安装部署依赖。"; done
docker info >/dev/null 2>&1 || fail 'Docker 未启动或当前用户无操作权限。'
[[ "$(uname -m)" == x86_64 ]] || fail '此部署包适用于 Linux amd64（x86_64）。'
[[ "$APP_CONTAINER_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || fail '容器名称无效。'
if docker container inspect "$APP_CONTAINER_NAME" >/dev/null 2>&1; then fail '应用容器已存在；已部署环境请使用 start-offline.sh。'; fi
printf '\n合力数据AI网关 v1.0.2 离线部署\n'
while true; do
  read -r -p '请输入宿主机数据目录 [/opt/AIGateway/data]: ' DATA_DIR || fail '输入已结束。'
  DATA_DIR="${DATA_DIR:-/opt/AIGateway/data}"
  [[ "$DATA_DIR" == /* && "$DATA_DIR" != *:* && "$DATA_DIR" != *$'\n'* ]] || { printf '请填写绝对路径，且不能包含冒号。\n'; continue; }
  DATA_DIR="$(realpath -m -- "$DATA_DIR")"
  [[ "$DATA_DIR" != / && "$DATA_DIR" != "$ROOT" ]] || { printf '该目录不能用作数据目录。\n'; continue; }
  if [[ -e "$DATA_DIR" ]] && { [[ ! -d "$DATA_DIR" ]] || [[ -n "$(find "$DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; }; then
    printf '目录不是空目录，请选择新的空数据目录；现有数据不会覆盖。\n'; continue
  fi
  break
done
while true; do
  read -r -p '请输入管理员用户名 [admin]: ' ADMIN_USER || fail '输入已结束。'
  ADMIN_USER="${ADMIN_USER:-admin}"
  [[ "$ADMIN_USER" =~ ^[a-zA-Z0-9_.-]{3,80}$ ]] && break
  printf '用户名须为 3 至 80 位字母、数字、下划线、点或短横线。\n'
done
printf '密码须为 12 至 128 位，包含大小写字母、数字、符号中的至少三类。\n'
while true; do
  read -r -s -p '请输入管理员密码: ' PASSWORD || fail '输入已结束。'; printf '\n'
  read -r -s -p '请再次输入管理员密码: ' CONFIRM_PASSWORD || fail '输入已结束。'; printf '\n'
  [[ "$PASSWORD" == "$CONFIRM_PASSWORD" ]] || { printf '两次密码不一致，请重新输入。\n'; continue; }
  classes=0
  [[ "$PASSWORD" =~ [[:lower:]] ]] && classes=$((classes+1))
  [[ "$PASSWORD" =~ [[:upper:]] ]] && classes=$((classes+1))
  [[ "$PASSWORD" =~ [[:digit:]] ]] && classes=$((classes+1))
  [[ "$PASSWORD" =~ [^[:alnum:]] ]] && classes=$((classes+1))
  (( ${#PASSWORD}>=12 && ${#PASSWORD}<=128 && classes>=3 )) && break
  printf '密码强度不足，请重新输入。\n'
done
while true; do
  read -r -p '请输入应用端口 [18080]: ' APP_PORT || fail '输入已结束。'
  APP_PORT="${APP_PORT:-18080}"
  if [[ "$APP_PORT" =~ ^[1-9][0-9]{0,4}$ ]] && (( APP_PORT<=65535 )); then
    if command -v ss >/dev/null 2>&1 && [[ -n "$(ss -H -ltn "sport = :$APP_PORT")" ]]; then printf '端口已被占用，请选择其他端口。\n'; continue; fi
    break
  fi
  printf '端口须为 1 至 65535。\n'
done
printf '\n部署目录：%s\n管理员：%s\n应用端口：%s\n正在校验离线包…\n' "$DATA_DIR" "$ADMIN_USER" "$APP_PORT"
(cd "$ROOT" && sha256sum --check SHA256SUMS) || fail '文件校验失败，请重新获取完整部署包。'
docker load --input "$ROOT/images/helidata-ai-gateway-v1.0.2-image.tar.gz"
EXPECTED_ID="$(cat "$ROOT/image-id.txt")"
[[ "$EXPECTED_ID" =~ ^sha256:[a-f0-9]{64}$ ]] || fail '镜像清单格式无效。'
[[ "$(docker image inspect "$APP_IMAGE" --format '{{.Id}}')" == "$EXPECTED_ID" ]] || fail '加载的镜像与离线包不一致。'
mkdir -p -- "$DATA_DIR"
exec 9>"$DATA_DIR/.offline-deployment.lock"
flock -n 9 || fail '该目录正在部署，请稍后重试。'
[[ -z "$(find "$DATA_DIR" -mindepth 1 -maxdepth 1 ! -name .offline-deployment.lock -print -quit)" ]] || fail '数据目录在输入期间已发生变化，请选择空目录。'
mkdir -p -- "$DATA_DIR/config"
INITIAL_FILE="$DATA_DIR/config/initial-admin.json"
# Credentials are passed on stdin. Docker metadata and configuration contain no plaintext password.
printf '%s\n%s' "$ADMIN_USER" "$PASSWORD" | docker run --rm -i --pull=never --network none --entrypoint python "$APP_IMAGE" -c 'import json,sys; from app.services.initial_admin import encode_credentials; raw=sys.stdin.read(); username,password=raw.split("\n",1); print(json.dumps(encode_credentials({"username":username,"password":password})))' > "$INITIAL_FILE"
chmod 600 "$INITIAL_FILE"
export APP_CONTAINER_NAME APP_IMAGE APP_PORT APP_DATA_DIR="$DATA_DIR"
CONFIG_TEMP="$(mktemp "$ROOT/.deployment.env.XXXXXX")"
for key in APP_CONTAINER_NAME APP_IMAGE APP_PORT APP_DATA_DIR; do printf 'export %s=%q\n' "$key" "${!key}" >> "$CONFIG_TEMP"; done
chmod 600 "$CONFIG_TEMP";mv -f -- "$CONFIG_TEMP" "$ROOT/deployment.env"
run_args=(run -d --pull=never --name "$APP_CONTAINER_NAME" -p "$APP_PORT:80" -v "$DATA_DIR:/data:Z" --restart unless-stopped)
if [[ -n "${APP_DOCKER_NETWORK:-}" ]]; then run_args+=(--network "$APP_DOCKER_NETWORK"); fi
docker "${run_args[@]}" "$APP_IMAGE" >/dev/null
export APP_CONTAINER_NAME APP_IMAGE APP_PORT APP_DATA_DIR="$DATA_DIR"
export APP_START_TIMEOUT="${APP_START_TIMEOUT:-300}"
source "$ROOT/scripts/application.sh"
wait_ready
[[ ! -e "$INITIAL_FILE" ]] || fail '管理员初始化未完成，请检查受保护的启动状态。'
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')";HOST_IP="${HOST_IP:-127.0.0.1}"
printf '\n部署成功！\n登录地址：http://%s:%s/login\n管理员用户名：%s\n管理员密码：使用刚才输入的密码（不回显）\n数据目录：%s\n启动：./start-offline.sh\n停止：./stop-offline.sh\n' "$HOST_IP" "$APP_PORT" "$ADMIN_USER" "$DATA_DIR"
