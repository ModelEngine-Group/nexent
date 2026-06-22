#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "[WARN] k8s/helm/deploy.sh is deprecated. Use: bash deploy.sh k8s" >&2
exec bash "$PROJECT_ROOT/deploy/k8s/deploy.sh" "$@"
