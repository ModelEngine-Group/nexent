#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -euo pipefail

requested_umask="${UMASK:-0022}"
if [[ ! "$requested_umask" =~ ^0?[0-7]{3}$ ]]; then
  printf '[start-ops] ERROR: unsupported UMASK: %s\n' "$requested_umask" >&2
  exit 1
fi
umask "$requested_umask"

# Only the Ops service owns initialization of its control database.
if [[ "${OPS_MONITORING_ENABLED:-true}" =~ ^([Tt][Rr][Uu][Ee])$ ]]; then
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  bash "$script_dir/run-ops-sql-migrations.sh" --migrate
fi

exec "$@"
