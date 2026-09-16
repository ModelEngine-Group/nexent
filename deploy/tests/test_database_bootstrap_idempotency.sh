#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION="$SCRIPT_DIR/../sql/migrations/v2.6.0_merged_migrations.sql"
# The v2.5.2 tag management section embeds the trigger function once, and the
# v2.5.3 idempotency correction redefines it once more, so the merged file
# contains exactly two definitions.
TRIGGER_FN='CREATE OR REPLACE FUNCTION nexent.provision_unified_tag_management_after_user_tenant_insert()'
TRIGGER_FN_COUNT=2

fail() { echo "FAIL: $*"; exit 1; }

[ -f "$MIGRATION" ] || fail "corrective migration missing"
grep -Fq "pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id')" "$MIGRATION" || fail "permission sequence is not synchronized"
grep -Fq "COALESCE(MAX(role_permission_id), 1)" "$MIGRATION" || fail "sequence does not use the current maximum"
grep -Fq "NULLIF(btrim(NEW.tenant_id), '') IS NOT NULL" "$MIGRATION" || fail "reserved empty tenant mapping is not skipped"
[ "$(grep -Fc "$TRIGGER_FN" "$MIGRATION")" -eq "$TRIGGER_FN_COUNT" ] || fail "trigger function correction is not idempotent"
grep -Fq 'BEGIN;' "$MIGRATION" || fail "migration transaction missing"
grep -Fq 'COMMIT;' "$MIGRATION" || fail "migration commit missing"

echo "Database bootstrap idempotency contract passed."
