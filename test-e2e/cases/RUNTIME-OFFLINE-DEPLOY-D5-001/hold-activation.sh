#!/bin/bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -eu
if [[ "${1:-}" == upgrade && "${2:-}" == --install && "${3:-}" == nexent ]]; then
    for argument; do
        if [[ "$argument" == global.businessPaused=false ]]; then
            touch "$D5_HELM_GATE/arrived"
            while [ ! -f "$D5_HELM_GATE/decision" ]; do
                sleep 0.1
            done
            [ "$(cat "$D5_HELM_GATE/decision")" = allow ] || exit 1
            break
        fi
    done
fi
exec "$D5_REAL_HELM" "$@"
