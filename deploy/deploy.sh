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
  bash deploy.sh docker [Docker 部署选项]
  bash deploy.sh k8s [K8s 部署选项]

Docker 实现：deploy/docker/deploy.sh
K8s 实现：   deploy/k8s/deploy.sh
USAGE
    return
  fi

  cat <<'USAGE'
Usage:
  bash deploy.sh docker [docker deploy options]
  bash deploy.sh k8s [k8s deploy options]

Docker implementation: deploy/docker/deploy.sh
K8s implementation:    deploy/k8s/deploy.sh
USAGE
}

case "${1:-}" in
  docker)
    shift
    exec bash "$SCRIPT_DIR/docker/deploy.sh" "$@"
    ;;
  k8s|kubernetes|helm)
    shift
    exec bash "$SCRIPT_DIR/k8s/deploy.sh" "$@"
    ;;
  --help|-h|"")
    usage
    ;;
  *)
    if [ "${DEPLOYMENT_LANGUAGE:-en}" = "zh" ]; then
      echo "未知部署目标：$1" >&2
    else
      echo "Unknown deploy target: $1" >&2
    fi
    usage >&2
    exit 1
    ;;
esac
