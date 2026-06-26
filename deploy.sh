#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  bash deploy.sh [--load-images] docker [docker deploy options]
  bash deploy.sh [--load-images] k8s [k8s deploy options]

This root entrypoint only forwards to the target-specific deploy script.
Implementation: deploy/deploy.sh

Options:
  --load-images    Load Docker image tar files from ./images before deploying.
                   Defaults to off.
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
    echo "Error: --load-images requires $LOAD_SCRIPT" >&2
    exit 1
  fi
  bash "$LOAD_SCRIPT"
fi

exec bash "$SCRIPT_DIR/deploy/deploy.sh" "${FORWARD_ARGS[@]}"
