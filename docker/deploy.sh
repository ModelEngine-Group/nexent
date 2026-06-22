#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "[WARN] docker/deploy.sh is deprecated. Use: bash deploy.sh docker" >&2
exec bash "$PROJECT_ROOT/deploy/docker/deploy.sh" "$@"
