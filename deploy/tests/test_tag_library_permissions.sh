#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATION_FILE="$DEPLOY_ROOT/sql/migrations/v2.5.2_unified_tag_management.sql"
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

  for grant in \
    "41, 'SU'" \
    "92, 'ADMIN'" \
    "229, 'SPEED'" \
    "230, 'ASSET_OWNER'"; do
    printf '%s\n' "$block" | grep -Fq "($grant, 'RESOURCE', 'TAG_LIBRARY', 'MANAGE')" \
      || fail "missing reserved grant ($grant) in $file"
  done

  if printf '%s\n' "$block" | grep -Eq "'(DEV|USER)', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'"; then
    fail "DEV or USER management grant found in $file"
  fi
}

[ -f "$MIGRATION_FILE" ] || fail "migration file missing"
grep -Fq 'BEGIN;' "$MIGRATION_FILE" || fail "migration must begin a transaction"
grep -Fq 'COMMIT;' "$MIGRATION_FILE" || fail "migration must commit a transaction"
assert_seed_contract "$MIGRATION_FILE"
if [ -n "$(seed_block "$INIT_FILE")" ]; then
  fail "init.sql must not contain migration-only tag library permission grants"
fi

sequence_line="$(grep -nF "pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id')" "$MIGRATION_FILE" | head -1 | cut -d: -f1)"
seed_line="$(grep -nF 'tag-library-permission-seed:start' "$MIGRATION_FILE" | head -1 | cut -d: -f1)"
[ -n "$sequence_line" ] || fail "role permission sequence repair missing from migration"
seed_end_line="$(grep -nF 'tag-library-permission-seed:end' "$MIGRATION_FILE" | head -1 | cut -d: -f1)"
[ "$sequence_line" -gt "$seed_line" ] || fail "role permission sequence must be repaired after explicit grants are inserted"
[ "$sequence_line" -lt "$seed_end_line" ] || fail "role permission sequence repair must remain inside the seed block"

echo "Tag library permission seed contract passed."
