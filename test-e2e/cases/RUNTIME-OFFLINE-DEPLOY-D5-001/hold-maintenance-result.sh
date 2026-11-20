#!/bin/bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -eu
if [[ $# -ge 13 && "$1 $2 $3 $4 $5 $6 $7 $8 $9 ${10}" == 'exec -i -n nexent deployment/nexent-postgresql -c postgresql -- sh -c' &&
      "${12}" == runtime-deploy-lock && "${13}" == psql ]]; then
    exec "$D5_REAL_KUBECTL" "${@:1:8}" env "PGAPPNAME=$D5_KUBECTL_LOCK_NAME" "${@:9}"
fi

if [[ $# == 7 && "$1 $2 $4 $5 $6" == 'get job -n nexent -o' &&
      "$3" =~ ^nexent-runtime-maintenance-([0-9a-f-]{36})$ &&
      "$7" == 'jsonpath={.status.succeeded}:{.status.failed}' ]]; then
    epoch="${BASH_REMATCH[1]}"
    status=$("$D5_REAL_KUBECTL" "$@")
    if [[ "$status" == '1:' || "$status" == '1:0' ]]; then
        printf '%s\n' "$epoch" > "$D5_KUBECTL_GATE/maintenance-arrived.tmp"
        mv "$D5_KUBECTL_GATE/maintenance-arrived.tmp" "$D5_KUBECTL_GATE/maintenance-arrived"
        while [ ! -f "$D5_KUBECTL_GATE/maintenance-decision" ]; do
            sleep 0.1
        done
        [ "$(cat "$D5_KUBECTL_GATE/maintenance-decision")" = allow ] || exit 1
    fi
    printf '%s' "$status"
else
    exec "$D5_REAL_KUBECTL" "$@"
fi
