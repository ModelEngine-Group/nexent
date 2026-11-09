#!/bin/bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../common/common.sh"
status=0
display_password="${2:-true}"
docker exec -i nexent-config python -m management.cli.account bootstrap-su --check >/dev/null || status=$?
case "$status" in
  0) exit 0 ;;
  3) ;;
  *) echo "Super administrator check failed. Inspect the command output above before retrying." >&2; exit "$status" ;;
esac
password="${1:-$(deployment_super_admin_password)}"
result="$(printf '%s\n' "$password" | docker exec -i nexent-config python -m management.cli.account bootstrap-su)"
deployment_report_super_admin_creation "$result" "$password" "$display_password"
unset result
unset password
