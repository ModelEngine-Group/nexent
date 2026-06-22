#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  bash deploy.sh docker [docker deploy options]
  bash deploy.sh k8s [k8s deploy options]

This root entrypoint only forwards to the target-specific deploy script.
Implementation: deploy/deploy.sh
USAGE
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] || [ $# -eq 0 ]; then
  usage
  exit 0
fi

exec bash "$SCRIPT_DIR/deploy/deploy.sh" "$@"
