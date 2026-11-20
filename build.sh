#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_COMMON="$SCRIPT_DIR/deploy/common/common.sh"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
fi
[ -n "${DEPLOYMENT_LANGUAGE:-}" ] || DEPLOYMENT_LANGUAGE="en"

usage() {
  cat <<'USAGE'
Usage:
  bash build.sh [image build options]
  bash build.sh --package [offline package options]

Image builds are forwarded to: deploy/images/build.sh
Offline package builds are forwarded to: deploy/offline/build_offline_package.sh

Available images (use --images LIST with comma-separated names, or matching flags):
  main          nexent/nexent
  management    nexent/nexent-management
  runtime       nexent/nexent-runtime
  mcp-service   nexent/nexent-mcp-service
  ops           nexent/nexent-ops
  gateway       nexent/nexent-gateway
  web           nexent/nexent-web
  data-process  nexent/nexent-data-process
  mcp           nexent/nexent-mcp (proxy)
  terminal      nexent/nexent-ubuntu-terminal
  docs          nexent/nexent-docs
  sandbox       nexent/nexent-sandbox
  sandbox-full  nexent/nexent-sandbox-full
  all           Build the images above, excluding optional sandbox-full

Examples:
  bash build.sh --main --version latest --dry-run
  bash build.sh --images runtime,management --version latest --load
  bash build.sh --images mcp-service,ops --version latest --load
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
