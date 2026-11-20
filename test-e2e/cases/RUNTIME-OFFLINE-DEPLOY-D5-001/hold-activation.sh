#!/bin/bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -eu
if [[ "${1:-}" == upgrade && "${2:-}" == --install && "${3:-}" == nexent ]]; then
    activate=false
    epoch=''
    for argument; do
        case "$argument" in
            global.businessPaused=false) activate=true ;;
            global.maintenanceEpoch=*) epoch="${argument#*=}" ;;
        esac
    done
    if "$activate"; then
        printf '%s\n' "$epoch" > "$D5_HELM_GATE/arrived.tmp"
        mv "$D5_HELM_GATE/arrived.tmp" "$D5_HELM_GATE/arrived"
        while [ ! -f "$D5_HELM_GATE/decision" ]; do
            sleep 0.1
        done
        [ "$(cat "$D5_HELM_GATE/decision")" = allow ] || exit 1
    fi
fi
exec "$D5_REAL_HELM" "$@"
