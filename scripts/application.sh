#!/usr/bin/env bash
# Shared host-side Docker controls. Source from start.sh or stop.sh.
set -Eeuo pipefail
APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
APP_CONTAINER_NAME="${APP_CONTAINER_NAME:-helidata-ai-gateway}"
APP_IMAGE="${APP_IMAGE:-helidata-ai-gateway:v1.0.6}"
APP_PORT="${APP_PORT:-18080}"
APP_DATA_DIR="${APP_DATA_DIR:-$APP_ROOT/data}"
APP_START_TIMEOUT="${APP_START_TIMEOUT:-180}"
APP_STOP_TIMEOUT="${APP_STOP_TIMEOUT:-90}"
fail() { printf '错误：%s\n' "$*" >&2; exit 1; }
check_environment() {
  local operation="${1:-all}"
  command -v docker >/dev/null 2>&1 || fail '未安装 Docker，请先完成 README 中的部署准备。'
  command -v realpath >/dev/null 2>&1 || fail '缺少 realpath，请安装 coreutils。'
  [[ "$APP_CONTAINER_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || fail '容器名称格式无效。'
  [[ "$APP_PORT" =~ ^[1-9][0-9]{0,4}$ ]] && (( APP_PORT <= 65535 )) || fail '端口须为 1 至 65535。'
  if [[ "$operation" != stop ]]; then
    [[ "$APP_START_TIMEOUT" =~ ^[1-9][0-9]{0,3}$ ]] && (( APP_START_TIMEOUT <= 3600 )) || fail '启动超时须为 1 至 3600 秒。'
  fi
  if [[ "$operation" != start ]]; then
    [[ "$APP_STOP_TIMEOUT" =~ ^[1-9][0-9]{0,3}$ ]] && (( APP_STOP_TIMEOUT <= 3600 )) || fail '停止超时须为 1 至 3600 秒。'
  fi
  [[ "$APP_DATA_DIR" != *:* && "$APP_DATA_DIR" != *$'\n'* && "$APP_DATA_DIR" != *$'\r'* ]] || fail '数据目录不能包含冒号或换行。'
  APP_DATA_DIR="$(realpath -m -- "$APP_DATA_DIR")"
  [[ "$APP_DATA_DIR" != / ]] || fail '数据目录不能为文件系统根目录。'
  [[ ! -e "$APP_DATA_DIR" || -d "$APP_DATA_DIR" ]] || fail '数据路径已存在且不是目录。'
  docker info >/dev/null 2>&1 || fail '无法连接 Docker，请检查服务状态和当前用户权限。'
}
container_exists() { docker container inspect "$APP_CONTAINER_NAME" >/dev/null 2>&1; }
container_state() { docker container inspect --format '{{.State.Status}}' "$APP_CONTAINER_NAME"; }
check_container() {
  local source port
  source="$(docker container inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$APP_CONTAINER_NAME")"
  port="$(docker container inspect --format '{{range (index .HostConfig.PortBindings "80/tcp")}}{{.HostPort}}{{end}}' "$APP_CONTAINER_NAME")"
  [[ "$source" == "$APP_DATA_DIR" && "$port" == "$APP_PORT" ]] || fail "现有容器的数据目录或端口与脚本配置不同；请设置 APP_DATA_DIR / APP_PORT 后重试。"
}
wait_ready() {
  local deadline=$((SECONDS + APP_START_TIMEOUT)) state
  while (( SECONDS < deadline )); do
    state="$(container_state)"
    [[ "$state" == running ]] || fail "容器未运行（$state），请检查容器状态和受保护的启动日志。"
    if docker exec "$APP_CONTAINER_NAME" python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1/health",timeout=3)' >/dev/null 2>&1; then
      printf '应用已就绪：%s，端口 %s。\n' "$APP_CONTAINER_NAME" "$APP_PORT"
      return 0
    fi
    sleep 2
  done
  fail "健康检查超时（${APP_START_TIMEOUT} 秒）。容器保留运行，请检查状态后重试。"
}
