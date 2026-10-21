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
MIGRATION = ROOT / "deploy/sql/migrations/v2.7.1_005_unify_agent_prompts.sql"


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
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail("Temporary PostgreSQL did not become ready")
        def sql(source):
            return docker("exec", "--interactive", name, "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres", input=source)
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
    postgres(MIGRATION.read_text(encoding="utf-8"))
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
    postgres(MIGRATION.read_text(encoding="utf-8"))
    assert postgres(snapshot_sql) == after
    assert postgres("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'nexent' AND table_name = 'ag_tenant_agent_t' AND column_name IN ('constraint_prompt', 'few_shots_prompt');") == "0"


@pytest.mark.parametrize("column", ["constraint_prompt", "few_shots_prompt"])
def test_partial_legacy_schema_aborts_without_data_loss(postgres, column):
    postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (1, 'tenant-a', 0, 'N', 'Duty', 'Rule', 'Example', 'Metadata');")
    postgres(f"ALTER TABLE nexent.ag_tenant_agent_t RENAME COLUMN {column} TO missing_section;")
    snapshot = "SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;"
    before = postgres(snapshot)
    with pytest.raises(subprocess.CalledProcessError) as error:
        postgres(MIGRATION.read_text(encoding="utf-8"))
    assert "Expected both legacy Agent prompt columns" in error.value.stderr.decode("utf-8")
    assert postgres(snapshot) == before


def test_drop_failure_rolls_back_consolidation_and_preserves_schema(postgres):
    postgres("INSERT INTO nexent.ag_tenant_agent_t VALUES (1, 'tenant-a', 0, 'N', 'Duty', 'Rule', 'Example', 'Metadata');")
    # A dependent view forces DROP COLUMN to fail after the UPDATE has run.
    postgres("CREATE VIEW nexent.legacy_prompt_view AS SELECT constraint_prompt FROM nexent.ag_tenant_agent_t;")
    snapshot = "SELECT row_to_json(t) FROM nexent.ag_tenant_agent_t t;"
    before = postgres(snapshot)
    with pytest.raises(subprocess.CalledProcessError) as error:
        postgres(MIGRATION.read_text(encoding="utf-8"))
    assert "depend" in error.value.stderr.decode("utf-8")
    assert postgres(snapshot) == before
    assert postgres("SELECT constraint_prompt FROM nexent.legacy_prompt_view;") == "Rule"
    postgres("DROP VIEW nexent.legacy_prompt_view;")
    postgres(MIGRATION.read_text(encoding="utf-8"))
    row = json.loads(postgres(snapshot))
    assert row["duty_prompt"] == "# Responsibilities\nDuty\n\n# Constraints\nRule\n\n# Examples\nExample"
    assert "constraint_prompt" not in row and "few_shots_prompt" not in row
