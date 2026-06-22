#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "[WARN] k8s/helm/uninstall.sh is deprecated. Use: bash deploy/k8s/uninstall.sh" >&2
exec bash "$PROJECT_ROOT/deploy/k8s/uninstall.sh" "$@"
