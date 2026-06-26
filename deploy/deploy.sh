#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  bash deploy.sh docker [docker deploy options]
  bash deploy.sh k8s [k8s deploy options]

Docker implementation: deploy/docker/deploy.sh
K8s implementation:    deploy/k8s/deploy.sh
USAGE
}

case "${1:-}" in
  docker)
    shift
    exec bash "$SCRIPT_DIR/docker/deploy.sh" "$@"
    ;;
  k8s|kubernetes|helm)
    shift
    exec bash "$SCRIPT_DIR/k8s/deploy.sh" "$@"
    ;;
  --help|-h|"")
    usage
    ;;
  *)
    echo "Unknown deploy target: $1" >&2
    usage >&2
    exit 1
    ;;
esac
