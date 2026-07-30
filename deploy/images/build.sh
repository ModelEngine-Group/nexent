#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION_HELPER="$PROJECT_ROOT/deploy/common/version.sh"
DEPLOYMENT_COMMON="$PROJECT_ROOT/deploy/common/common.sh"
DOCKERFILE_DIR="$SCRIPT_DIR/dockerfiles"

# shellcheck source=/dev/null
source "$VERSION_HELPER"
# shellcheck source=/dev/null
source "$DEPLOYMENT_COMMON"

IMAGE="all"
IMAGES=""
COMPONENTS=""
PLATFORM=""
VERSION="$(deployment_read_version)"
REGISTRY="general"
REPO_PREFIX="nexent"
MAINLAND_REPO_PREFIX="ccr.ccs.tencentyun.com/nexent-hub"
DEPENDENCY_VARIANT="cpu"
TERMINAL_VARIANT="slim"
PUSH=false
LOAD=false
NO_CACHE=false
DRY_RUN=false
INTERACTIVE=false
ARGS_COUNT=$#
REQUESTED_IMAGES=()

if [ "$ARGS_COUNT" -eq 0 ] && [ -t 0 ]; then
  INTERACTIVE=true
fi

usage() {
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    cat <<'USAGE'
用法：deploy/images/build.sh [选项]

选项：
  --images LIST              逗号分隔的镜像列表：all,main,web,data-process,mcp,terminal,docs
  --image IMAGE              兼容参数，等同于只传一个 --images
  --all                      构建全部镜像
  --main                     构建 nexent/nexent
  --web                      构建 nexent/nexent-web
  --data-process             构建 nexent/nexent-data-process
  --mcp                      构建 nexent/nexent-mcp
  --terminal                 构建 nexent/nexent-ubuntu-terminal
  --docs                     构建 nexent/nexent-docs
  --components LIST          将部署组件兼容映射为镜像列表
  --platform linux/amd64|linux/arm64|linux/amd64,linux/arm64
  --version VERSION          镜像 tag，例如 v2.2.1 或 latest。默认读取根目录 VERSION
  --registry general|mainland
  --dependency-variant cpu|gpu
                             data-process 依赖变体，默认 cpu
  --terminal-variant slim|conda
                             terminal 镜像变体，默认 slim
  --push
  --load
  --no-cache
  --dry-run
  --interactive              交互式选择镜像、版本和镜像源
USAGE
    return
  fi

  cat <<'USAGE'
Usage: deploy/images/build.sh [options]

Options:
  --images LIST              Comma-separated image list: all,main,web,data-process,mcp,terminal,docs,sandbox
  --image IMAGE              Compatibility alias for --images with one image
  --all                      Build all images
  --main                     Build nexent/nexent
  --web                      Build nexent/nexent-web
  --data-process             Build nexent/nexent-data-process
  --mcp                      Build nexent/nexent-mcp
  --terminal                 Build nexent/nexent-ubuntu-terminal
  --docs                     Build nexent/nexent-docs
  --components LIST          Compatibility mapping from deployment components to images.
  --platform linux/amd64|linux/arm64|linux/amd64,linux/arm64
  --version VERSION          Image tag, for example v2.2.1 or latest. Defaults to root VERSION.
  --registry general|mainland
  --dependency-variant cpu|gpu
                             data-process dependency variant. Defaults to cpu.
  --terminal-variant slim|conda
                             terminal image variant. Defaults to slim.
  --push
  --load
  --no-cache
  --dry-run
  --interactive              Prompt for images, version, and registry.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --image) IMAGE="$2"; shift 2 ;;
    --images) IMAGES="$2"; shift 2 ;;
    --all) REQUESTED_IMAGES=(all); shift ;;
    --main) REQUESTED_IMAGES+=("main"); shift ;;
    --web) REQUESTED_IMAGES+=("web"); shift ;;
    --data-process) REQUESTED_IMAGES+=("data-process"); shift ;;
    --mcp) REQUESTED_IMAGES+=("mcp"); shift ;;
    --terminal) REQUESTED_IMAGES+=("terminal"); shift ;;
    --docs) REQUESTED_IMAGES+=("docs"); shift ;;
    --sandbox) REQUESTED_IMAGES+=("sandbox"); shift ;;
    --components) COMPONENTS="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --registry) REGISTRY="$2"; shift 2 ;;
    --dependency-variant|--data-process-dependency-variant) DEPENDENCY_VARIANT="$2"; shift 2 ;;
    --terminal-variant) TERMINAL_VARIANT="$2"; shift 2 ;;
    --push) PUSH=true; shift ;;
    --load) LOAD=true; shift ;;
    --no-cache) NO_CACHE=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --interactive) INTERACTIVE=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *)
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "未知选项：$1" >&2
      else
        echo "Unknown option: $1" >&2
      fi
      usage >&2
      exit 1
      ;;
  esac
done

prompt_choice() {
  local prompt="$1"
  local default_value="$2"
  local value
  read -r -p "$prompt" value || value=""
  printf '%s' "${value:-$default_value}"
}

add_image_if_missing() {
  local image="$1"
  local existing
  for existing in "${SELECTED_IMAGES[@]}"; do
    [ "$existing" = "$image" ] && return 0
  done
  SELECTED_IMAGES+=("$image")
}

select_all_images() {
  SELECTED_IMAGES=(main web data-process mcp terminal docs sandbox)
}

select_images_from_csv() {
  local images="$1"
  local old_ifs="$IFS"
  local image normalized

  SELECTED_IMAGES=()
  IFS=','
  for image in $images; do
    normalized="$(deployment_trim "$image")"
    case "$normalized" in
      "" )
        ;;
      all)
        select_all_images
        ;;
      main|web|data-process|mcp|terminal|docs|sandbox)
        add_image_if_missing "$normalized"
        ;;
      *)
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
          echo "不支持的镜像：$normalized" >&2
        else
          echo "Unsupported image: $normalized" >&2
        fi
        exit 1
        ;;
    esac
  done
  IFS="$old_ifs"
}

image_tui_multiselect() {
  [ -t 0 ] || return 1

  local images=(main web data-process mcp terminal docs sandbox)
  local details=(
    "$(deployment_i18n image_build.detail.main)"
    "$(deployment_i18n image_build.detail.web)"
    "$(deployment_i18n image_build.detail.data_process)"
    "$(deployment_i18n image_build.detail.mcp)"
    "$(deployment_i18n image_build.detail.terminal)"
    "$(deployment_i18n image_build.detail.docs)"
    "Sandbox runtime for LLM-generated Python execution"
  )
  local selected=(1 1 0 0 0 0 0)
  local cursor=0
  local i key key_tail selection

  image_tui_render() {
    printf '\033[2J\033[H'
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      printf '选择要构建的镜像\n'
      printf '使用 Up/Down 或 j/k 移动，空格切换，Enter 确认，q 退出。\n\n'
    else
      printf 'Select images to build\n'
      printf 'Use Up/Down or j/k to move, Space to toggle, Enter to confirm, q to quit.\n\n'
    fi
    local row marker check
    for row in "${!images[@]}"; do
      marker=" "
      [ "$row" -eq "$cursor" ] && marker=">"
      check=" "
      [ "${selected[$row]}" = "1" ] && check="*"
      printf '%s [%s] %s - %s\n' "$marker" "$check" "${images[$row]}" "${details[$row]}"
    done
  }

  printf '\033[?25l'
  while true; do
    image_tui_render
    IFS= read -rsn1 key || key=""
    if [ -z "$key" ]; then
      selection=""
      for i in "${!images[@]}"; do
        if [ "${selected[$i]}" = "1" ]; then
          selection="$(deployment_join_csv "$selection" "${images[$i]}")"
        fi
      done
      if [ -n "$selection" ]; then
        IMAGES="$selection"
        break
      fi
      continue
    fi

    if [ "$key" = $'\033' ]; then
      IFS= read -rsn2 -t 0.1 key_tail || key_tail=""
      key="${key}${key_tail}"
    fi

    case "$key" in
      $'\033[A'|k|K)
        cursor=$((cursor - 1))
        [ "$cursor" -lt 0 ] && cursor=$((${#images[@]} - 1))
        ;;
      $'\033[B'|j|J)
        cursor=$((cursor + 1))
        [ "$cursor" -ge "${#images[@]}" ] && cursor=0
        ;;
      " ")
        if [ "${selected[$cursor]}" = "1" ]; then
          selected[$cursor]=0
        else
          selected[$cursor]=1
        fi
        ;;
      q|Q)
        printf '\033[?25h'
        printf '\033[2J\033[H'
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
          echo "已取消镜像构建配置。" >&2
        else
          echo "Image build configuration cancelled." >&2
        fi
        return 130
        ;;
    esac
  done
  printf '\033[?25h'
  printf '\033[2J\033[H'
}

run_interactive_configuration() {
  local root_version
  root_version="$(deployment_read_version)"

  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "Nexent 镜像构建配置"
  else
    echo "Nexent image build configuration"
  fi
  echo ""

  if [ -z "$IMAGES" ] && [ "${#REQUESTED_IMAGES[@]}" -eq 0 ] && [ -z "$COMPONENTS" ] && [ "$IMAGE" = "all" ]; then
    if [ -t 0 ]; then
      image_tui_multiselect || return $?
    else
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "镜像："
      else
        echo "Images:"
      fi
      echo "  main, web, data-process, mcp, terminal, docs, sandbox"
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        IMAGES="$(prompt_choice "请输入镜像（默认：main,web）：" "main,web")"
      else
        IMAGES="$(prompt_choice "Enter images (default: main,web): " "main,web")"
      fi
    fi
  fi

  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "镜像版本："
  else
    echo "Image version:"
  fi
  echo "  1) latest"
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "  2) 根目录 VERSION ($root_version)"
  else
    echo "  2) Root VERSION ($root_version)"
  fi
  local version_choice
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    version_choice="$(prompt_choice "选择版本 [1/2]（默认：1）：" "1")"
  else
    version_choice="$(prompt_choice "Choose version [1/2] (default: 1): " "1")"
  fi
  case "$version_choice" in
    1|latest|"") VERSION="latest" ;;
    2|root|version|VERSION) VERSION="$root_version" ;;
    *)
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "不支持的版本选择：$version_choice" >&2
      else
        echo "Unsupported version choice: $version_choice" >&2
      fi
      exit 1
      ;;
  esac

  echo ""
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "镜像源："
    echo "  1) general（公共镜像源）"
    echo "  2) mainland（中国大陆镜像源）"
  else
    echo "Image source:"
    echo "  1) general (public image sources)"
    echo "  2) mainland (mainland China image sources and build mirrors)"
  fi
  local registry_choice
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    registry_choice="$(prompt_choice "选择镜像源 [1/2]（默认：1）：" "1")"
  else
    registry_choice="$(prompt_choice "Choose image source [1/2] (default: 1): " "1")"
  fi
  case "$registry_choice" in
    2|mainland) REGISTRY="mainland" ;;
    1|general|"") REGISTRY="general" ;;
    *) REGISTRY="$registry_choice" ;;
  esac

}

if [ "$INTERACTIVE" = true ]; then
  run_interactive_configuration
fi

case "$REGISTRY" in
  general)
    PY_MIRROR_ARGS=()
    WEB_MIRROR_ARGS=()
    ;;
  mainland)
    PY_MIRROR_ARGS=(--build-arg MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple --build-arg APT_MIRROR=tsinghua)
    WEB_MIRROR_ARGS=(--build-arg MIRROR=https://registry.npmmirror.com --build-arg APK_MIRROR=tsinghua)
    ;;
  *)
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "不支持的 registry：$REGISTRY" >&2
    else
      echo "Unsupported registry: $REGISTRY" >&2
    fi
    exit 1
    ;;
esac

case "$DEPENDENCY_VARIANT" in
  cpu|gpu) ;;
  *)
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "不支持的 data-process 依赖变体：$DEPENDENCY_VARIANT" >&2
    else
      echo "Unsupported data-process dependency variant: $DEPENDENCY_VARIANT" >&2
    fi
    exit 1
    ;;
esac

case "$TERMINAL_VARIANT" in
  slim|conda) ;;
  *)
    if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
      echo "不支持的 terminal 变体：$TERMINAL_VARIANT" >&2
    else
      echo "Unsupported terminal variant: $TERMINAL_VARIANT" >&2
    fi
    exit 1
    ;;
esac

run_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [ "$DRY_RUN" != true ]; then
    "$@"
  fi
}

model_assets_complete() {
  local model_assets_dir="$1"

  [ -f "$model_assets_dir/clip-vit-base-patch32/config.json" ] && \
    [ -d "$model_assets_dir/nltk_data" ] && \
    [ -d "$model_assets_dir/table-transformer-structure-recognition" ] && \
    [ -d "$model_assets_dir/yolox" ]
}

prepare_model_assets() {
  [ "$DRY_RUN" = true ] && return 0

  local project_model_assets="$PROJECT_ROOT/model-assets"
  local home_model_assets="${HOME:-}/model-assets"
  local model_assets_repo="${MODEL_ASSETS_REPO:-}"
  local tmp_model_assets

  if model_assets_complete "$project_model_assets"; then
    echo "Using existing model-assets at $project_model_assets"
    return 0
  fi

  if [ -n "${HOME:-}" ] && model_assets_complete "$home_model_assets"; then
    echo "Copying cached model-assets from $home_model_assets"
    mkdir -p "$project_model_assets"
    cp -R "$home_model_assets"/. "$project_model_assets"/
    return 0
  fi

  command -v git >/dev/null 2>&1 || {
    echo "git is required to clone model-assets for data-process builds." >&2
    exit 1
  }
  git lfs version >/dev/null 2>&1 || {
    echo "git-lfs is required to pull model-assets for data-process builds." >&2
    exit 1
  }

  if [ -z "$model_assets_repo" ]; then
    if [ "$REGISTRY" = "mainland" ]; then
      model_assets_repo="https://hf-mirror.com/Nexent-AI/model-assets"
    else
      model_assets_repo="https://huggingface.co/Nexent-AI/model-assets"
    fi
  fi

  tmp_model_assets="$PROJECT_ROOT/model-assets.tmp.$$"
  echo "Cloning model-assets from $model_assets_repo"
  rm -rf "$tmp_model_assets"
  GIT_LFS_SKIP_SMUDGE=1 git clone "$model_assets_repo" "$tmp_model_assets"
  (
    cd "$tmp_model_assets"
    GIT_TRACE=1 GIT_CURL_VERBOSE=1 GIT_LFS_LOG=debug git lfs pull
    rm -rf .git .gitattributes
  )
  mkdir -p "$project_model_assets"
  cp -R "$tmp_model_assets"/. "$project_model_assets"/
  rm -rf "$tmp_model_assets"
}

build_one() {
  local name="$1"
  local dockerfile="$2"
  shift 2
  local tag="$REPO_PREFIX/$name:$VERSION"
  if [ "$PUSH" = true ] && [ "$REGISTRY" = "mainland" ]; then
    tag="$MAINLAND_REPO_PREFIX/$name:$VERSION"
  fi
  local cmd=(docker buildx build)
  if [ -n "$PLATFORM" ]; then
    cmd+=(--platform "$PLATFORM")
  fi
  if [ "$NO_CACHE" = true ] || { [ "$REGISTRY" = "mainland" ] && [ "$name" = "nexent-web" ]; }; then
    cmd+=(--no-cache)
  fi
  cmd+=(-t "$tag" -f "$dockerfile")
  if [ "$PUSH" = true ]; then
    cmd+=(--push)
  elif [ "$LOAD" = true ]; then
    cmd+=(--load)
  fi
  cmd+=("$@" "$PROJECT_ROOT")
  run_cmd "${cmd[@]}"
}

build_selected_image() {
  case "$1" in
    main) build_one nexent "$DOCKERFILE_DIR/main/Dockerfile" "${PY_MIRROR_ARGS[@]}" ;;
    web) build_one nexent-web "$DOCKERFILE_DIR/web/Dockerfile" "${WEB_MIRROR_ARGS[@]}" ;;
    docs) build_one nexent-docs "$DOCKERFILE_DIR/docs/Dockerfile" "${WEB_MIRROR_ARGS[@]}" ;;
    data-process)
      local image_name="nexent-data-process"
      [ "$DEPENDENCY_VARIANT" = "gpu" ] && image_name="${image_name}-gpu"
      prepare_model_assets
      build_one "$image_name" "$DOCKERFILE_DIR/data-process/Dockerfile" \
        --build-arg DATA_PROCESS_DEPENDENCY_VARIANT="$DEPENDENCY_VARIANT" \
        "${PY_MIRROR_ARGS[@]}"
      ;;
    mcp) build_one nexent-mcp "$DOCKERFILE_DIR/mcp/Dockerfile" "${PY_MIRROR_ARGS[@]}" ;;
    terminal)
      local image_name="nexent-ubuntu-terminal"
      [ "$TERMINAL_VARIANT" = "conda" ] && image_name="nexent-ubuntu-terminal-conda"
      build_one "$image_name" "$DOCKERFILE_DIR/terminal/Dockerfile" --build-arg TERMINAL_VARIANT="$TERMINAL_VARIANT"
      ;;
    sandbox) build_one nexent-sandbox "$DOCKERFILE_DIR/sandbox/Dockerfile" "${PY_MIRROR_ARGS[@]}" ;;
    *)
      if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
        echo "不支持的镜像：$1" >&2
      else
        echo "Unsupported image: $1" >&2
      fi
      exit 1
      ;;
  esac
}

select_images_from_components() {
  local components="$1"
  local old_ifs="$IFS"
  local component normalized

  SELECTED_IMAGES=()
  IFS=','
  for component in $components; do
    normalized="$(deployment_trim "$component")"
    case "$normalized" in
      ""|infrastructure|supabase|monitoring)
        ;;
      application)
        add_image_if_missing main
        add_image_if_missing web
        add_image_if_missing mcp
        ;;
      data-process)
        add_image_if_missing data-process
        ;;
      terminal)
        add_image_if_missing terminal
        ;;
      sandbox)
        add_image_if_missing sandbox
        ;;
      *)
        if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
          echo "镜像构建不支持该组件：$normalized" >&2
        else
          echo "Unsupported component for image build: $normalized" >&2
        fi
        exit 1
        ;;
    esac
  done
  IFS="$old_ifs"
}

select_images_from_image_arg() {
  SELECTED_IMAGES=()
  if [ "$IMAGE" = "all" ]; then
    select_all_images
  else
    select_images_from_csv "$IMAGE"
  fi
}

SELECTED_IMAGES=()
if [ "${#REQUESTED_IMAGES[@]}" -gt 0 ]; then
  select_images_from_csv "$(deployment_join_csv "${REQUESTED_IMAGES[@]}")"
elif [ -n "$IMAGES" ]; then
  select_images_from_csv "$IMAGES"
elif [ -n "$COMPONENTS" ]; then
  select_images_from_components "$COMPONENTS"
else
  select_images_from_image_arg
fi

if [ "${#SELECTED_IMAGES[@]}" -eq 0 ]; then
  if [ "$DEPLOYMENT_LANGUAGE" = "zh" ]; then
    echo "未选择任何 Nexent 镜像进行构建。"
  else
    echo "No Nexent images selected for build."
  fi
  exit 0
fi

for selected in "${SELECTED_IMAGES[@]}"; do
  build_selected_image "$selected"
done
