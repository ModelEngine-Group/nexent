#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_COMMON="$SCRIPT_DIR/deploy/common/common.sh"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
else
  echo "Error: shared deployment helper not found: $DEPLOYMENT_COMMON" >&2
  exit 1
fi
[ -n "${DEPLOYMENT_LANGUAGE:-}" ] || DEPLOYMENT_LANGUAGE="en"
DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE=""

usage() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    cat <<'USAGE'
用法：
  bash deploy.sh [--load-images] [--push-images] [--reuse-from DIR] [--image-registry-prefix PREFIX] [--config|--defaults] docker [Docker 部署选项]
  bash deploy.sh [--load-images] [--push-images] [--reuse-from DIR] [--image-registry-prefix PREFIX] [--config|--defaults] k8s [K8s 部署选项]

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
  --reuse-from DIR 从已有离线部署包复用 .env、monitoring.env 和目标部署选项。
                   仅离线部署包入口可用，且会覆盖当前包中的对应文件。
                   导入的 .env 会自动补充当前 .env.example 中的新变量。
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
  bash deploy.sh [--load-images] [--push-images] [--reuse-from DIR] [--image-registry-prefix PREFIX] [--config|--defaults] docker [docker deploy options]
  bash deploy.sh [--load-images] [--push-images] [--reuse-from DIR] [--image-registry-prefix PREFIX] [--config|--defaults] k8s [k8s deploy options]

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
  --reuse-from DIR Reuse .env, monitoring.env, and target deployment options
                   from an existing offline package. Offline entrypoint only.
                   The imported .env receives new variables from the current template.
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
REUSE_FROM=""
IMAGE_REGISTRY_PREFIX="${IMAGE_REGISTRY_PREFIX:-}"
DEPLOY_CONFIG_MODE="$DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE"
DEPLOYMENT_OFFLINE="false"
[ "$DEPLOY_WRAPPER_DEFAULT_CONFIG_MODE" = "defaults" ] && DEPLOYMENT_OFFLINE="true"
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
    --reuse-from)
      if [ $# -lt 2 ]; then
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
          echo "错误：--reuse-from 需要一个目录" >&2
        else
          echo "Error: --reuse-from requires a directory" >&2
        fi
        exit 1
      fi
      REUSE_FROM="$2"
      shift 2
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

detect_deployment_target() {
  local arg
  for arg in "${FORWARD_ARGS[@]}"; do
    case "$arg" in
      docker)
        printf 'docker'
        return 0
        ;;
      k8s|kubernetes|helm)
        printf 'k8s'
        return 0
        ;;
    esac
  done
  return 1
}

reuse_deployment_files() {
  local source_input="$1"
  local target="$2"
  local source_root
  local current_root
  local relative_path
  local source_file
  local destination_file
  local optional_files=(
    "deploy/env/monitoring.env"
    "deploy/$target/deploy.options"
  )

  deployment_require_env_example "$SCRIPT_DIR/deploy/env/.env.example" || return 1

  if [ ! -d "$source_input" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：已有部署包目录不存在或不是目录：$source_input" >&2
    else
      echo "Error: existing deployment package directory does not exist or is not a directory: $source_input" >&2
    fi
    return 1
  fi

  source_root="$(cd "$source_input" 2>/dev/null && pwd -P)" || {
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：无法读取已有部署包目录：$source_input" >&2
    else
      echo "Error: cannot read existing deployment package directory: $source_input" >&2
    fi
    return 1
  }
  current_root="$(cd "$SCRIPT_DIR" && pwd -P)"
  if [ "$source_root" = "$current_root" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：已有部署包目录不能与当前部署包目录相同。" >&2
    else
      echo "Error: existing deployment package directory must differ from the current package directory." >&2
    fi
    return 1
  fi

  source_file="$source_root/deploy/env/.env"
  if [ ! -f "$source_file" ] || [ ! -r "$source_file" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：已有部署包中缺少可读的 deploy/env/.env：$source_root" >&2
    else
      echo "Error: existing deployment package does not contain a readable deploy/env/.env: $source_root" >&2
    fi
    return 1
  fi

  for relative_path in "${optional_files[@]}"; do
    source_file="$source_root/$relative_path"
    if [ -e "$source_file" ] && { [ ! -f "$source_file" ] || [ ! -r "$source_file" ]; }; then
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "错误：已有部署包文件不可读：$relative_path" >&2
      else
        echo "Error: existing deployment package file is not readable: $relative_path" >&2
      fi
      return 1
    fi
  done

  mkdir -p "$SCRIPT_DIR/deploy/env" "$SCRIPT_DIR/deploy/$target"
  cp -p "$source_root/deploy/env/.env" "$SCRIPT_DIR/deploy/env/.env"
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "已复用已有部署包文件：deploy/env/.env"
  else
    echo "Reused existing deployment package file: deploy/env/.env"
  fi
  deployment_merge_env_from_example \
    "$SCRIPT_DIR/deploy/env/.env" \
    "$SCRIPT_DIR/deploy/env/.env.example" || return 1

  for relative_path in "${optional_files[@]}"; do
    source_file="$source_root/$relative_path"
    destination_file="$SCRIPT_DIR/$relative_path"
    if [ -f "$source_file" ]; then
      mkdir -p "$(dirname "$destination_file")"
      cp -p "$source_file" "$destination_file"
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "已复用已有部署包文件：$relative_path"
      else
        echo "Reused existing deployment package file: $relative_path"
      fi
    elif [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "警告：已有部署包中未找到可选文件：$relative_path" >&2
    else
      echo "Warning: optional file not found in existing deployment package: $relative_path" >&2
    fi
  done
}

if [ -n "$REUSE_FROM" ]; then
  if [ "$DEPLOYMENT_OFFLINE" != "true" ]; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：--reuse-from 仅支持离线部署包入口。" >&2
    else
      echo "Error: --reuse-from is supported only by the offline package entrypoint." >&2
    fi
    exit 1
  fi
  if ! DEPLOYMENT_TARGET="$(detect_deployment_target)"; then
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "错误：--reuse-from 需要指定 docker 或 k8s 部署目标。" >&2
    else
      echo "Error: --reuse-from requires a docker or k8s deployment target." >&2
    fi
    exit 1
  fi
  reuse_deployment_files "$REUSE_FROM" "$DEPLOYMENT_TARGET"
fi

if [ "${#FORWARD_ARGS[@]}" -eq 0 ]; then
  usage
  exit 0
fi

deployment_ensure_root_env "$SCRIPT_DIR" "$SCRIPT_DIR/docker" || exit 1

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
  NEXENT_DEPLOYMENT_OFFLINE="$DEPLOYMENT_OFFLINE" \
    NEXENT_DEPLOY_CONFIG_MODE="$DEPLOY_CONFIG_MODE" \
    exec bash "$SCRIPT_DIR/deploy/deploy.sh" "${FORWARD_ARGS[@]}"
fi

NEXENT_DEPLOYMENT_OFFLINE="$DEPLOYMENT_OFFLINE" \
  exec bash "$SCRIPT_DIR/deploy/deploy.sh" "${FORWARD_ARGS[@]}"
