#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
[[ -f "$ROOT/deployment.env" ]] || { printf '请先执行 deploy-offline.sh 完成部署。\n' >&2; exit 1; }
source "$ROOT/deployment.env"
exec bash "$ROOT/stop.sh" "$@"
