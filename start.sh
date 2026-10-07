#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/scripts/application.sh"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  printf '%s\n' '用法：./start.sh' '启动现有应用；容器不存在时使用本地镜像创建。' '环境变量：APP_CONTAINER_NAME、APP_IMAGE、APP_PORT、APP_DATA_DIR、APP_START_TIMEOUT。'
  exit 0
fi
(( $# == 0 )) || fail '不接受位置参数，请使用 --help 查看配置方式。'
check_environment
if container_exists; then
  check_container
  state="$(container_state)"
  case "$state" in
    running) printf '应用容器已运行，检查就绪状态…\n' ;;
    created|exited) docker start "$APP_CONTAINER_NAME" >/dev/null ;;
    *) fail "容器状态为 $state，请先处理该状态后重试。" ;;
  esac
else
  docker image inspect "$APP_IMAGE" >/dev/null 2>&1 || fail "本地镜像 $APP_IMAGE 不存在，请先按照 README 构建镜像。"
  mkdir -p -- "$APP_DATA_DIR"
  docker run -d --name "$APP_CONTAINER_NAME" -p "$APP_PORT:80" \
    -v "$APP_DATA_DIR:/data:Z" --restart unless-stopped "$APP_IMAGE" >/dev/null
fi
wait_ready
