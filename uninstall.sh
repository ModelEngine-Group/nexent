#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  bash uninstall.sh docker [docker uninstall options]
  bash uninstall.sh k8s [k8s uninstall options]

This root entrypoint only forwards to the target-specific uninstall script.
Implementation: deploy/uninstall.sh
USAGE
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] || [ $# -eq 0 ]; then
  usage
  exit 0
fi

exec bash "$SCRIPT_DIR/deploy/uninstall.sh" "$@"
