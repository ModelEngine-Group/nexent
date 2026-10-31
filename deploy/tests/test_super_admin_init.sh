#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
# Native bootstrap transport tests. Database semantics are proved by AUTH-LOCAL-D2-001.
set -euo pipefail
TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/nexent-local-bootstrap.XXXXXX")"
EVENT_LOG="$TEST_TMP/events.log"
trap 'rm -f -- "$EVENT_LOG"; rmdir -- "$TEST_TMP"' EXIT
export EVENT_LOG

mock_account_command() {
  [ "${MSYS_NO_PATHCONV:-}" = 1 ] || { echo "Container path conversion is enabled" >&2; return 10; }
  [ "${MSYS2_ARG_CONV_EXCL:-}" = '*' ] || { echo "MSYS argument conversion is enabled" >&2; return 11; }
  if [ -n "${NEXENT_NATIVE_PATH_PROBE:-}" ]; then
    "$NEXENT_NATIVE_PATH_PROBE" -c 'import sys; assert "/opt/backend/account_admin.py" in sys.argv[1:], sys.argv[1:]' "$@" || return 12
  fi
  case "$*" in
    *"/opt/backend/account_admin.py bootstrap-su"*) ;;
    *) echo "Unexpected bootstrap command" >&2; return 9 ;;
  esac
  case "$*" in
    *--check*)
      printf 'check\n' >> "$EVENT_LOG"
      return "$MOCK_CHECK_STATUS"
      ;;
    *)
      local provided
      IFS= read -r provided
      [ "$provided" = "$MOCK_PASSWORD" ] || return 8
      printf 'create\n' >> "$EVENT_LOG"
      if [ -n "${MOCK_CREATE_RESULT:-}" ]; then
        printf '%s\n' "$MOCK_CREATE_RESULT"
      else
        printf '%s\n' '{"created":true}'
      fi
      return "${MOCK_CREATE_STATUS:-0}"
      ;;
  esac
}
docker() { mock_account_command "$@"; }
kubectl() { mock_account_command "$@"; }
export -f mock_account_command docker kubectl
MOCK_PASSWORD="BootstrapPass123'"
NEXENT_SUPER_ADMIN_PASSWORD="$MOCK_PASSWORD"
NEXENT_DEPLOY_CONFIG_MODE=defaults
export MOCK_PASSWORD NEXENT_SUPER_ADMIN_PASSWORD NEXENT_DEPLOY_CONFIG_MODE

for script in "$TEST_ROOT/deploy/docker/create-su.sh" "$TEST_ROOT/deploy/k8s/create-suadmin.sh"; do
  : > "$EVENT_LOG"
  MOCK_CHECK_STATUS=0
  export MOCK_CHECK_STATUS
  output="$(bash "$script" "$MOCK_PASSWORD")"
  [ "$(cat "$EVENT_LOG")" = check ]
  [[ "$output" != *"$MOCK_PASSWORD"* ]]

  : > "$EVENT_LOG"
  MOCK_CHECK_STATUS=3
  export MOCK_CHECK_STATUS
  output="$(bash "$script" "$MOCK_PASSWORD")"
  [ "$(cat "$EVENT_LOG")" = $'check\ncreate' ]
  [[ "$output" == *"$MOCK_PASSWORD"* ]]
  [[ "$output" == *"suadmin@nexent.com"* ]]

  output="$(bash "$script" "$MOCK_PASSWORD" false)"
  [[ "$output" != *"$MOCK_PASSWORD"* ]]

  MOCK_CREATE_RESULT='{"exists":true}'
  export MOCK_CREATE_RESULT
  output="$(bash "$script" "$MOCK_PASSWORD")"
  [[ "$output" != *"$MOCK_PASSWORD"* ]]
  unset MOCK_CREATE_RESULT

  MOCK_CREATE_STATUS=1
  export MOCK_CREATE_STATUS
  if output="$(bash "$script" "$MOCK_PASSWORD")"; then
    echo "Creation failure must abort bootstrap" >&2
    exit 1
  fi
  [[ "$output" != *"$MOCK_PASSWORD"* ]]
  unset MOCK_CREATE_STATUS

  : > "$EVENT_LOG"
  MOCK_CHECK_STATUS=1
  export MOCK_CHECK_STATUS
  if bash "$script" "$MOCK_PASSWORD" >/dev/null 2>&1; then
    echo "Conflict/schema failure must abort bootstrap" >&2
    exit 1
  fi
  [ "$(cat "$EVENT_LOG")" = check ]
done
# Exercise the actual deployment precheck without running deployment main().
eval "$(sed -n '/^check_super_admin_user_exists() {/,/^}/p' "$TEST_ROOT/deploy/docker/deploy.sh")"
for MOCK_CHECK_STATUS in 0 3 1; do
  export MOCK_CHECK_STATUS
  : > "$EVENT_LOG"
  actual=0
  check_super_admin_user_exists || actual=$?
  [ "$actual" = "$MOCK_CHECK_STATUS" ]
  [ "$(cat "$EVENT_LOG")" = check ]
done
printf 'Native super administrator bootstrap tests passed.\n'
