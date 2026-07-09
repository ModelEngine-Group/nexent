#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_COMMON="$SCRIPT_DIR/deploy/common/common.sh"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
fi
[ -n "${DEPLOYMENT_LANGUAGE:-}" ] || DEPLOYMENT_LANGUAGE="en"
DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE=""

usage() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    cat <<'USAGE'
用法：
  bash deploy.sh [--load-images] [--push-images] [--image-registry-prefix PREFIX] [--config|--defaults] docker [Docker 部署选项]
  bash deploy.sh [--load-images] [--push-images] [--image-registry-prefix PREFIX] [--config|--defaults] k8s [K8s 部署选项]

USAGE
    if [ "$DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE" = "defaults" ]; then
      cat <<'USAGE'
此离线包入口默认复用保存配置或内置默认值部署，不进入交互界面。
添加 --config 可进入交互式部署配置界面。
实现：deploy/deploy.sh

USAGE
    else
      cat <<'USAGE'
此根入口只转发到目标专用部署脚本。
实现：deploy/deploy.sh

USAGE
    fi
    cat <<'USAGE'
选项：
  --load-images    部署前从 ./images 加载 Docker 镜像 tar 文件。
                   默认关闭。
  --push-images    部署前调用 push-images.sh 推送镜像。
  --image-registry-prefix PREFIX
                   镜像仓库前缀，例如 registry.example.com/nexent。
                   使用 --push-images 且未传入时会交互询问。
  --config         进入交互式部署配置界面。
  --defaults       复用保存配置或内置默认值，跳过交互界面。
USAGE
    return
  fi

  cat <<'USAGE'
Usage:
  bash deploy.sh [--load-images] [--push-images] [--image-registry-prefix PREFIX] [--config|--defaults] docker [docker deploy options]
  bash deploy.sh [--load-images] [--push-images] [--image-registry-prefix PREFIX] [--config|--defaults] k8s [k8s deploy options]

USAGE
  if [ "$DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE" = "defaults" ]; then
    cat <<'USAGE'
This offline entrypoint deploys with saved configuration or built-in defaults by default.
Add --config to open the interactive deployment configuration.
Implementation: deploy/deploy.sh

USAGE
  else
    cat <<'USAGE'
This root entrypoint only forwards to the target-specific deploy script.
Implementation: deploy/deploy.sh

USAGE
  fi
  cat <<'USAGE'
Options:
  --load-images    Load Docker image tar files from ./images before deploying.
                   Defaults to off.
  --push-images    Run push-images.sh before deploying.
  --image-registry-prefix PREFIX
                   Image registry prefix, e.g. registry.example.com/nexent.
                   Prompts when --push-images is used and no prefix is provided.
  --config         Open the interactive deployment configuration.
  --defaults       Use saved configuration or built-in defaults and skip TUI.
USAGE
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] || [ $# -eq 0 ]; then
  usage
  exit 0
fi

LOAD_IMAGES="false"
PUSH_IMAGES="false"
IMAGE_REGISTRY_PREFIX="${IMAGE_REGISTRY_PREFIX:-}"
DEPLOY_CONFIG_MODE="$DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE"
FORWARD_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --load-images)
      LOAD_IMAGES="true"
      shift
      ;;
    --push-images)
      PUSH_IMAGES="true"
      shift
      ;;
    --image-registry-prefix|--registry-prefix|--image-registry)
      if [ $# -lt 2 ]; then
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
          echo "错误：$1 需要一个值" >&2
        else
          echo "Error: $1 requires a value" >&2
        fi
        exit 1
      fi
      IMAGE_REGISTRY_PREFIX="$2"
      shift 2
      ;;
    --config)
      DEPLOY_CONFIG_MODE="tui"
      shift
      ;;
    --defaults)
      DEPLOY_CONFIG_MODE="defaults"
      shift
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done

normalize_image_registry_prefix() {
  if declare -F deployment_normalize_image_registry_prefix_value >/dev/null 2>&1; then
    deployment_normalize_image_registry_prefix_value "$1"
    return 0
  fi

  local prefix="$1"
  prefix="${prefix#"${prefix%%[![:space:]]*}"}"
  prefix="${prefix%"${prefix##*[![:space:]]}"}"
  prefix="${prefix#http://}"
  prefix="${prefix#https://}"
  while [[ "$prefix" == */ ]]; do
    prefix="${prefix%/}"
  done
  printf '%s' "$prefix"
}

require_image_registry_prefix() {
  if [ -z "$IMAGE_REGISTRY_PREFIX" ]; then
    if [ -t 0 ]; then
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        read -r -p "请输入镜像仓库前缀（例如 registry.example.com/nexent）: " IMAGE_REGISTRY_PREFIX
      else
        read -r -p "Enter image registry prefix (e.g. registry.example.com/nexent): " IMAGE_REGISTRY_PREFIX
      fi
    else
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "错误：--push-images 需要 --image-registry-prefix，或设置 IMAGE_REGISTRY_PREFIX。" >&2
      else
        echo "Error: --push-images requires --image-registry-prefix or IMAGE_REGISTRY_PREFIX." >&2
      fi
      exit 1
    fi
  fi

  IMAGE_REGISTRY_PREFIX="$(normalize_image_registry_prefix "$IMAGE_REGISTRY_PREFIX")"
  if [ -z "$IMAGE_REGISTRY_PREFIX" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：镜像仓库前缀不能为空。" >&2
    else
      echo "Error: image registry prefix cannot be empty." >&2
    fi
    exit 1
  fi
}

if [ "${#FORWARD_ARGS[@]}" -eq 0 ]; then
  usage
  exit 0
fi

if [ "$LOAD_IMAGES" = "true" ] && [ "$PUSH_IMAGES" != "true" ]; then
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

if [ "$PUSH_IMAGES" = "true" ]; then
  PUSH_SCRIPT="$SCRIPT_DIR/push-images.sh"
  if [ ! -f "$PUSH_SCRIPT" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：--push-images 需要 $PUSH_SCRIPT" >&2
    else
      echo "Error: --push-images requires $PUSH_SCRIPT" >&2
    fi
    exit 1
  fi

  require_image_registry_prefix
  bash "$PUSH_SCRIPT" --image-registry-prefix "$IMAGE_REGISTRY_PREFIX" --load-images
fi

if [ -n "$IMAGE_REGISTRY_PREFIX" ]; then
  IMAGE_REGISTRY_PREFIX="$(normalize_image_registry_prefix "$IMAGE_REGISTRY_PREFIX")"
  if [ -n "$IMAGE_REGISTRY_PREFIX" ]; then
    FORWARD_ARGS+=("--image-registry-prefix" "$IMAGE_REGISTRY_PREFIX")
  fi
fi

if [ -n "$DEPLOY_CONFIG_MODE" ]; then
  NEXENT_DEPLOY_CONFIG_MODE="$DEPLOY_CONFIG_MODE" exec bash "$SCRIPT_DIR/deploy/deploy.sh" "${FORWARD_ARGS[@]}"
fi

exec bash "$SCRIPT_DIR/deploy/deploy.sh" "${FORWARD_ARGS[@]}"
