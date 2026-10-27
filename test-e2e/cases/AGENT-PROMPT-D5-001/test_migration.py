# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Execute the real migration in a run-owned PostgreSQL container."""

import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import pytest

pytestmark = [pytest.mark.case_id("AGENT-PROMPT-D5-001"), pytest.mark.stage("D5")]

ROOT = Path(__file__).resolve().parents[3]
MERGED_MIGRATION = ROOT / "deploy/sql/migrations/v2.8.0_merged_migrations.sql"


def migration_section(filename):
    """Execute exact production sections while keeping fault tests isolated."""
    source = MERGED_MIGRATION.read_text(encoding="utf-8")
    start = source.index(f"-- Source migration: {filename}\n")
    end = source.find("-- Source migration: ", start + len("-- Source migration: "))
    return source[start:] if end == -1 else source[start:end]


MIGRATION = migration_section("v2.7.1_005_unify_agent_prompts.sql")


def docker(*args, input=None):
    return subprocess.run(
        ["docker", *args], input=input.encode("utf-8") if input is not None else None,
        capture_output=True, check=True, timeout=60,
    ).stdout.decode("utf-8").strip()


@pytest.fixture
def postgres():
    if not shutil.which("docker"):
        pytest.fail("BLOCKED: Docker is required for isolated migration proof")
    docker("image", "inspect", "postgres:15-alpine")
    name = "nexent-prompt-test-" + uuid.uuid4().hex[:12]
    docker("run", "--rm", "--detach", "--name", name, "--network", "none",
           "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:15-alpine")
    try:
        for _ in range(40):
            # The entrypoint's temporary initialization server accepts only Unix sockets.
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], capture_output=True, timeout=10)
            if ready.returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail("Temporary PostgreSQL did not become ready")
        def sql(source):
            return docker("exec", "--interactive", name, "psql", "-h", "127.0.0.1", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres", input=source)
        sql("CREATE SCHEMA nexent; CREATE TABLE nexent.ag_tenant_agent_t (id int PRIMARY KEY, tenant_id text, version_no int, delete_flag text, duty_prompt text, constraint_prompt text, few_shots_prompt text, description text);")
        yield sql
    finally:
        docker("rm", "--force", name)


def literal(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def test_legacy_prompt_migration_preserves_rows_and_repeated_execution(postgres):
    variants = [
        (1, "tenant-a", 0, "N", "职责\n  原文", "只能中文", "<code>\n  call('你好')\n</code>", "Keep metadata"),
        (2, "tenant-b", 3, "N", "Published", "Rule", "Example", "Published metadata"),
        (3, "tenant-b", 1, "Y", None, "Deleted rule", None, "Deleted metadata"),
        (4, "tenant-a", 0, "N", "  Single prompt\n  untouched ", "", "", "Single metadata"),
        (5, "tenant-a", 0, "N", None, None, None, "Null metadata"),
        (6, "tenant-a", 0, "N", "Duty", " \t\n", "\r\n", "Whitespace metadata"),
        (7, "tenant-a", 0, "N", "", "", "Only example", "Example metadata"),
    ]
    for row in variants:
        postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (" + ",".join(literal(x) for x in row) + ");")
    snapshot_sql = "SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t ORDER BY id;"
    postgres(MIGRATION)
    after = postgres(snapshot_sql)
    rows = [json.loads(line) for line in after.splitlines()]
    for source, row in zip(variants, rows):
        assert [row[k] for k in ("id", "tenant_id", "version_no", "delete_flag")] == list(source[:4])
        assert row["description"] == source[7]
        assert "constraint_prompt" not in row
        assert "few_shots_prompt" not in row
    expected = [
        "# Responsibilities\n职责\n  原文\n\n# Constraints\n只能中文\n\n# Examples\n<code>\n  call('你好')\n</code>",
        "# Responsibilities\nPublished\n\n# Constraints\nRule\n\n# Examples\nExample",
        "# Constraints\nDeleted rule", "  Single prompt\n  untouched ", None, "Duty", "# Examples\nOnly example",
    ]
    assert [row["duty_prompt"] for row in rows] == expected
    postgres(MIGRATION)
    assert postgres(snapshot_sql) == after
    assert postgres("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'ag_tenant_agent_t' AND column_name IN ('constraint_prompt', 'few_shots_prompt');") == "0"


@pytest.mark.parametrize("column", ["constraint_prompt", "few_shots_prompt"])
def test_partial_legacy_schema_aborts_without_data_loss(postgres, column):
    postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (1, 'tenant-a', 0, 'N', 'Duty', 'Rule', 'Example', 'Metadata');")
    postgres(f"ALTER TABLE nexent.ag_tenant_agent_t RENAME COLUMN {column} TO missing_section;")
    snapshot = "SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;"
    before = postgres(snapshot)
    with pytest.raises(subprocess.CalledProcessError) as error:
        postgres(MIGRATION)
    assert "Expected both legacy Agent prompt columns" in error.value.stderr.decode("utf-8")
    assert postgres(snapshot) == before


def test_drop_failure_rolls_back_consolidation_and_preserves_schema(postgres):
    postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (1, 'tenant-a', 0, 'N', 'Duty', 'Rule', 'Example', 'Metadata');")
    # A dependent view forces DROP COLUMN to fail after the UPDATE has run.
    postgres("CREATE VIEW nexent.legacy_prompt_view AS SELECT constraint_prompt FROM nexent.ag_tenant_agent_t;")
    snapshot = "SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;"
    before = postgres(snapshot)
    with pytest.raises(subprocess.CalledProcessError) as error:
        postgres(MIGRATION)
    assert "depend" in error.value.stderr.decode("utf-8")
    assert postgres(snapshot) == before
    assert postgres("SELECT constraint_prompt FROM nexent.legacy_prompt_view;") == "Rule"
    postgres("DROP VIEW nexent.legacy_prompt_view;")
    postgres(MIGRATION)
    row = json.loads(postgres(snapshot))
    assert row["duty_prompt"] == "# Responsibilities\nDuty\n\n# Constraints\nRule\n\n# Examples\nExample"
    assert "constraint_prompt" not in row and "few_shots_prompt" not in row


MARKETPLACE_MIGRATION = migration_section("v2.7.1_006_unify_marketplace_agent_prompts.sql")


def seed_marketplace(postgres, snapshots):
    postgres("CREATE TABLE nexent.ag_agent_repository_t (agent_repository_id int PRIMARY KEY, tenant_id text, version_no int, delete_flag text, agent_info_json jsonb, description text);")
    for index, snapshot in enumerate(snapshots, 1):
        payload = literal(json.dumps(snapshot, ensure_ascii=False))
        postgres(f"INSERT INTO nexent.ag_agent_repository_t VALUES ({index}, 'tenant-{index}', {index}, '{'Y' if index % 2 else 'N'}', {payload}::jsonb, 'Keep metadata');")
    return "SELECT row_to_json(t) FROM nexent.ag_agent_repository_t t ORDER BY agent_repository_id;"


def test_marketplace_migration_preserves_frozen_parent_child_content_and_is_idempotent(postgres):
    parent = {"duty_prompt": "职责\n  原文", "constraint_prompt": "只能中文", "few_shots_prompt": "<code>\n  call('你好')\n</code>", "tools": [{"name": "keep", "params": {"prompt": "Tool prompt"}}]}
    child = {"prompt": "Child", "constraints_prompt": "Rule", "few_shot_prompts": "Example", "managed_agents": []}
    variants = {
        "parent": parent, "child": child,
        "single": {"prompt": "  Single prompt\n  untouched "},
        "null": {"duty_prompt": None, "constraint_prompt": None},
        "empty": {"duty_prompt": "", "few_shots_prompt": ""},
        "whitespace": {"duty_prompt": "Duty", "constraint_prompt": " \t\n", "few_shots_prompt": "\r\n"},
        "only-example": {"few_shots_prompt": "Only example"},
        "aliases": {"prompt": "Same", "duty_prompt": "Same", "constraint_prompt": "Rule", "constraints_prompt": "Rule", "few_shots_prompt": "Example", "few_shot_prompts": "Example"},
        "no-prompt": {"description": "Keep missing prompt"},
    }
    snapshots = [{"agent_id": 1, "agent_info": variants, "mcp_info": [{"url": "keep"}], "skills": [{"prompt": "Not Agent instructions"}]}]
    snapshots.append({"agent_id": 2, "agent_info": {"2": {"prompt": "Other published version"}}, "mcp_info": []})
    snapshot_sql = seed_marketplace(postgres, snapshots)
    before = [json.loads(line) for line in postgres(snapshot_sql).splitlines()]
    # A different live draft must never replace the frozen published instructions.
    postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (1, 'tenant-1', 0, 'N', 'LIVE DRAFT MUST NOT BE USED', '', '', 'Live metadata');")
    live_before = postgres("SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;")
    postgres(MARKETPLACE_MIGRATION)
    after = postgres(snapshot_sql)
    rows = [json.loads(line) for line in after.splitlines()]
    for old, new in zip(before, rows):
        assert {k: v for k, v in new.items() if k != "agent_info_json"} == {k: v for k, v in old.items() if k != "agent_info_json"}
        assert {k: v for k, v in new["agent_info_json"].items() if k != "agent_info"} == {k: v for k, v in old["agent_info_json"].items() if k != "agent_info"}
    agents = rows[0]["agent_info_json"]["agent_info"]
    assert agents["parent"] == {"prompt": "# Responsibilities\n职责\n  原文\n\n# Constraints\n只能中文\n\n# Examples\n<code>\n  call('你好')\n</code>", "tools": parent["tools"]}
    assert agents["child"] == {"prompt": "# Responsibilities\nChild\n\n# Constraints\nRule\n\n# Examples\nExample", "managed_agents": []}
    assert agents["single"] == variants["single"]
    assert agents["null"] == {"prompt": None}
    assert agents["empty"] == {"prompt": ""}
    assert agents["whitespace"] == {"prompt": "Duty"}
    assert agents["only-example"] == {"prompt": "# Examples\nOnly example"}
    assert agents["aliases"] == {"prompt": "# Responsibilities\nSame\n\n# Constraints\nRule\n\n# Examples\nExample"}
    assert agents["no-prompt"] == variants["no-prompt"]
    assert rows[1] == before[1]
    for info in agents.values():
        assert not set(info) & {"duty_prompt", "constraint_prompt", "constraints_prompt", "few_shots_prompt", "few_shot_prompts"}
    postgres(MARKETPLACE_MIGRATION)
    assert postgres(snapshot_sql) == after
    assert postgres("SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;") == live_before


@pytest.mark.parametrize("invalid", [
    {"prompt": "New", "duty_prompt": "Old"},
    {"constraint_prompt": "New", "constraints_prompt": "Old"},
    {"few_shots_prompt": "New", "few_shot_prompts": "Old"},
    {"prompt": None, "duty_prompt": "Old"},
    *[{key: value} for key in ("prompt", "duty_prompt", "constraint_prompt", "constraints_prompt", "few_shots_prompt", "few_shot_prompts") for value in (7, [], {})],
    "not-an-agent-object",
])
def test_marketplace_migration_invalid_agent_rolls_back_all_listings(postgres, invalid):
    snapshots = [
        {"agent_info": {"1": {"duty_prompt": "Duty", "constraint_prompt": "Rule"}}},
        {"agent_info": {"2": invalid}},
    ]
    query = seed_marketplace(postgres, snapshots)
    before = postgres(query)
    with pytest.raises(subprocess.CalledProcessError):
        postgres(MARKETPLACE_MIGRATION)
    assert postgres(query) == before


@pytest.mark.parametrize("invalid", [None, [], "invalid", {}, {"agent_info": None}, {"agent_info": []}])
def test_marketplace_migration_malformed_snapshot_rolls_back_all_listings(postgres, invalid):
    query = seed_marketplace(postgres, [{"agent_info": {"1": {"duty_prompt": "Keep"}}}, invalid])
    before = postgres(query)
    with pytest.raises(subprocess.CalledProcessError):
        postgres(MARKETPLACE_MIGRATION)
    assert postgres(query) == before


RENAME_MIGRATION = migration_section("v2.7.1_009_rename_agent_prompt_column.sql")


def agent_column_snapshot(postgres):
    return postgres("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'ag_tenant_agent_t' ORDER BY ordinal_position;")


def test_agent_prompt_column_rename_preserves_rows_and_full_chain_is_repeatable(postgres):
    rows = [
        (1, "tenant-a", 0, "N", "职责\n  原文", "Rule", "Example", "Draft metadata"),
        (2, "tenant-b", 3, "Y", "  Published\n exact ", "", "", "Deleted version"),
        (3, "tenant-b", 1, "N", None, None, None, "Null metadata"),
        (4, "tenant-a", 2, "N", "", "", "", "Empty metadata"),
    ]
    for row in rows:
        postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (" + ",".join(literal(x) for x in row) + ");")
    market_query = seed_marketplace(postgres, [{"agent_info": {"1": {"duty_prompt": "Frozen content"}}}])
    postgres(MIGRATION)
    postgres(MARKETPLACE_MIGRATION)
    market_before = postgres(market_query)
    query = "SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t ORDER BY id;"
    before = [json.loads(line) for line in postgres(query).splitlines()]
    postgres("ALTER TABLE nexent.ag_tenant_agent_t ALTER COLUMN duty_prompt SET DEFAULT 'Default instructions'; CREATE INDEX prompt_lookup ON nexent.ag_tenant_agent_t (duty_prompt); CREATE VIEW nexent.published_prompt AS SELECT id, duty_prompt AS instructions FROM nexent.ag_tenant_agent_t;")
    view_query = "SELECT row_to_json(t) FROM nexent.published_prompt t ORDER BY id;"
    view_before = postgres(view_query)
    postgres(RENAME_MIGRATION)
    expected = [{**{k: v for k, v in row.items() if k != "duty_prompt"}, "prompt": row["duty_prompt"]} for row in before]
    assert [json.loads(line) for line in postgres(query).splitlines()] == expected
    assert postgres(view_query) == view_before
    assert postgres(market_query) == market_before
    assert postgres("SELECT column_name FROM information_schema.columns WHERE table_schema='nexent' AND table_name='ag_tenant_agent_t' AND column_name IN ('prompt','duty_prompt');") == "prompt"
    assert postgres("SELECT data_type || ':' || is_nullable || ':' || column_default FROM information_schema.columns WHERE table_schema='nexent' AND table_name='ag_tenant_agent_t' AND column_name='prompt';") == "text:YES:'Default instructions'::text"
    index = postgres("SELECT indexdef FROM pg_indexes WHERE schemaname='nexent' AND indexname='prompt_lookup';")
    assert "(prompt)" in index and "duty_prompt" not in index
    assert postgres("SELECT col_description('nexent.ag_tenant_agent_t'::regclass, attnum) FROM pg_attribute WHERE attrelid='nexent.ag_tenant_agent_t'::regclass AND attname='prompt';") == "Complete Agent instructions including responsibilities, constraints and examples"
    after, columns = postgres(query), agent_column_snapshot(postgres)
    postgres(MIGRATION + MARKETPLACE_MIGRATION + RENAME_MIGRATION)
    assert postgres(query) == after
    assert agent_column_snapshot(postgres) == columns
    assert postgres(view_query) == view_before
    assert postgres(market_query) == market_before


@pytest.mark.parametrize("state", ["both", "neither", "unconsolidated", "canonical-unconsolidated"])
def test_agent_prompt_column_rename_rejects_invalid_schema_without_changes(postgres, state):
    postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (1,'tenant-a',0,'N','Duty','Rule','Example','Metadata');")
    if state in {"both", "neither"}:
        postgres(MIGRATION)
        postgres("ALTER TABLE nexent.ag_tenant_agent_t " + ("ADD COLUMN prompt TEXT;" if state == "both" else "DROP COLUMN duty_prompt;"))
    elif state == "canonical-unconsolidated":
        postgres("ALTER TABLE nexent.ag_tenant_agent_t RENAME COLUMN duty_prompt TO prompt;")
    query = "SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;"
    before, columns = postgres(query), agent_column_snapshot(postgres)
    with pytest.raises(subprocess.CalledProcessError):
        postgres(RENAME_MIGRATION)
    assert postgres(query) == before
    assert agent_column_snapshot(postgres) == columns


def test_agent_prompt_column_rename_ddl_failure_rolls_back(postgres):
    postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (1,'tenant-a',1,'N','Duty','','','Metadata');")
    postgres(MIGRATION)
    postgres("CREATE FUNCTION nexent.reject_prompt_comment() RETURNS event_trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Injected comment failure'; END; $$; CREATE EVENT TRIGGER reject_prompt_comment ON ddl_command_start WHEN TAG IN ('COMMENT') EXECUTE FUNCTION nexent.reject_prompt_comment();")
    query = "SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;"
    before, columns = postgres(query), agent_column_snapshot(postgres)
    with pytest.raises(subprocess.CalledProcessError) as error:
        postgres(RENAME_MIGRATION)
    assert "Injected comment failure" in error.value.stderr.decode("utf-8")
    assert postgres(query) == before
    assert agent_column_snapshot(postgres) == columns
    postgres("DROP EVENT TRIGGER reject_prompt_comment;")
    postgres(RENAME_MIGRATION)
    assert json.loads(postgres(query))["prompt"] == "Duty"



def test_merged_prompt_sections_run_in_deployment_order_and_repeat(postgres):
    source = MERGED_MIGRATION.read_text(encoding="utf-8")
    start = source.index("-- Source migration: v2.7.1_005_unify_agent_prompts.sql\n")
    end_marker = "-- End source migration: v2.7.1_009_rename_agent_prompt_column.sql"
    end = source.index(end_marker, start) + len(end_marker)
    merged = source[start:end]
    postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (1,'tenant-a',0,'N','Duty','Rule','Example','Metadata');")
    query = seed_marketplace(postgres, [{"agent_info": {"1": {"duty_prompt": "Frozen", "constraint_prompt": "Published rule"}}}])
    postgres(merged)
    rows = postgres("SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;")
    assert json.loads(rows) == {
        "id": 1, "tenant_id": "tenant-a", "version_no": 0, "delete_flag": "N",
        "prompt": "# Responsibilities\nDuty\n\n# Constraints\nRule\n\n# Examples\nExample",
        "description": "Metadata",
    }
    market = postgres(query)
    assert json.loads(market)["agent_info_json"]["agent_info"]["1"] == {
        "prompt": "# Responsibilities\nFrozen\n\n# Constraints\nPublished rule",
    }
    postgres(merged)
    assert postgres("SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;") == rows
    assert postgres(query) == market
