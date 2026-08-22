#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_COMMON="$SCRIPT_DIR/deploy/common/common.sh"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
fi
[ -n "${DEPLOYMENT_LANGUAGE:-}" ] || DEPLOYMENT_LANGUAGE="en"

usage() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    cat <<'USAGE'
用法：
  bash uninstall.sh docker [Docker 卸载选项]
  bash uninstall.sh k8s [K8s 卸载选项]

此根入口只转发到目标专用卸载脚本。
实现：deploy/uninstall.sh
USAGE
    return
  fi

  cat <<'USAGE'
Usage:
  bash uninstall.sh docker [docker uninstall options]
  bash uninstall.sh k8s [k8s uninstall options]

This root entrypoint only forwards to the target-specific uninstall script.
Implementation: deploy/uninstall.sh
USAGE
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] || [ $# -eq 0 ]; then
  usage
  exit 0
fi

exec bash "$SCRIPT_DIR/deploy/uninstall.sh" "$@"
