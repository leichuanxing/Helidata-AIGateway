#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/scripts/application.sh"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  printf '%s\n' '用法：./stop.sh' '正常停止应用容器，保留容器、数据和镜像。' '环境变量：APP_CONTAINER_NAME、APP_PORT、APP_DATA_DIR、APP_STOP_TIMEOUT。'
  exit 0
fi
(( $# == 0 )) || fail '不接受位置参数，请使用 --help 查看配置方式。'
check_environment
if ! container_exists; then
  printf '应用容器不存在，无需停止：%s。\n' "$APP_CONTAINER_NAME"
  exit 0
fi
check_container
state="$(container_state)"
case "$state" in
  created|exited|dead) printf '应用容器已停止：%s。\n' "$APP_CONTAINER_NAME" ;;
  running|restarting)
    docker stop --time "$APP_STOP_TIMEOUT" "$APP_CONTAINER_NAME" >/dev/null
    [[ "$(container_state)" == exited ]] || fail '停止后容器未进入 exited 状态，请检查容器。'
    printf '应用已停止，容器和数据已保留：%s。\n' "$APP_CONTAINER_NAME"
    ;;
  *) fail "容器状态为 $state，请先处理该状态后重试。" ;;
esac
