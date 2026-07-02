#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  bash uninstall.sh docker [docker uninstall options]
  bash uninstall.sh k8s [k8s uninstall options]

Docker implementation: deploy/docker/uninstall.sh
K8s implementation:    deploy/k8s/uninstall.sh
USAGE
}

case "${1:-}" in
  docker)
    shift
    exec bash "$SCRIPT_DIR/docker/uninstall.sh" "$@"
    ;;
  k8s|kubernetes|helm)
    shift
    exec bash "$SCRIPT_DIR/k8s/uninstall.sh" "$@"
    ;;
  --help|-h|"")
    usage
    ;;
  *)
    echo "Unknown uninstall target: $1" >&2
    usage >&2
    exit 1
    ;;
esac
