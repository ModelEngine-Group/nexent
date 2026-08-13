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
  bash build.sh [镜像构建选项]
  bash build.sh --package [离线包构建选项]

镜像构建会转发到：deploy/images/build.sh
离线包构建会转发到：deploy/offline/build_offline_package.sh

常用示例：
  bash build.sh --main --version latest --dry-run
  bash build.sh --package --version latest --target docker --dry-run

更多选项：
  bash deploy/images/build.sh --help
  bash deploy/offline/build_offline_package.sh --help
USAGE
    return
  fi

  cat <<'USAGE'
Usage:
  bash build.sh [image build options]
  bash build.sh --package [offline package options]

Image builds are forwarded to: deploy/images/build.sh
Offline package builds are forwarded to: deploy/offline/build_offline_package.sh

Examples:
  bash build.sh --main --version latest --dry-run
  bash build.sh --package --version latest --target docker --dry-run

More options:
  bash deploy/images/build.sh --help
  bash deploy/offline/build_offline_package.sh --help
USAGE
}

case "${1:-}" in
  --help|-h)
    usage
    exit 0
    ;;
esac

if [ "${1:-}" = "--package" ]; then
  shift
  exec bash "$SCRIPT_DIR/deploy/offline/build_offline_package.sh" "$@"
fi

exec bash "$SCRIPT_DIR/deploy/images/build.sh" "$@"
