#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "${1:-}" = "--package" ]; then
  shift
  exec bash "$SCRIPT_DIR/deploy/offline/build_offline_package.sh" "$@"
fi

exec bash "$SCRIPT_DIR/deploy/images/build.sh" "$@"
