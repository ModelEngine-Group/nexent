#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat <<'NOTICE'
[WARN] docker/upgrade.sh is deprecated.
[WARN] Use deploy/docker/deploy.sh for both first install and upgrade.
[WARN] This compatibility wrapper does not delete Docker volumes.
NOTICE

exec bash "$SCRIPT_DIR/deploy.sh" "$@"
