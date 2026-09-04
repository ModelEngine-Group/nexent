#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INIT_SQL="$DEPLOY_ROOT/sql/init.sql"
MIGRATION_SQL="$DEPLOY_ROOT/sql/migrations/v2.5.2_unified_tag_management.sql"
PREFLIGHT_SQL="$DEPLOY_ROOT/sql/preflight/unified_tag_management_preflight.sql"
POSTGRES_TEST_IMAGE="${POSTGRES_TEST_IMAGE:-postgres:15-alpine}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
POSTGRES_PASSWORD="utm-test-password"
CONTAINER_NAME="nexent-utm-test-$$-${RANDOM}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nexent-utm-test.XXXXXX")"
CONTAINER_STARTED=false

cleanup() {
  if [ "$CONTAINER_STARTED" = true ]; then
    "$DOCKER_BIN" stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [ "$actual" != "$expected" ]; then
    fail "$message (expected='$expected', actual='$actual')"
  fi
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    fail "$message (missing '$needle')"
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    fail "$message (unexpected '$needle')"
  fi
}

require_prerequisites() {
  command -v "$DOCKER_BIN" >/dev/null 2>&1 || fail "docker command not found: $DOCKER_BIN"
  [ -f "$INIT_SQL" ] || fail "init SQL not found: $INIT_SQL"
  [ -f "$MIGRATION_SQL" ] || fail "migration SQL not found: $MIGRATION_SQL"
  [ -f "$PREFLIGHT_SQL" ] || fail "preflight SQL not found: $PREFLIGHT_SQL"
}

run_migration_files_through() {
  local database="$1"
  local stop_at="$2"
  local migration_file
  while IFS= read -r migration_file; do
    run_file_with_search_path "$database" "$migration_file" >/dev/null
    if [ "$(basename "$migration_file")" = "$stop_at" ]; then
      return
    fi
  done < <(printf '%s\n' "$DEPLOY_ROOT"/sql/migrations/*.sql | sort -V)
  fail "migration boundary not found: $stop_at"
}

start_postgres() {
  "$DOCKER_BIN" run --rm -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    "$POSTGRES_TEST_IMAGE" >/dev/null
  CONTAINER_STARTED=true

  local attempt
  for attempt in {1..30}; do
    if "$DOCKER_BIN" exec "$CONTAINER_NAME" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
      pass "PostgreSQL container is ready ($POSTGRES_TEST_IMAGE)"
      return
    fi
    sleep 1
  done
  fail "PostgreSQL container did not become ready"
}

create_database() {
  local database="$1"
  "$DOCKER_BIN" exec "$CONTAINER_NAME" \
    psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres \
    -c "CREATE DATABASE \"$database\"" >/dev/null
}

run_sql() {
  local database="$1"
  "$DOCKER_BIN" exec -i "$CONTAINER_NAME" \
    psql -X -v ON_ERROR_STOP=1 -U postgres -d "$database" -A -t -q
}

run_file() {
  local database="$1"
  local file="$2"
  "$DOCKER_BIN" exec -i "$CONTAINER_NAME" \
    psql -X -v ON_ERROR_STOP=1 -U postgres -d "$database" -A -t -q < "$file"
}

run_file_with_search_path() {
  local database="$1"
  local file="$2"
  "$DOCKER_BIN" exec -e PGOPTIONS="-c search_path=nexent,public" -i "$CONTAINER_NAME" \
    psql -X -v ON_ERROR_STOP=1 -U root -d "$database" -A -t -q < "$file"
}

assert_query() {
  local database="$1"
  local sql="$2"
  local expected="$3"
  local message="$4"
  local actual
  actual="$(run_sql "$database" <<< "$sql")"
  assert_eq "$expected" "$actual" "$message"
}

expect_sql_failure() {
  local database="$1"
  local sql="$2"
  local expected_error="$3"
  local message="$4"
  local output
  if output="$(run_sql "$database" <<< "$sql" 2>&1)"; then
    fail "$message (statement unexpectedly succeeded)"
  fi
  assert_contains "$output" "$expected_error" "$message"
}

expect_migration_failure() {
  local database="$1"
  local expected_reason="$2"
  local output
  if output="$(run_file "$database" "$MIGRATION_SQL" 2>&1)"; then
    fail "migration unexpectedly succeeded for $database"
  fi
  assert_contains "$output" "Unified tag migration blocked" \
    "migration should fail closed for $database"
  assert_contains "$output" "$expected_reason" \
    "migration failure should report $expected_reason for $database"
}

expect_agent_category_migration_failure() {
  local database="$1"
  local expected_reason="$2"
  local output
  if output="$(run_file "$database" "$MIGRATION_SQL" 2>&1)"; then
    fail "Agent Category compatibility migration unexpectedly succeeded for $database"
  fi
  assert_contains "$output" "Agent category migration blocked" \
    "Agent Category compatibility migration should fail closed for $database"
  assert_contains "$output" "$expected_reason" \
    "Agent Category compatibility failure should report $expected_reason for $database"
}

run_concurrent_sql_pair() {
  local database="$1"
  local label="$2"
  local expected_error="$3"
  local sql_one="$4"
  local sql_two="$5"
  local log_one="$TMP_DIR/${label}-one.log"
  local log_two="$TMP_DIR/${label}-two.log"
  local pid_one pid_two status_one status_two successes combined

  set +e
  run_sql "$database" <<< "$sql_one" >"$log_one" 2>&1 &
  pid_one=$!
  run_sql "$database" <<< "$sql_two" >"$log_two" 2>&1 &
  pid_two=$!
  wait "$pid_one"
  status_one=$?
  wait "$pid_two"
  status_two=$?
  set -e

  successes=0
  if [ "$status_one" -eq 0 ]; then
    successes=$((successes + 1))
  fi
  if [ "$status_two" -eq 0 ]; then
    successes=$((successes + 1))
  fi
  assert_eq "1" "$successes" \
    "exactly one concurrent writer should claim the final $label slot"
  combined="$(cat "$log_one" "$log_two")"
  assert_contains "$combined" "$expected_error" \
    "losing concurrent $label writer should receive the expected error"
}

assert_schema_rolled_back() {
  local database="$1"
  assert_query "$database" \
    "SELECT COALESCE(to_regclass('nexent.tag_bucket')::TEXT, '');" \
    "" \
    "failed migration should roll back the unified tag schema"
}

create_legacy_schema() {
  local database="$1"
  run_sql "$database" <<'SQL'
CREATE SCHEMA nexent;

CREATE TABLE nexent.user_tenant_t (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100),
    created_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE nexent.ag_tool_info_t (
    tool_id INTEGER PRIMARY KEY,
    author VARCHAR(100),
    labels JSONB,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE nexent.ag_skill_info_t (
    skill_id INTEGER PRIMARY KEY,
    tenant_id VARCHAR(100),
    skill_tags JSON,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE nexent.ag_tenant_agent_t (
    agent_id INTEGER,
    tenant_id VARCHAR(100)
);

CREATE TABLE nexent.ag_agent_repository_t (
    agent_repository_id BIGINT PRIMARY KEY,
    publisher_tenant_id VARCHAR(100),
    agent_id INTEGER,
    tags TEXT[],
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE nexent.ag_skill_repository_t (
    skill_repository_id BIGINT PRIMARY KEY,
    publisher_tenant_id VARCHAR(100),
    skill_id INTEGER,
    tags TEXT[],
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE nexent.mcp_record_t (
    mcp_id INTEGER PRIMARY KEY,
    tenant_id VARCHAR(100),
    tags TEXT[],
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE nexent.mcp_community_record_t (
    community_id INTEGER PRIMARY KEY,
    tenant_id VARCHAR(100),
    tags TEXT[],
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE nexent.mcp_market_record_t (
    market_id BIGINT PRIMARY KEY,
    tenant_id VARCHAR(100),
    source_mcp_id INTEGER,
    tags TEXT[],
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE TABLE nexent.role_permission_t (
    role_permission_id SERIAL PRIMARY KEY,
    user_role VARCHAR(100),
    permission_category VARCHAR(100),
    permission_type VARCHAR(100),
    permission_subtype VARCHAR(100)
);
SQL
}

test_preflight_before_tag_schema() {
  local database="utm_preflight"
  local output
  create_database "$database"
  create_legacy_schema "$database"

  output="$(run_file "$database" "$PREFLIGHT_SQL")"
  assert_contains "$output" "no_document_legacy_column_found" \
    "preflight should emit the document sentinel before tag schema exists"
  assert_contains "$output" "structured_schema_not_installed" \
    "preflight should skip structured checks before tag schema exists"
  assert_query "$database" \
    "SELECT COALESCE(to_regclass('nexent.tag_bucket')::TEXT, '');" "" \
    "read-only preflight must not create tag schema"
  pass "preflight runs before tag schema and returns the document sentinel"
}

test_empty_legacy_provisions_final_tag_library() {
  local database="utm_empty"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t (tenant_id, created_by, delete_flag)
VALUES ('tenant-empty', 'owner-empty', 'N');
SQL

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" \
    "SELECT (SELECT count(*) FROM nexent.tag_bucket) || '|' || (SELECT count(*) FROM nexent.tag_bucket_resource_type) || '|' || (SELECT count(*) FROM nexent.tag_definition) || '|' || (SELECT count(*) FROM nexent.tag_value);" \
    "2|6|1|20" \
    "empty legacy data should create final buckets, bindings, and Agent Category presets"

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" \
    "SELECT (SELECT count(*) FROM nexent.tag_bucket) || '|' || (SELECT count(*) FROM nexent.tag_bucket_resource_type) || '|' || (SELECT count(*) FROM nexent.tag_definition) || '|' || (SELECT count(*) FROM nexent.tag_value);" \
    "2|6|1|20" \
    "empty migration rerun should remain duplicate-free"
  pass "empty legacy tenant provisions the final tag library and reruns idempotently"
}

test_tag_library_permission_ids_and_legacy_normalization() {
  local database="utm_permission_ids"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" >/dev/null <<'SQL'
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) VALUES
    (1605, 'SU', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
    (1606, 'ADMIN', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
    (1607, 'SPEED', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE'),
    (1608, 'ASSET_OWNER', 'RESOURCE', 'TAG_LIBRARY', 'MANAGE');

SELECT setval('nexent.role_permission_t_role_permission_id_seq', 1608, TRUE);
SQL

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" \
    "SELECT string_agg(role_permission_id || ':' || user_role, ',' ORDER BY role_permission_id) FROM nexent.role_permission_t WHERE permission_category = 'RESOURCE' AND permission_type = 'TAG_LIBRARY' AND permission_subtype = 'MANAGE';" \
    "41:SU,92:ADMIN,229:SPEED,230:ASSET_OWNER" \
    "legacy generated permission IDs should normalize to the reserved IDs"
  assert_query "$database" \
    "SELECT (last_value >= (SELECT max(role_permission_id) FROM nexent.role_permission_t))::TEXT FROM nexent.role_permission_t_role_permission_id_seq;" \
    "true" "permission sequence must not lag behind explicit IDs"

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" \
    "SELECT string_agg(role_permission_id || ':' || user_role, ',' ORDER BY role_permission_id) FROM nexent.role_permission_t WHERE permission_category = 'RESOURCE' AND permission_type = 'TAG_LIBRARY' AND permission_subtype = 'MANAGE';" \
    "41:SU,92:ADMIN,229:SPEED,230:ASSET_OWNER" \
    "permission ID normalization should remain idempotent"
  pass "TAG_LIBRARY permissions use reserved IDs and normalize legacy generated IDs"
}

test_tag_library_permission_id_conflict_rolls_back() {
  local database="utm_permission_id_conflict"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) VALUES (
    41, 'DEV', 'RESOURCE', 'MODEL', 'READ'
);
SQL

  expect_migration_failure "$database" "tag_library_permission_id_conflict"
  assert_schema_rolled_back "$database"
  assert_query "$database" \
    "SELECT role_permission_id || ':' || user_role || ':' || permission_type FROM nexent.role_permission_t;" \
    "41:DEV:MODEL" "permission ID conflict rollback must preserve the existing permission"
  pass "occupied reserved TAG_LIBRARY permission IDs fail closed and roll back"
}

test_valid_legacy_backfill_and_idempotency() {
  local database="utm_valid"
  local preflight_output
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t (tenant_id, created_by, delete_flag)
VALUES ('tenant-valid', 'owner-valid', 'N');

INSERT INTO nexent.ag_tool_info_t VALUES
    (10, 'tenant-valid', '[" Alpha ", "alpha", "ALPHA", "ToolOnly"]'::JSONB, 'N');
INSERT INTO nexent.ag_skill_info_t VALUES
    (20, 'tenant-valid', '["SkillTag"]'::JSON, 'N');
INSERT INTO nexent.ag_tenant_agent_t VALUES (30, 'tenant-valid');
INSERT INTO nexent.ag_agent_repository_t VALUES
    (31, 'tenant-valid', 30, ARRAY['AgentTag'], 'N');
INSERT INTO nexent.ag_skill_repository_t VALUES
    (21, 'tenant-valid', 20, ARRAY['RepoSkillTag'], 'N');
INSERT INTO nexent.mcp_record_t VALUES
    (40, 'tenant-valid', ARRAY['McpTag'], 'N');
INSERT INTO nexent.mcp_community_record_t VALUES
    (41, 'tenant-valid', ARRAY[]::TEXT[], 'N');
INSERT INTO nexent.mcp_market_record_t VALUES
    (42, 'tenant-valid', 40, ARRAY['MarketTag'], 'N');
SQL

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_definition WHERE definition_key = 'keywords' AND definition_name = 'Keywords' AND selection_mode = 'multi_select';" \
    "1" "valid legacy values should create one Keywords definition"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_value;" "27" \
    "legacy values should be deduplicated alongside 20 Agent Category presets"
  assert_query "$database" \
    "SELECT normalized_value || '|' || display_value FROM nexent.tag_value WHERE normalized_value = 'alpha';" \
    "alpha|ALPHA" \
    "display value should be the deterministic C-collation minimum"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.resource_tag_assignment;" "7" \
    "all valid canonical and marketplace sources should create assignments"
  assert_query "$database" \
    "SELECT string_agg(resource_type || ':' || item_count, ',' ORDER BY resource_type) FROM (SELECT resource_type, count(*) AS item_count FROM nexent.resource_tag_assignment GROUP BY resource_type) AS counts;" \
    "agent:1,mcp_service:2,skill:2,tool:2" \
    "backfill should cover Tool, Skill, Agent repository, Skill repository, local MCP, and market MCP"
  assert_query "$database" \
    "SELECT labels::TEXT FROM nexent.ag_tool_info_t WHERE tool_id = 10;" \
    "[\" Alpha \", \"alpha\", \"ALPHA\", \"ToolOnly\"]" \
    "successful migration must preserve legacy values"

  preflight_output="$(run_file "$database" "$PREFLIGHT_SQL")"
  assert_contains "$preflight_output" "structured_capacity" \
    "post-migration preflight should execute structured capacity checks"
  assert_not_contains "$preflight_output" "legacy_missing_assignment" \
    "post-migration preflight should find no missing legacy assignments"
  assert_not_contains "$preflight_output" "assignment_missing_legacy_source" \
    "post-migration preflight should find no assignments without legacy sources"

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" \
    "SELECT (SELECT count(*) FROM nexent.tag_bucket) || '|' || (SELECT count(*) FROM nexent.tag_bucket_resource_type) || '|' || (SELECT count(*) FROM nexent.tag_definition) || '|' || (SELECT count(*) FROM nexent.tag_value) || '|' || (SELECT count(*) FROM nexent.resource_tag_assignment);" \
    "2|6|2|27|7" \
    "valid migration rerun should not create duplicates"
  pass "valid legacy sources normalize into deterministic Keywords values and rerun idempotently"
}

test_agent_category_compatibility_and_future_tenant_provisioning() {
  local database="utm_agent_category"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t (tenant_id, created_by, delete_flag)
VALUES ('tenant-category', 'owner-category', 'N');

INSERT INTO nexent.ag_tenant_agent_t VALUES
    (30, 'tenant-category'),
    (31, 'tenant-category'),
    (32, 'tenant-category'),
    (33, 'tenant-category');

INSERT INTO nexent.ag_agent_repository_t VALUES
    (301, 'tenant-category', 30,
     ARRAY['营销', 'Content Creation', 'code_review', 'CustomOnly', '营销'], 'N'),
    (302, 'tenant-category', 31,
     ARRAY['Customer Support', 'Ticketing', 'Color Scheme', 'Marketing'], 'N'),
    (303, 'tenant-category', 32, ARRAY['OnlyCustom'], 'N'),
    (304, 'tenant-category', 33, ARRAY['数据'], 'Y');

ALTER TABLE nexent.ag_agent_repository_t ADD COLUMN category_id INTEGER;
UPDATE nexent.ag_agent_repository_t SET category_id = 1 WHERE agent_repository_id = 301;
SQL

  run_file "$database" "$MIGRATION_SQL" >/dev/null

  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_definition WHERE tenant_id = 'tenant-category' AND definition_key = 'agent_category' AND delete_flag = 'N';" \
    "1" "compatibility migration should provision one Agent Category definition"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.tenant_id = 'tenant-category' AND definition.definition_key = 'agent_category' AND value.delete_flag = 'N';" \
    "20" "compatibility migration should provision all 20 Agent Category values"
  assert_query "$database" \
    "SELECT string_agg(value.normalized_value, ',' ORDER BY value.normalized_value) FROM nexent.resource_tag_assignment AS assignment JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) JOIN nexent.tag_value AS value USING (tenant_id, definition_id, value_id) WHERE assignment.tenant_id = 'tenant-category' AND assignment.resource_type = 'agent' AND assignment.resource_id = '30' AND definition.definition_key = 'agent_category' AND assignment.delete_flag = 'N';" \
    "code_review,content_creation,marketing" \
    "Chinese, English, and stable-key aliases should map to Agent Category values"
  assert_query "$database" \
    "SELECT string_agg(value.normalized_value, ',' ORDER BY value.normalized_value) FROM nexent.resource_tag_assignment AS assignment JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) JOIN nexent.tag_value AS value USING (tenant_id, definition_id, value_id) WHERE assignment.tenant_id = 'tenant-category' AND assignment.resource_type = 'agent' AND assignment.resource_id = '31' AND definition.definition_key = 'agent_category' AND assignment.delete_flag = 'N';" \
    "color_scheme,customer_service,marketing,ticket" \
    "known English display aliases should map to stable Agent Category values"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.resource_tag_assignment AS assignment JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE assignment.tenant_id = 'tenant-category' AND assignment.resource_type = 'agent' AND assignment.resource_id IN ('32', '33') AND definition.definition_key = 'agent_category' AND assignment.delete_flag = 'N';" \
    "0" "custom-only and soft-deleted repository rows should not activate Agent Category values"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.resource_tag_assignment AS assignment JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) JOIN nexent.tag_value AS value USING (tenant_id, definition_id, value_id) WHERE assignment.tenant_id = 'tenant-category' AND assignment.resource_id = '30' AND definition.definition_key = 'keywords' AND value.normalized_value = 'customonly' AND assignment.delete_flag = 'N';" \
    "1" "custom Agent tags should remain available under Keywords"
  assert_query "$database" \
    "SELECT tags::TEXT FROM nexent.ag_agent_repository_t WHERE agent_repository_id = 301;" \
    "{营销,\"Content Creation\",code_review,CustomOnly,营销}" \
    "Agent Category projection must preserve the legacy repository tags"
  assert_query "$database" \
    "SELECT category_id FROM nexent.ag_agent_repository_t WHERE agent_repository_id = 301;" \
    "1" "the removed category_id taxonomy should remain unchanged"

  run_file "$database" "$MIGRATION_SQL" >/dev/null
  assert_query "$database" \
    "SELECT count(*) FROM nexent.resource_tag_assignment AS assignment JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE assignment.tenant_id = 'tenant-category' AND definition.definition_key = 'agent_category' AND assignment.delete_flag = 'N';" \
    "7" "Agent Category compatibility migration should rerun without duplicates"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t (tenant_id, created_by, delete_flag)
VALUES ('tenant-after-upgrade', 'owner-after-upgrade', 'N');
SQL
  assert_query "$database" \
    "SELECT (SELECT count(*) FROM nexent.tag_bucket WHERE tenant_id = 'tenant-after-upgrade' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_bucket_resource_type WHERE tenant_id = 'tenant-after-upgrade' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_definition WHERE tenant_id = 'tenant-after-upgrade' AND definition_key = 'agent_category' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.tenant_id = 'tenant-after-upgrade' AND definition.definition_key = 'agent_category' AND value.delete_flag = 'N');" \
    "2|6|1|20" \
    "a tenant created after the complete upgrade chain should receive Agent Category immediately"
  pass "Agent preset aliases migrate to Agent Category and future tenants use the restored provisioner"
}

test_agent_category_capacity_conflict_rolls_back() {
  local database="utm_agent_category_capacity"
  local preflight_output
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t (tenant_id, created_by, delete_flag)
VALUES ('tenant-category-capacity', 'owner-category-capacity', 'N');
INSERT INTO nexent.ag_tenant_agent_t VALUES (50, 'tenant-category-capacity');
INSERT INTO nexent.ag_agent_repository_t (
    agent_repository_id, publisher_tenant_id, agent_id, tags, delete_flag
)
SELECT 501, 'tenant-category-capacity', 50,
       array_agg(CASE WHEN item = 1 THEN '营销' ELSE 'custom-' || item::TEXT END ORDER BY item),
       'N'
FROM generate_series(1, 100) AS series(item);
SQL

  expect_agent_category_migration_failure "$database" "assignment-capacity"
  assert_query "$database" \
    "SELECT COALESCE(to_regclass('nexent.tag_bucket')::TEXT, '');" \
    "" "capacity conflict should roll back the complete consolidated tag migration"
  assert_query "$database" \
    "SELECT cardinality(tags) FROM nexent.ag_agent_repository_t WHERE agent_repository_id = 501;" \
    "100" "capacity conflict should preserve all legacy Agent repository tags"
  pass "Agent Category projection fails closed and rolls back the consolidated migration"
}

test_latest_init_and_tag_migration_order() {
  local database="utm_tag_upgrade_order"
  create_database "$database"
  run_sql "$database" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'root') THEN
        CREATE ROLE root LOGIN SUPERUSER;
    END IF;
END;
$$;
SQL
  run_file_with_search_path "$database" "$INIT_SQL" >/dev/null
  run_migration_files_through "$database" "v2.5.2_unified_tag_management.sql"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t (user_id, tenant_id, created_by, delete_flag)
VALUES ('user-complete-upgrade', 'tenant-complete-upgrade', 'user-complete-upgrade', 'N');
SQL
  assert_query "$database" \
    "SELECT (SELECT count(*) FROM nexent.tag_bucket WHERE tenant_id = 'tenant-complete-upgrade' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_bucket_resource_type WHERE tenant_id = 'tenant-complete-upgrade' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_definition WHERE tenant_id = 'tenant-complete-upgrade' AND definition_key = 'agent_category' AND delete_flag = 'N') || '|' || (SELECT count(*) FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.tenant_id = 'tenant-complete-upgrade' AND definition.definition_key = 'agent_category' AND value.delete_flag = 'N');" \
    "2|6|1|20" \
    "latest init followed by the relevant tag migration order should leave the final tenant provisioner active"
  pass "latest init plus the historical tag migration order preserves final tenant provisioning"
}

test_community_tags_fail_closed() {
  local database="utm_community"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-community', 'owner', 'N');
INSERT INTO nexent.mcp_community_record_t VALUES
    (1, 'tenant-community', ARRAY['CommunityTag'], 'N');
SQL

  expect_migration_failure "$database" "community_canonical_source_unprovable"
  assert_schema_rolled_back "$database"
  assert_query "$database" \
    "SELECT tags::TEXT FROM nexent.mcp_community_record_t WHERE community_id = 1;" \
    "{CommunityTag}" "community migration failure must preserve legacy tags"
  pass "non-empty community tags fail closed and roll back"
}

test_null_and_empty_tenant_roll_back() {
  local database="utm_bad_tenant"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.ag_tool_info_t VALUES
    (1, NULL, '["NullTenant"]'::JSONB, 'N');
INSERT INTO nexent.ag_skill_info_t VALUES
    (2, '', '["EmptyTenant"]'::JSON, 'N');
SQL

  expect_migration_failure "$database" "null_or_empty_tenant"
  assert_schema_rolled_back "$database"
  assert_query "$database" \
    "SELECT labels::TEXT FROM nexent.ag_tool_info_t WHERE tool_id = 1;" \
    "[\"NullTenant\"]" "NULL-tenant rollback must preserve tool labels"
  assert_query "$database" \
    "SELECT skill_tags::TEXT FROM nexent.ag_skill_info_t WHERE skill_id = 2;" \
    "[\"EmptyTenant\"]" "empty-tenant rollback must preserve skill tags"
  pass "NULL and empty legacy tenants roll back the entire migration"
}

test_non_string_json_roll_back() {
  local database="utm_bad_json"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-json', 'owner', 'N');
INSERT INTO nexent.ag_tool_info_t VALUES
    (1, 'tenant-json', '["ok", 1]'::JSONB, 'N');
SQL

  expect_migration_failure "$database" "json_array_contains_non_string"
  assert_schema_rolled_back "$database"
  assert_query "$database" \
    "SELECT labels::TEXT FROM nexent.ag_tool_info_t WHERE tool_id = 1;" \
    "[\"ok\", 1]" "non-string JSON rollback must preserve labels"
  pass "non-string legacy JSON fails closed and preserves legacy data"
}

test_source_mismatch_roll_back() {
  local database="utm_source_mismatch"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-source', 'owner', 'N');
INSERT INTO nexent.ag_tenant_agent_t VALUES (10, 'other-tenant');
INSERT INTO nexent.ag_agent_repository_t VALUES
    (11, 'tenant-source', 10, ARRAY['AgentMismatch'], 'N');
INSERT INTO nexent.mcp_market_record_t VALUES
    (12, 'tenant-source', 999, ARRAY['McpMismatch'], 'N');
SQL

  expect_migration_failure "$database" "canonical_source_missing_or_tenant_mismatch"
  assert_schema_rolled_back "$database"
  assert_query "$database" \
    "SELECT tags::TEXT FROM nexent.ag_agent_repository_t WHERE agent_repository_id = 11;" \
    "{AgentMismatch}" "source mismatch rollback must preserve agent repository tags"
  assert_query "$database" \
    "SELECT tags::TEXT FROM nexent.mcp_market_record_t WHERE market_id = 12;" \
    "{McpMismatch}" "source mismatch rollback must preserve market MCP tags"
  pass "canonical source mismatch rolls back all migration work"
}

test_value_capacity_preflight_roll_back() {
  local database="utm_value_overflow"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-values', 'owner', 'N');
INSERT INTO nexent.ag_tool_info_t (tool_id, author, labels, delete_flag)
SELECT ((item - 1) / 100) + 1,
       'tenant-values',
       jsonb_agg(to_jsonb('value-' || item::TEXT) ORDER BY item),
       'N'
FROM generate_series(1, 1001) AS series(item)
GROUP BY ((item - 1) / 100) + 1;
SQL

  expect_migration_failure "$database" "value_capacity_exceeded"
  assert_schema_rolled_back "$database"
  assert_query "$database" \
    "SELECT sum(jsonb_array_length(labels)) FROM nexent.ag_tool_info_t;" \
    "1001" "value overflow rollback must preserve all 1001 legacy values"
  pass "1001 projected values exceed the 1000 limit and roll back"
}

test_assignment_capacity_preflight_roll_back() {
  local database="utm_assignment_overflow"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-assignments', 'owner', 'N');
INSERT INTO nexent.ag_tool_info_t (tool_id, author, labels, delete_flag)
SELECT 1,
       'tenant-assignments',
       jsonb_agg(to_jsonb('assignment-' || item::TEXT) ORDER BY item),
       'N'
FROM generate_series(1, 101) AS series(item);
SQL

  expect_migration_failure "$database" "assignment_capacity_exceeded"
  assert_schema_rolled_back "$database"
  assert_query "$database" \
    "SELECT jsonb_array_length(labels) FROM nexent.ag_tool_info_t WHERE tool_id = 1;" \
    "101" "assignment overflow rollback must preserve all 101 legacy values"
  pass "101 projected assignments exceed the 100 limit and roll back"
}

test_indexes_and_hard_delete_semantics() {
  local database="utm_indexes_delete"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-delete', 'owner', 'N');
INSERT INTO nexent.ag_tool_info_t VALUES
    (1, 'tenant-delete', '["KeepMe"]'::JSONB, 'N');
SQL
  run_file "$database" "$MIGRATION_SQL" >/dev/null

  assert_query "$database" \
    "SELECT count(*) FROM pg_indexes WHERE schemaname = 'nexent' AND indexname IN ('idx_resource_tag_assignment_resource', 'idx_resource_tag_assignment_definition');" \
    "2" "both assignment lookup indexes should exist"
  assert_query "$database" \
    "SELECT count(*) FROM pg_index AS metadata JOIN pg_class AS index_class ON index_class.oid = metadata.indexrelid JOIN pg_namespace AS namespace ON namespace.oid = index_class.relnamespace WHERE namespace.nspname = 'nexent' AND index_class.relname IN ('uq_tag_definition_active_normalized_name', 'uq_tag_value_active_normalized_value') AND metadata.indisunique AND metadata.indpred IS NOT NULL;" \
    "2" "normalized definition/value indexes should be unique and partial"

  expect_sql_failure "$database" \
    "DELETE FROM nexent.tag_value WHERE tenant_id = 'tenant-delete' AND normalized_value = 'keepme';" \
    "foreign key constraint" \
    "hard delete should reject an in-use tag value"
  expect_sql_failure "$database" \
    "DELETE FROM nexent.tag_definition WHERE tenant_id = 'tenant-delete' AND definition_key = 'keywords';" \
    "foreign key constraint" \
    "hard delete should reject an in-use tag definition"
  assert_query "$database" \
    "SELECT (SELECT count(*) FROM nexent.tag_definition) || '|' || (SELECT count(*) FROM nexent.tag_value) || '|' || (SELECT count(*) FROM nexent.resource_tag_assignment);" \
    "2|21|1" "failed hard deletes must preserve built-in presets, definitions, values, and assignments"
  assert_query "$database" \
    "SELECT labels::TEXT FROM nexent.ag_tool_info_t WHERE tool_id = 1;" \
    "[\"KeepMe\"]" "failed hard deletes must preserve the legacy field"
  pass "required indexes exist and in-use hard deletes preserve assignments/legacy data"
}

test_trigger_boundaries_and_tenant_fks() {
  local database="utm_triggers"
  local preflight_output
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-trigger', 'owner', 'N');
SQL
  run_file "$database" "$MIGRATION_SQL" >/dev/null

  run_sql "$database" <<'SQL'
INSERT INTO nexent.tag_definition (
    tenant_id, bucket_id, definition_key, definition_name, selection_mode
)
SELECT 'tenant-trigger', bucket.bucket_id,
       'definition-' || item::TEXT,
       'Definition ' || item::TEXT,
       CASE WHEN item = 98 THEN 'single_select' ELSE 'multi_select' END
FROM nexent.tag_bucket AS bucket
CROSS JOIN generate_series(1, 98) AS series(item)
WHERE bucket.tenant_id = 'tenant-trigger'
  AND bucket.bucket_key = 'default_resource';
SQL
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_definition WHERE tenant_id = 'tenant-trigger';" \
    "99" "definition trigger should allow 98 user definitions plus the built-in preset"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.tag_definition (
    tenant_id, bucket_id, definition_key, definition_name, selection_mode
)
SELECT 'tenant-trigger', bucket_id, 'definition-99', 'Definition 99', 'multi_select'
FROM nexent.tag_bucket
WHERE tenant_id = 'tenant-trigger' AND bucket_key = 'default_resource';
SQL
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_definition WHERE tenant_id = 'tenant-trigger';" \
    "100" "definition trigger should allow the 100th definition including the built-in preset"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.ag_tool_info_t (tool_id, author, labels, delete_flag)
VALUES (100, 'tenant-trigger', '["ProjectedKeyword"]'::JSONB, 'N');
SQL
  preflight_output="$(run_file "$database" "$PREFLIGHT_SQL")"
  assert_contains "$preflight_output" "projected_definition_count" \
    "preflight should report the projected Keywords definition"
  assert_contains "$preflight_output" "101" \
    "preflight should project 101 definitions after adding Keywords"
  assert_contains "$preflight_output" '"exceeded": true' \
    "preflight should mark the projected definition limit as exceeded"
  run_sql "$database" <<'SQL'
UPDATE nexent.ag_tool_info_t
SET labels = '[]'::JSONB
WHERE tool_id = 100;
SQL
  run_sql "$database" <<'SQL'
UPDATE nexent.tag_definition
SET status = 'disabled'
WHERE tenant_id = 'tenant-trigger' AND definition_key = 'definition-96';
SQL
  expect_sql_failure "$database" \
    "INSERT INTO nexent.tag_definition (tenant_id, bucket_id, definition_key, definition_name, selection_mode) SELECT 'tenant-trigger', bucket_id, 'definition-100', 'Definition 100', 'multi_select' FROM nexent.tag_bucket WHERE tenant_id = 'tenant-trigger' AND bucket_key = 'default_resource';" \
    "Tag definition limit exceeded" \
    "disabled definitions should still count and reject the 101st definition"
  run_sql "$database" <<'SQL'
UPDATE nexent.tag_definition
SET delete_flag = 'Y'
WHERE tenant_id = 'tenant-trigger' AND definition_key = 'definition-97';

INSERT INTO nexent.tag_definition (
    tenant_id, bucket_id, definition_key, definition_name, selection_mode
)
SELECT 'tenant-trigger', bucket_id,
       'definition-97-rebuilt', 'Definition 97', 'multi_select'
FROM nexent.tag_bucket
WHERE tenant_id = 'tenant-trigger' AND bucket_key = 'default_resource';
SQL
  assert_query "$database" \
    "SELECT count(*) FILTER (WHERE delete_flag = 'N') || '|' || count(*) FILTER (WHERE normalized_name = 'definition 97') FROM nexent.tag_definition WHERE tenant_id = 'tenant-trigger';" \
    "100|2" \
    "soft-deleted definitions should not count and their normalized name should be reusable"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.tag_value (
    tenant_id, definition_id, normalized_value, display_value
)
SELECT 'tenant-trigger', definition.definition_id,
       'value-' || item::TEXT,
       'Value ' || item::TEXT
FROM nexent.tag_definition AS definition
CROSS JOIN generate_series(1, 999) AS series(item)
WHERE definition.tenant_id = 'tenant-trigger'
  AND definition.definition_key = 'definition-1';
SQL
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.definition_key = 'definition-1';" \
    "999" "value trigger should allow 999 values"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.tag_value (tenant_id, definition_id, normalized_value, display_value)
SELECT 'tenant-trigger', definition_id, 'value-1000', 'Value 1000'
FROM nexent.tag_definition
WHERE tenant_id = 'tenant-trigger' AND definition_key = 'definition-1';
SQL
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.definition_key = 'definition-1';" \
    "1000" "value trigger should allow the 1000th value"
  run_sql "$database" <<'SQL'
UPDATE nexent.tag_value AS value
SET status = 'disabled'
FROM nexent.tag_definition AS definition
WHERE definition.tenant_id = value.tenant_id
  AND definition.definition_id = value.definition_id
  AND definition.definition_key = 'definition-1'
  AND value.normalized_value = 'value-997';
SQL
  expect_sql_failure "$database" \
    "INSERT INTO nexent.tag_value (tenant_id, definition_id, normalized_value, display_value) SELECT 'tenant-trigger', definition_id, 'value-1001', 'Value 1001' FROM nexent.tag_definition WHERE tenant_id = 'tenant-trigger' AND definition_key = 'definition-1';" \
    "Tag value limit exceeded" \
    "disabled values should still count and reject the 1001st value"
  run_sql "$database" <<'SQL'
UPDATE nexent.tag_value AS value
SET delete_flag = 'Y'
FROM nexent.tag_definition AS definition
WHERE definition.tenant_id = value.tenant_id
  AND definition.definition_id = value.definition_id
  AND definition.definition_key = 'definition-1'
  AND value.normalized_value = 'value-998';

INSERT INTO nexent.tag_value (
    tenant_id, definition_id, normalized_value, display_value
)
SELECT 'tenant-trigger', definition_id, 'value-998', 'Value 998 rebuilt'
FROM nexent.tag_definition
WHERE tenant_id = 'tenant-trigger' AND definition_key = 'definition-1';
SQL
  assert_query "$database" \
    "SELECT count(*) FILTER (WHERE value.delete_flag = 'N') || '|' || count(*) FILTER (WHERE value.normalized_value = 'value-998') FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.definition_key = 'definition-1';" \
    "1000|2" \
    "soft-deleted values should not count and their normalized value should be reusable"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.resource_tag_assignment (
    tenant_id, resource_type, resource_id, definition_id, value_id
)
SELECT value.tenant_id, 'tool', 'tool-limit', value.definition_id, value.value_id
FROM nexent.tag_value AS value
JOIN nexent.tag_definition AS definition
  ON definition.tenant_id = value.tenant_id
 AND definition.definition_id = value.definition_id
WHERE definition.definition_key = 'definition-1'
  AND value.delete_flag = 'N'
ORDER BY value.value_id
LIMIT 99;
SQL
  assert_query "$database" \
    "SELECT count(*) FROM nexent.resource_tag_assignment WHERE tenant_id = 'tenant-trigger' AND resource_type = 'tool' AND resource_id = 'tool-limit';" \
    "99" "assignment trigger should allow 99 assignments"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.resource_tag_assignment (
    tenant_id, resource_type, resource_id, definition_id, value_id
)
SELECT value.tenant_id, 'tool', 'tool-limit', value.definition_id, value.value_id
FROM nexent.tag_value AS value
JOIN nexent.tag_definition AS definition
  ON definition.tenant_id = value.tenant_id
 AND definition.definition_id = value.definition_id
WHERE definition.definition_key = 'definition-1'
  AND value.delete_flag = 'N'
ORDER BY value.value_id
OFFSET 99 LIMIT 1;
SQL
  assert_query "$database" \
    "SELECT count(*) FROM nexent.resource_tag_assignment WHERE tenant_id = 'tenant-trigger' AND resource_type = 'tool' AND resource_id = 'tool-limit';" \
    "100" "assignment trigger should allow the 100th assignment"
  expect_sql_failure "$database" \
    "INSERT INTO nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, definition_id, value_id) SELECT value.tenant_id, 'tool', 'tool-limit', value.definition_id, value.value_id FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition ON definition.tenant_id = value.tenant_id AND definition.definition_id = value.definition_id WHERE definition.definition_key = 'definition-1' AND value.delete_flag = 'N' ORDER BY value.value_id OFFSET 100 LIMIT 1;" \
    "Tag assignment limit exceeded" \
    "assignment trigger should reject the 101st assignment"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.tag_value (tenant_id, definition_id, normalized_value, display_value)
SELECT 'tenant-trigger', definition_id, value_key, display_value
FROM nexent.tag_definition
CROSS JOIN (VALUES ('single-a', 'Single A'), ('single-b', 'Single B')) AS values(value_key, display_value)
WHERE tenant_id = 'tenant-trigger' AND definition_key = 'definition-98';

INSERT INTO nexent.resource_tag_assignment (
    tenant_id, resource_type, resource_id, definition_id, value_id
)
SELECT value.tenant_id, 'tool', 'single-resource', value.definition_id, value.value_id
FROM nexent.tag_value AS value
JOIN nexent.tag_definition AS definition
  ON definition.tenant_id = value.tenant_id
 AND definition.definition_id = value.definition_id
WHERE definition.definition_key = 'definition-98'
ORDER BY value.value_id
LIMIT 1;
SQL
  expect_sql_failure "$database" \
    "INSERT INTO nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, definition_id, value_id) SELECT value.tenant_id, 'tool', 'single-resource', value.definition_id, value.value_id FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition ON definition.tenant_id = value.tenant_id AND definition.definition_id = value.definition_id WHERE definition.definition_key = 'definition-98' ORDER BY value.value_id DESC LIMIT 1;" \
    "single_select definition" \
    "single_select should reject a second active value"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-other', 'owner-other', 'N');
SQL
  expect_sql_failure "$database" \
    "INSERT INTO nexent.tag_value (tenant_id, definition_id, normalized_value, display_value) SELECT 'tenant-other', definition_id, 'cross-tenant', 'Cross Tenant' FROM nexent.tag_definition WHERE tenant_id = 'tenant-trigger' AND definition_key = 'definition-1';" \
    "foreign key constraint" \
    "composite tag_value FK should reject a definition from another tenant"
  expect_sql_failure "$database" \
    "INSERT INTO nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, definition_id, value_id) SELECT 'tenant-other', 'tool', 'cross-tenant-resource', value.definition_id, value.value_id FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition ON definition.tenant_id = value.tenant_id AND definition.definition_id = value.definition_id WHERE definition.tenant_id = 'tenant-trigger' AND definition.definition_key = 'definition-1' LIMIT 1;" \
    "Assignment references a mismatched definition/value" \
    "assignment trigger should reject definition/value rows from another tenant before the FK"
  pass "composite FKs, 99/100/101 limits, 999/1000/1001 limits, and single_select are enforced"
}

test_concurrent_final_slots() {
  local database="utm_concurrency"
  create_database "$database"
  create_legacy_schema "$database"
  run_sql "$database" <<'SQL'
INSERT INTO nexent.user_tenant_t VALUES (DEFAULT, 'tenant-concurrent', 'owner', 'N');
SQL
  run_file "$database" "$MIGRATION_SQL" >/dev/null

  run_sql "$database" <<'SQL'
INSERT INTO nexent.tag_definition (
    tenant_id, bucket_id, definition_key, definition_name, selection_mode
)
SELECT 'tenant-concurrent', bucket.bucket_id,
       'concurrent-definition-' || item::TEXT,
       'Concurrent Definition ' || item::TEXT,
       CASE WHEN item = 98 THEN 'single_select' ELSE 'multi_select' END
FROM nexent.tag_bucket AS bucket
CROSS JOIN generate_series(1, 98) AS series(item)
WHERE bucket.tenant_id = 'tenant-concurrent'
  AND bucket.bucket_key = 'default_resource';
SQL
  run_concurrent_sql_pair "$database" "definitions" "Tag definition limit exceeded" \
    "INSERT INTO nexent.tag_definition (tenant_id, bucket_id, definition_key, definition_name, selection_mode) SELECT 'tenant-concurrent', bucket_id, 'concurrent-definition-99a', 'Concurrent Definition 99 A', 'multi_select' FROM nexent.tag_bucket WHERE tenant_id = 'tenant-concurrent' AND bucket_key = 'default_resource';" \
    "INSERT INTO nexent.tag_definition (tenant_id, bucket_id, definition_key, definition_name, selection_mode) SELECT 'tenant-concurrent', bucket_id, 'concurrent-definition-99b', 'Concurrent Definition 99 B', 'multi_select' FROM nexent.tag_bucket WHERE tenant_id = 'tenant-concurrent' AND bucket_key = 'default_resource';"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_definition WHERE tenant_id = 'tenant-concurrent' AND delete_flag = 'N';" \
    "100" "concurrent definition final-slot writes must stop at 100"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.tag_value (
    tenant_id, definition_id, normalized_value, display_value
)
SELECT 'tenant-concurrent', definition.definition_id,
       'concurrent-value-' || item::TEXT,
       'Concurrent Value ' || item::TEXT
FROM nexent.tag_definition AS definition
CROSS JOIN generate_series(1, 999) AS series(item)
WHERE definition.tenant_id = 'tenant-concurrent'
  AND definition.definition_key = 'concurrent-definition-1';
SQL
  run_concurrent_sql_pair "$database" "values" "Tag value limit exceeded" \
    "INSERT INTO nexent.tag_value (tenant_id, definition_id, normalized_value, display_value) SELECT 'tenant-concurrent', definition_id, 'concurrent-value-1000a', 'Concurrent Value 1000 A' FROM nexent.tag_definition WHERE tenant_id = 'tenant-concurrent' AND definition_key = 'concurrent-definition-1';" \
    "INSERT INTO nexent.tag_value (tenant_id, definition_id, normalized_value, display_value) SELECT 'tenant-concurrent', definition_id, 'concurrent-value-1000b', 'Concurrent Value 1000 B' FROM nexent.tag_definition WHERE tenant_id = 'tenant-concurrent' AND definition_key = 'concurrent-definition-1';"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.definition_key = 'concurrent-definition-1' AND value.delete_flag = 'N';" \
    "1000" "concurrent value final-slot writes must stop at 1000"

  run_sql "$database" <<'SQL'
INSERT INTO nexent.tag_value (
    tenant_id, definition_id, normalized_value, display_value
)
SELECT 'tenant-concurrent', definition.definition_id, value_key, display_value
FROM nexent.tag_definition AS definition
CROSS JOIN (VALUES
    ('concurrent-single-a', 'Concurrent Single A'),
    ('concurrent-single-b', 'Concurrent Single B')
) AS values(value_key, display_value)
WHERE definition.tenant_id = 'tenant-concurrent'
  AND definition.definition_key = 'concurrent-definition-98';
SQL
  run_concurrent_sql_pair "$database" "single-select" "single_select definition" \
    "INSERT INTO nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, definition_id, value_id) SELECT value.tenant_id, 'tool', 'concurrent-single-resource', value.definition_id, value.value_id FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.definition_key = 'concurrent-definition-98' AND value.normalized_value = 'concurrent-single-a';" \
    "INSERT INTO nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, definition_id, value_id) SELECT value.tenant_id, 'tool', 'concurrent-single-resource', value.definition_id, value.value_id FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.definition_key = 'concurrent-definition-98' AND value.normalized_value = 'concurrent-single-b';"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.resource_tag_assignment WHERE tenant_id = 'tenant-concurrent' AND resource_type = 'tool' AND resource_id = 'concurrent-single-resource';" \
    "1" "concurrent single_select writes must leave exactly one assignment"

  # Reuse values from concurrent-definition-1 to avoid another large insert.
  run_sql "$database" <<'SQL'
INSERT INTO nexent.resource_tag_assignment (
    tenant_id, resource_type, resource_id, definition_id, value_id
)
SELECT value.tenant_id, 'tool', 'concurrent-resource', value.definition_id, value.value_id
FROM nexent.tag_value AS value
JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id)
WHERE definition.definition_key = 'concurrent-definition-1'
ORDER BY value.value_id
LIMIT 99;
SQL
  run_concurrent_sql_pair "$database" "assignments" "Tag assignment limit exceeded" \
    "INSERT INTO nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, definition_id, value_id) SELECT value.tenant_id, 'tool', 'concurrent-resource', value.definition_id, value.value_id FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.definition_key = 'concurrent-definition-1' ORDER BY value.value_id OFFSET 99 LIMIT 1;" \
    "INSERT INTO nexent.resource_tag_assignment (tenant_id, resource_type, resource_id, definition_id, value_id) SELECT value.tenant_id, 'tool', 'concurrent-resource', value.definition_id, value.value_id FROM nexent.tag_value AS value JOIN nexent.tag_definition AS definition USING (tenant_id, definition_id) WHERE definition.definition_key = 'concurrent-definition-1' ORDER BY value.value_id OFFSET 100 LIMIT 1;"
  assert_query "$database" \
    "SELECT count(*) FROM nexent.resource_tag_assignment WHERE tenant_id = 'tenant-concurrent' AND resource_type = 'tool' AND resource_id = 'concurrent-resource';" \
    "100" "concurrent final-slot writes must not exceed the assignment limit"
  pass "definition, value, single_select, and assignment final slots are serialized"
}

main() {
  require_prerequisites
  start_postgres

  test_preflight_before_tag_schema
  test_empty_legacy_provisions_final_tag_library
  test_tag_library_permission_ids_and_legacy_normalization
  test_tag_library_permission_id_conflict_rolls_back
  test_valid_legacy_backfill_and_idempotency
  test_agent_category_compatibility_and_future_tenant_provisioning
  test_agent_category_capacity_conflict_rolls_back
  test_latest_init_and_tag_migration_order
  test_community_tags_fail_closed
  test_null_and_empty_tenant_roll_back
  test_non_string_json_roll_back
  test_source_mismatch_roll_back
  test_value_capacity_preflight_roll_back
  test_assignment_capacity_preflight_roll_back
  test_indexes_and_hard_delete_semantics
  test_trigger_boundaries_and_tenant_fks
  test_concurrent_final_slots

  echo "PASS: all unified tag management integration tests passed"
}

main "$@"
