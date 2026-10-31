# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the ordinary user model-read repair on disposable PostgreSQL."""

import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import pytest

pytestmark = [pytest.mark.case_id("USER-MODEL-READ-D5-001"), pytest.mark.stage("D5")]
ROOT = Path(__file__).resolve().parents[3]
MARKER = "-- Source migration: v2.8.0_009_restore_user_model_read.sql"


def migration_sql():
    source = (ROOT / "deploy/sql/migrations/v2.8.0_merged_migrations.sql").read_text(encoding="utf-8")
    start = source.index(MARKER)
    end = source.find("-- Source migration: ", start + len(MARKER))
    return source[start:] if end == -1 else source[start:end]


def docker(*args, source=None):
    return subprocess.run(
        ["docker", *args], input=source, text=True, encoding="utf-8",
        capture_output=True, check=True, timeout=60,
    ).stdout.strip()


@pytest.fixture
def postgres():
    if not shutil.which("docker"):
        pytest.fail("BLOCKED: Docker is required for migration verification")
    docker("image", "inspect", "postgres:15-alpine")
    name = "nexent-user-model-read-" + uuid.uuid4().hex[:12]
    docker("run", "--rm", "--detach", "--name", name, "--network", "none",
           "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:15-alpine")
    try:
        for _ in range(80):
            ready = subprocess.run(
                # The temporary initialization server must not satisfy readiness.
                ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], capture_output=True, timeout=10,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail("Disposable PostgreSQL did not become ready")

        def sql(source):
            return docker("exec", "--interactive", name, "psql", "-h", "127.0.0.1", "-X", "-qAt",
                          "-v", "ON_ERROR_STOP=1", "-U", "postgres", source=source)

        sql("""CREATE SCHEMA nexent;
            CREATE TABLE nexent.role_permission_t (
                role_permission_id SERIAL PRIMARY KEY, user_role VARCHAR(30),
                permission_category VARCHAR(30), permission_type VARCHAR(30),
                permission_subtype VARCHAR(30));""")
        yield sql
    finally:
        docker("rm", "--force", name)


@pytest.mark.parametrize("variant", ["missing", "existing", "empty", "occupied"])
def test_restore_read_only_grant_preserves_rows_and_supports_rollback_and_rerun(postgres, variant):
    if variant != "empty":
        postgres("""INSERT INTO nexent.role_permission_t VALUES
            (158,'ADMIN','RESOURCE','MODEL','READ'),
            (1901,'USER','RESOURCE','AGENT','READ'),
            (2400,'USER','VISIBILITY','LEFT_NAV_MENU','/workbench'),
            (5000,'DEV','RESOURCE','MODEL','READ');""")
    if variant == "existing":
        postgres("INSERT INTO nexent.role_permission_t VALUES (42,'USER','RESOURCE','MODEL','READ');")
    if variant == "occupied":
        postgres("INSERT INTO nexent.role_permission_t VALUES (143,'ADMIN','RESOURCE','MODEL','UPDATE');")

    snapshot = "SELECT row_to_json(t) FROM nexent.role_permission_t t ORDER BY role_permission_id;"
    before = postgres(snapshot)
    source = migration_sql()
    if variant == "occupied":
        with pytest.raises(subprocess.CalledProcessError) as raised:
            postgres(source)
        assert "duplicate key value" in raised.value.stderr
        assert postgres(snapshot) == before
        return
    with pytest.raises(subprocess.CalledProcessError):
        postgres(source.replace("COMMIT;", "SELECT 1 / 0; COMMIT;"))
    assert postgres(snapshot) == before

    postgres(source)
    after = postgres(snapshot)
    original = [json.loads(line) for line in before.splitlines()]
    actual = [json.loads(line) for line in after.splitlines()]
    assert all(row in actual for row in original)
    grants = [row for row in actual if (
        row["user_role"], row["permission_category"], row["permission_type"], row["permission_subtype"]
    ) == ("USER", "RESOURCE", "MODEL", "READ")]
    assert len(grants) == 1
    assert grants[0]["role_permission_id"] == (42 if variant == "existing" else 143)
    assert len(actual) == len(original) + (variant != "existing")
    assert [row for row in actual if row not in original] == ([] if variant == "existing" else grants)
    assert not any(row["user_role"] == "USER" and (
        (row["permission_category"] == "RESOURCE" and row["permission_type"] == "MODEL"
         and row["permission_subtype"] in {"CREATE", "UPDATE", "DELETE"})
        or (row["permission_category"] == "VISIBILITY" and row["permission_type"] == "LEFT_NAV_MENU"
            and row["permission_subtype"] == "/models")
    ) for row in actual)
    postgres(source)
    assert postgres(snapshot) == after
