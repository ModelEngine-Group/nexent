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
  bash deploy.sh [--config|--defaults] docker [Docker 部署选项]
  bash deploy.sh [--config|--defaults] k8s [K8s 部署选项]

Docker 实现：deploy/docker/deploy.sh
K8s 实现：   deploy/k8s/deploy.sh
选项：
  --config         进入交互式部署配置界面。
  --defaults       复用保存配置或内置默认值，跳过交互界面。
USAGE
    return
  fi

  cat <<'USAGE'
Usage:
  bash deploy.sh [--config|--defaults] docker [docker deploy options]
  bash deploy.sh [--config|--defaults] k8s [k8s deploy options]

Docker implementation: deploy/docker/deploy.sh
K8s implementation:    deploy/k8s/deploy.sh
Options:
  --config         Open the interactive deployment configuration.
  --defaults       Use saved configuration or built-in defaults and skip TUI.
USAGE
}

case "${1:-}" in
  --config)
    export NEXENT_DEPLOY_CONFIG_MODE="tui"
    shift
    exec bash "$0" "$@"
    ;;
  --defaults)
    export NEXENT_DEPLOY_CONFIG_MODE="defaults"
    shift
    exec bash "$0" "$@"
    ;;
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
