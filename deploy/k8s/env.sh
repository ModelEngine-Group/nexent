#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

# Render trusted shell-compatible env files without dumping the host environment.

k8s_env_file_data() {
    local nexent_env_input="$1"
    local nexent_env_indent="${2:-0}"
    local nexent_env_helper
    local nexent_env_data
    nexent_env_helper="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

    if ! nexent_env_data="$(bash --noprofile --norc -e -o pipefail "$nexent_env_helper" --load \
        "$nexent_env_input" "$nexent_env_indent" 2>/dev/null)"; then
        printf 'Error: failed to load environment file: %s\n' "$nexent_env_input" >&2
        return 1
    fi
    printf '%s\n' "$nexent_env_data"
}

k8s_load_env_file_data() {
    local nexent_env_input="$1"
    local nexent_env_indent="$2"
    local nexent_env_keys=()
    local nexent_env_key nexent_env_encoded nexent_env_padding

    [ -f "$nexent_env_input" ] && [ -r "$nexent_env_input" ] || return 1
    [[ "$nexent_env_indent" =~ ^[0-9]+$ ]] || return 1

    # DEBUG observes complete Bash assignment commands, including multiline
    # values. A line scanner would mistake assignment-looking value text for keys.
    set -a
    set -T
    trap 'if [[ "$BASH_COMMAND" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)= ]]; then nexent_env_keys+=("${BASH_REMATCH[2]}"); fi' DEBUG
    # shellcheck source=/dev/null
    source "$nexent_env_input" >/dev/null 2>&1
    trap - DEBUG
    set +T
    set +a

    nexent_env_padding="$(printf '%*s' "$nexent_env_indent" '')"
    if [ "${#nexent_env_keys[@]}" -eq 0 ]; then
        printf '%s{}\n' "$nexent_env_padding"
        return 0
    fi
    while IFS= read -r nexent_env_key; do
        [ "${!nexent_env_key+x}" = x ] || continue
        nexent_env_encoded="$(printf '%s' "${!nexent_env_key}" | base64 | tr -d '\r\n')"
        printf '%s%s: "%s"\n' "$nexent_env_padding" "$nexent_env_key" "$nexent_env_encoded"
    done < <(printf '%s\n' "${nexent_env_keys[@]}" | LC_ALL=C sort -u)
}

k8s_write_private_values() (
    local nexent_values_output="$1"
    local nexent_values_temporary
    umask 077
    nexent_values_temporary="$(mktemp "${nexent_values_output}.XXXXXX")" || return 1
    trap 'rm -f "$nexent_values_temporary"' EXIT
    cat > "$nexent_values_temporary" || return 1
    chmod 600 "$nexent_values_temporary" || return 1
    mv -f "$nexent_values_temporary" "$nexent_values_output"
)

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    set -e
    if [ "${1:-}" != --load ] || [ "$#" -ne 3 ]; then
        echo 'Usage: env.sh --load ENV_FILE INDENT' >&2
        exit 1
    fi
    k8s_load_env_file_data "$2" "$3"
fi
