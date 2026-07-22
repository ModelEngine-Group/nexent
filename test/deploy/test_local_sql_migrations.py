from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from deploy.common.run_local_sql_migrations import MigrationConfig, run_migrations


class FakeCursor:
    def __init__(
        self,
        fetchone_results: list[Any],
        fetchall_result: list[tuple[Any, ...]] | None = None,
    ):
        self.executions: list[tuple[str, Any]] = []
        self._fetchone_results = iter(fetchone_results)
        self._fetchall_result = fetchall_result or []
        self.closed = False

    def execute(self, query: str, parameters: Any = None) -> None:
        self.executions.append((query, parameters))

    def fetchone(self) -> Any:
        return next(self._fetchone_results)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._fetchall_result

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor
        self.autocommit = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def _config(tmp_path: Path, migration_names: list[str]) -> MigrationConfig:
    init_file = tmp_path / "init.sql"
    init_file.write_text("CREATE SCHEMA IF NOT EXISTS nexent;", encoding="utf-8")
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    for migration_name in migration_names:
        (migration_dir / migration_name).write_text(
            f"SELECT '{migration_name}';",
            encoding="utf-8",
        )
    return MigrationConfig(
        init_file=init_file,
        migration_dir=migration_dir,
        migration_table="nexent.schema_migrations",
        app_version="v-test",
        connection_kwargs={"host": "database"},
    )


def _executed_sql(cursor: FakeCursor) -> list[str]:
    return [query for query, _ in cursor.executions]


def test_run_migrations_applies_files_in_natural_order_and_validates(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, ["v2_10.sql", "v2_2.sql"])
    cursor = FakeCursor([None, None, ("ready",)])
    connection = FakeConnection(cursor)
    connect_calls: list[dict[str, Any]] = []

    def connect(**kwargs: Any) -> FakeConnection:
        connect_calls.append(kwargs)
        return connection

    run_migrations(config, connect=connect)

    statements = _executed_sql(cursor)
    migration_statements = [
        statement for statement in statements if statement.startswith("SELECT 'v2_")
    ]
    assert migration_statements == ["SELECT 'v2_2.sql';", "SELECT 'v2_10.sql';"]
    assert any("information_schema.columns" in statement for statement in statements)
    assert connect_calls == [{"host": "database"}]
    assert connection.autocommit is True
    assert cursor.closed is True
    assert connection.closed is True
    assert "pg_advisory_unlock" in statements[-1]


def test_run_migrations_skips_matching_checksum(tmp_path: Path) -> None:
    config = _config(tmp_path, ["v1.sql"])
    migration = config.migration_dir / "v1.sql"
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    cursor = FakeCursor([(checksum,), ("ready",)])
    connection = FakeConnection(cursor)

    run_migrations(config, connect=lambda **_: connection)

    assert migration.read_text(encoding="utf-8") not in _executed_sql(cursor)


def test_run_migrations_reports_active_sessions_without_runner(tmp_path: Path) -> None:
    config = _config(tmp_path, ["v1.sql"])
    cursor = FakeCursor(
        [None, ("active_session_without_runner",)],
        fetchall_result=[("tenant-a", 2)],
    )
    connection = FakeConnection(cursor)

    with pytest.raises(
        RuntimeError,
        match=r"active_session_without_runner \(tenant-a: 2\)",
    ):
        run_migrations(config, connect=lambda **_: connection)

    assert cursor.closed is True
    assert connection.closed is True
    assert "pg_advisory_unlock" in _executed_sql(cursor)[-1]


def test_run_migrations_rejects_invalid_migration_table(tmp_path: Path) -> None:
    config = _config(tmp_path, [])
    invalid_config = MigrationConfig(
        init_file=config.init_file,
        migration_dir=config.migration_dir,
        migration_table="nexent.schema_migrations;DROP TABLE users",
        app_version=config.app_version,
        connection_kwargs=config.connection_kwargs,
    )

    with pytest.raises(ValueError, match="valid PostgreSQL identifiers"):
        run_migrations(invalid_config, connect=lambda **_: None)
