#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_COMMON="$SCRIPT_DIR/common/common.sh"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
fi

usage() {
  if [ "${DEPLOYMENT_LANGUAGE:-en}" = "zh" ]; then
    cat <<'USAGE'
用法：
  bash uninstall.sh docker [Docker 卸载选项]
  bash uninstall.sh k8s [K8s 卸载选项]

Docker 实现：deploy/docker/uninstall.sh
K8s 实现：   deploy/k8s/uninstall.sh
USAGE
    return
  fi

  cat <<'USAGE'
Usage:
  bash uninstall.sh docker [docker uninstall options]
  bash uninstall.sh k8s [k8s uninstall options]

Docker implementation: deploy/docker/uninstall.sh
K8s implementation:    deploy/k8s/uninstall.sh
USAGE
}

case "${1:-}" in
  docker)
    shift
    exec bash "$SCRIPT_DIR/docker/uninstall.sh" "$@"
    ;;
  k8s|kubernetes|helm)
    shift
    exec bash "$SCRIPT_DIR/k8s/uninstall.sh" "$@"
    ;;
  --help|-h|"")
    usage
    ;;
  *)
    if [ "${DEPLOYMENT_LANGUAGE:-en}" = "zh" ]; then
      echo "未知卸载目标：$1" >&2
    else
      echo "Unknown uninstall target: $1" >&2
    fi
    usage >&2
    exit 1
    ;;
esac
