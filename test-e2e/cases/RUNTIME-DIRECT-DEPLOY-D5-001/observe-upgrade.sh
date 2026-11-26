#!/bin/bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

set -eu
case "${0##*/}" in
    helm)
        if [[ "${1:-}" == upgrade ]]; then
            release="${2:-}"
            [[ "$release" != --install ]] || release="${3:-}"
            paused=""
            replicas=""
            for argument; do
                case "$argument" in
                    global.businessPaused=*) paused="${argument#*=}" ;;
                    nexent-runtime.replicaCount=*) replicas="${argument#*=}" ;;
                esac
            done
            [[ "$release" == nexent && "$paused" == false && "$replicas" =~ ^[1-9][0-9]*$ ]]
            printf '%s\n' "$replicas" >> "$D5_HELM_GATE/application-upgrades"
        fi
        exec "$D5_REAL_HELM" "$@"
        ;;
    kubectl)
        if [[ "${1:-}" == scale ]]; then
            touch "$D5_KUBECTL_GATE/forbidden-scale"
            exit 1
        fi
        exec "$D5_REAL_KUBECTL" "$@"
        ;;
esac
exit 1
