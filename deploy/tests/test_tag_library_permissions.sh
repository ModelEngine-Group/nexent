#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATION_FILE="$DEPLOY_ROOT/sql/migrations/v2.5.1_0817_tag_library_permissions.sql"
INIT_FILE="$DEPLOY_ROOT/sql/init.sql"

fail() {
  echo "FAIL: $*"
  exit 1
}

seed_block() {
  sed -n '/tag-library-permission-seed:start/,/tag-library-permission-seed:end/p' "$1"
}

assert_seed_contract() {
  local file="$1"
  local block
  block="$(seed_block "$file")"

  [ -n "$block" ] || fail "tag-library permission seed block missing from $file"
  printf '%s\n' "$block" | grep -Fq "permission_category = 'RESOURCE'" \
    || fail "RESOURCE category missing from $file"
  printf '%s\n' "$block" | grep -Fq "permission_type = 'TAG_LIBRARY'" \
    || fail "TAG_LIBRARY type missing from $file"
  printf '%s\n' "$block" | grep -Fq "permission_subtype = 'MANAGE'" \
    || fail "MANAGE subtype missing from $file"
  printf '%s\n' "$block" | grep -Fq 'WHERE NOT EXISTS' \
    || fail "idempotent insert guard missing from $file"

  for role in SU ADMIN SPEED ASSET_OWNER; do
    printf '%s\n' "$block" | grep -Fq "('$role', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE')" \
      || fail "missing $role grant in $file"
  done

  if printf '%s\n' "$block" | grep -Eq "\('(DEV|USER)', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'\)"; then
    fail "DEV or USER management grant found in $file"
  fi
}

[ -f "$MIGRATION_FILE" ] || fail "migration file missing"
grep -Fq 'BEGIN;' "$MIGRATION_FILE" || fail "migration must begin a transaction"
grep -Fq 'COMMIT;' "$MIGRATION_FILE" || fail "migration must commit a transaction"
assert_seed_contract "$MIGRATION_FILE"
assert_seed_contract "$INIT_FILE"

echo "Tag library permission seed contract passed."
