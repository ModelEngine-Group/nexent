# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify selective legacy navigation cleanup on a disposable PostgreSQL instance."""

import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import pytest

pytestmark = [pytest.mark.case_id("EVAL-LEGACY-D5-001"), pytest.mark.stage("D5")]
ROOT = Path(__file__).resolve().parents[3]
MERGED = ROOT / "deploy/sql/migrations/v2.8.0_merged_migrations.sql"
SECTION = "v2.7.1_006_remove_legacy_space_permissions.sql"


def migration_sql():
    """Read this case's section out of the consolidated v2.8.0 migration bundle."""
    text = MERGED.read_text(encoding="utf-8")
    marker = f"-- Source migration: {SECTION}"
    start = text.index(marker)
    end = text.find("-- Source migration: ", start + len(marker))
    return text[start:] if end == -1 else text[start:end]


def docker(*args, source=None):
    return subprocess.run(
        ["docker", *args], input=source.encode("utf-8") if source is not None else None,
        capture_output=True, check=True, timeout=60,
    ).stdout.decode("utf-8").strip()


@pytest.fixture
def postgres():
    if not shutil.which("docker"):
        pytest.fail("BLOCKED: Docker is required for isolated migration proof")
    docker("image", "inspect", "postgres:15-alpine")
    name = "nexent-eval-legacy-test-" + uuid.uuid4().hex[:12]
    docker("run", "--rm", "--detach", "--name", name, "--network", "none",
           "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:15-alpine")
    try:
        for _ in range(40):
            result = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "postgres"], capture_output=True,
            )
            if result.returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail("Temporary PostgreSQL did not become ready")

        def sql(source):
            return docker("exec", "--interactive", name, "psql", "-X", "-qAt",
                          "-v", "ON_ERROR_STOP=1", "-U", "postgres", source=source)

        sql("""CREATE SCHEMA nexent;
            CREATE TABLE nexent.role_permission_t (
                role_permission_id INTEGER PRIMARY KEY, user_role TEXT,
                permission_category TEXT, permission_type TEXT,
                permission_subtype TEXT, parent_key TEXT);""")
        yield sql
    finally:
        docker("rm", "--force", name)


def literal(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def test_cleanup_preserves_modern_permissions_and_is_transactional_and_repeatable(postgres):
    roles = ["SU", "ADMIN", "DEV", "SPEED", "ASSET_OWNER", "USER"]
    paths = ["/space", "/space/evaluation", "/space/evaluators"]
    legacy = [
        (10 + index * len(paths) + offset, role, "VISIBILITY", "LEFT_NAV_MENU", path, None)
        for index, role in enumerate(roles) for offset, path in enumerate(paths)
    ] + [(9999, "SU", "VISIBILITY", "LEFT_NAV_MENU", "/space", None)]
    # Modern grants intentionally reuse old numeric IDs; IDs must never drive deletion.
    retained = [
        (1600, "ADMIN", "VISIBILITY", "LEFT_NAV_MENU", "/evaluation", "/agent-dev"),
        (1701, "DEV", "VISIBILITY", "LEFT_NAV_MENU", "/evaluation/labels", "/evaluation"),
        (1601, "SU", "VISIBILITY", "LEFT_NAV_MENU", "/resource-manage", None),
        (1602, "USER", "VISIBILITY", "LEFT_NAV_MENU", "/space-extra", None),
        (1603, "USER", "VISIBILITY", "LEFT_NAV_MENU", "/space/other-feature", None),
        (1604, "USER", "OPERATION", "LEFT_NAV_MENU", "/space", None),
        (1702, "USER", "VISIBILITY", "ACTION", "/space/evaluators", None),
    ]
    for row in legacy + retained:
        postgres("INSERT INTO nexent.role_permission_t VALUES (" + ",".join(literal(x) for x in row) + ");")
    snapshot = "SELECT row_to_json(t) FROM nexent.role_permission_t t ORDER BY role_permission_id;"
    before = postgres(snapshot)
    migration = migration_sql()
    assert migration.count("COMMIT;") == 1
    with pytest.raises(subprocess.CalledProcessError):
        postgres(migration.replace("COMMIT;", "SELECT 1 / 0; COMMIT;"))
    assert postgres(snapshot) == before

    postgres(migration)
    after = postgres(snapshot)
    rows = [json.loads(line) for line in after.splitlines()]
    fields = ("role_permission_id", "user_role", "permission_category", "permission_type",
              "permission_subtype", "parent_key")
    assert [tuple(row[key] for key in fields) for row in rows] == sorted(retained)
    postgres(migration)
    assert postgres(snapshot) == after

    postgres("TRUNCATE nexent.role_permission_t;")
    postgres(migration)
    assert postgres(snapshot) == ""
