#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION_HELPER="$PROJECT_ROOT/deploy/common/version.sh"
DOCKERFILE_DIR="$SCRIPT_DIR/dockerfiles"

# shellcheck source=/dev/null
source "$VERSION_HELPER"

IMAGE="all"
PLATFORM="linux/amd64"
VERSION="$(deployment_read_version)"
REGISTRY="general"
VARIANT="full"
PUSH=false
LOAD=false
DRY_RUN=false

usage() {
  cat <<'USAGE'
Usage: deploy/images/build.sh [options]

Options:
  --image all|main|web|data-process|mcp|terminal
  --platform linux/amd64|linux/arm64
  --version VERSION
  --registry general|mainland
  --variant full|slim        data-process image variant
  --push
  --load
  --dry-run
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --image) IMAGE="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --registry) REGISTRY="$2"; shift 2 ;;
    --variant) VARIANT="$2"; shift 2 ;;
    --push) PUSH=true; shift ;;
    --load) LOAD=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

case "$REGISTRY" in
  general)
    REPO_PREFIX="nexent"
    PY_MIRROR_ARGS=()
    WEB_MIRROR_ARGS=()
    ;;
  mainland)
    REPO_PREFIX="ccr.ccs.tencentyun.com/nexent-hub"
    PY_MIRROR_ARGS=(--build-arg MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple --build-arg APT_MIRROR=tsinghua)
    WEB_MIRROR_ARGS=(--build-arg MIRROR=https://registry.npmmirror.com --build-arg APK_MIRROR=tsinghua)
    ;;
  *) echo "Unsupported registry: $REGISTRY" >&2; exit 1 ;;
esac

case "$VARIANT" in
  full|slim) ;;
  *) echo "Unsupported data-process variant: $VARIANT" >&2; exit 1 ;;
esac

run_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [ "$DRY_RUN" != true ]; then
    "$@"
  fi
}

build_one() {
  local name="$1"
  local dockerfile="$2"
  shift 2
  local tag="$REPO_PREFIX/$name:$VERSION"
  local cmd=(docker buildx build --platform "$PLATFORM" -t "$tag" -f "$dockerfile")
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
    data-process)
      local image_name="nexent-data-process"
      [ "$VARIANT" = "slim" ] && image_name="nexent-data-process-slim"
      build_one "$image_name" "$DOCKERFILE_DIR/data-process/Dockerfile" --build-arg DATA_PROCESS_VARIANT="$VARIANT" "${PY_MIRROR_ARGS[@]}"
      ;;
    mcp) build_one nexent-mcp "$DOCKERFILE_DIR/mcp/Dockerfile" "${PY_MIRROR_ARGS[@]}" ;;
    terminal) build_one nexent-ubuntu-terminal "$DOCKERFILE_DIR/terminal/Dockerfile" ;;
    *) echo "Unsupported image: $1" >&2; exit 1 ;;
  esac
}

if [ "$IMAGE" = "all" ]; then
  for selected in main web data-process mcp terminal; do
    build_selected_image "$selected"
  done
else
  build_selected_image "$IMAGE"
fi
