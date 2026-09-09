#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION="$SCRIPT_DIR/../sql/migrations/v2.5.3_database_bootstrap_idempotency.sql"

fail() { echo "FAIL: $*"; exit 1; }

[ -f "$MIGRATION" ] || fail "corrective migration missing"
grep -Fq "pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id')" "$MIGRATION" || fail "permission sequence is not synchronized"
grep -Fq "COALESCE(MAX(role_permission_id), 1)" "$MIGRATION" || fail "sequence does not use the current maximum"
grep -Fq "NULLIF(btrim(NEW.tenant_id), '') IS NOT NULL" "$MIGRATION" || fail "reserved empty tenant mapping is not skipped"
[ "$(grep -Fc 'CREATE OR REPLACE FUNCTION nexent.provision_unified_tag_management_after_user_tenant_insert()' "$MIGRATION")" -eq 1 ] || fail "trigger function correction is not idempotent"
grep -Fq 'BEGIN;' "$MIGRATION" || fail "migration transaction missing"
grep -Fq 'COMMIT;' "$MIGRATION" || fail "migration commit missing"

echo "Database bootstrap idempotency contract passed."
