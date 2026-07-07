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
  bash deploy.sh [--load-images] [--config] docker [Docker 部署选项]
  bash deploy.sh [--load-images] [--config] k8s [K8s 部署选项]

此根入口只转发到目标专用部署脚本。
实现：deploy/deploy.sh

选项：
  --load-images    部署前从 ./images 加载 Docker 镜像 tar 文件。
                   默认关闭。
  --config         进入交互式部署配置界面。
USAGE
    return
  fi

  cat <<'USAGE'
Usage:
  bash deploy.sh [--load-images] [--config] docker [docker deploy options]
  bash deploy.sh [--load-images] [--config] k8s [k8s deploy options]

This root entrypoint only forwards to the target-specific deploy script.
Implementation: deploy/deploy.sh

Options:
  --load-images    Load Docker image tar files from ./images before deploying.
                   Defaults to off.
  --config         Open the interactive deployment configuration.
USAGE
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] || [ $# -eq 0 ]; then
  usage
  exit 0
fi

LOAD_IMAGES="false"
FORWARD_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --load-images)
      LOAD_IMAGES="true"
      shift
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done

if [ "${#FORWARD_ARGS[@]}" -eq 0 ]; then
  usage
  exit 0
fi

if [ "$LOAD_IMAGES" = "true" ]; then
  LOAD_SCRIPT="$SCRIPT_DIR/load-images.sh"
  if [ ! -f "$LOAD_SCRIPT" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：--load-images 需要 $LOAD_SCRIPT" >&2
    else
      echo "Error: --load-images requires $LOAD_SCRIPT" >&2
    fi
    exit 1
  fi
  bash "$LOAD_SCRIPT"
fi

exec bash "$SCRIPT_DIR/deploy/deploy.sh" "${FORWARD_ARGS[@]}"
