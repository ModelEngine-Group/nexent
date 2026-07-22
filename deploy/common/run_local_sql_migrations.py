"""Apply repository SQL migrations for local source-based development."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import psycopg2


MIGRATION_ID = "v2.4.0_0722_add_nl2agent.sql"
LOCK_KEY = "nexent_sql_migrations"
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class MigrationConfig:
    init_file: Path
    migration_dir: Path
    migration_table: str
    app_version: str
    connection_kwargs: dict[str, Any]


def _natural_sort_key(path: Path) -> tuple[Any, ...]:
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    )


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _quoted_table(table_name: str) -> tuple[str, str, str]:
    parts = table_name.split(".", 1)
    if len(parts) == 1:
        schema, table = "public", parts[0]
    else:
        schema, table = parts
    if not IDENTIFIER_PATTERN.fullmatch(schema) or not IDENTIFIER_PATTERN.fullmatch(
        table
    ):
        raise ValueError("migration_table must contain valid PostgreSQL identifiers")
    return schema, table, f'"{schema}"."{table}"'


def _ensure_migration_table(
    cursor: Any, schema: str, table: str, qualified_table: str
) -> None:
    cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
    cursor.execute(
        f"""
CREATE TABLE IF NOT EXISTS {qualified_table} (
  migration_id text PRIMARY KEY,
  checksum text NOT NULL,
  status text NOT NULL DEFAULT 'applied',
  executed_at timestamptz NOT NULL DEFAULT now(),
  app_version text,
  source_file text
);
ALTER TABLE {qualified_table} ADD COLUMN IF NOT EXISTS status text;
ALTER TABLE {qualified_table} ADD COLUMN IF NOT EXISTS executed_at timestamptz;
ALTER TABLE {qualified_table} ADD COLUMN IF NOT EXISTS app_version text;
ALTER TABLE {qualified_table} ADD COLUMN IF NOT EXISTS source_file text;
UPDATE {qualified_table} SET status = 'applied' WHERE status IS NULL;
UPDATE {qualified_table} SET executed_at = now() WHERE executed_at IS NULL;
ALTER TABLE {qualified_table} ALTER COLUMN status SET DEFAULT 'applied';
ALTER TABLE {qualified_table} ALTER COLUMN status SET NOT NULL;
ALTER TABLE {qualified_table} ALTER COLUMN executed_at SET DEFAULT now();
ALTER TABLE {qualified_table} ALTER COLUMN executed_at SET NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = '{table}_status_check'
      AND conrelid = '{qualified_table}'::regclass
  ) THEN
    ALTER TABLE {qualified_table}
      ADD CONSTRAINT "{table}_status_check"
      CHECK (status IN ('applied', 'baselined'));
  END IF;
END
$$;
"""
    )


def _record_migration(
    cursor: Any,
    qualified_table: str,
    *,
    migration_id: str,
    checksum: str,
    app_version: str,
    source_file: Path,
) -> None:
    cursor.execute(
        f"""
INSERT INTO {qualified_table}
  (migration_id, checksum, status, app_version, source_file)
VALUES (%s, %s, 'applied', %s, %s)
ON CONFLICT (migration_id) DO UPDATE SET
  checksum = EXCLUDED.checksum,
  status = EXCLUDED.status,
  executed_at = now(),
  app_version = EXCLUDED.app_version,
  source_file = EXCLUDED.source_file;
""",
        (migration_id, checksum, app_version, str(source_file)),
    )


def _validate_nl2agent_schema(cursor: Any, qualified_table: str) -> None:
    cursor.execute(
        f"""
SELECT CASE
  WHEN NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'nexent'
      AND table_name = 'nl2agent_session_t'
      AND column_name = 'runner_agent_id'
  ) THEN 'missing_runner_column'
  WHEN NOT EXISTS (
    SELECT 1 FROM {qualified_table}
    WHERE migration_id = %s
      AND status IN ('applied', 'baselined')
  ) THEN 'missing_migration_record'
  WHEN EXISTS (
    SELECT 1 FROM nexent.nl2agent_session_t
    WHERE status = 'active'
      AND delete_flag <> 'Y'
      AND runner_agent_id IS NULL
  ) THEN 'active_session_without_runner'
  ELSE 'ready'
END;
""",
        (MIGRATION_ID,),
    )
    status = cursor.fetchone()[0]
    if status == "ready":
        return
    if status == "active_session_without_runner":
        cursor.execute(
            """
SELECT tenant_id, count(*)
FROM nexent.nl2agent_session_t
WHERE status = 'active'
  AND delete_flag <> 'Y'
  AND runner_agent_id IS NULL
GROUP BY tenant_id
ORDER BY tenant_id;
"""
        )
        affected = ", ".join(
            f"{tenant_id}: {count}" for tenant_id, count in cursor.fetchall()
        )
        raise RuntimeError(f"NL2AGENT schema validation failed: {status} ({affected})")
    raise RuntimeError(f"NL2AGENT schema validation failed: {status}")


def run_migrations(
    config: MigrationConfig,
    *,
    connect: Callable[..., Any] = psycopg2.connect,
) -> None:
    if not config.init_file.is_file():
        raise FileNotFoundError(f"init SQL file not found: {config.init_file}")
    if not config.migration_dir.is_dir():
        raise FileNotFoundError(
            f"migration directory not found: {config.migration_dir}"
        )

    schema, table, qualified_table = _quoted_table(config.migration_table)
    migrations = sorted(config.migration_dir.glob("*.sql"), key=_natural_sort_key)
    connection = connect(**config.connection_kwargs)
    connection.autocommit = True
    cursor = connection.cursor()
    lock_acquired = False
    try:
        cursor.execute("SELECT pg_advisory_lock(hashtext(%s));", (LOCK_KEY,))
        lock_acquired = True
        _ensure_migration_table(cursor, schema, table, qualified_table)
        search_path = (
            f'"nexent", "{schema}", public'
            if schema != "nexent"
            else '"nexent", public'
        )
        cursor.execute(f"SET search_path TO {search_path};")

        cursor.execute(config.init_file.read_text(encoding="utf-8"))
        _record_migration(
            cursor,
            qualified_table,
            migration_id="__init.sql",
            checksum=_checksum(config.init_file),
            app_version=config.app_version,
            source_file=config.init_file,
        )

        for migration in migrations:
            checksum = _checksum(migration)
            cursor.execute(
                f"SELECT checksum FROM {qualified_table} WHERE migration_id = %s;",
                (migration.name,),
            )
            recorded = cursor.fetchone()
            if recorded is not None and recorded[0] == checksum:
                print(f"[local-sql-migrations] skip {migration.name}")
                continue
            action = "reapply" if recorded is not None else "apply"
            print(f"[local-sql-migrations] {action} {migration.name}")
            cursor.execute(migration.read_text(encoding="utf-8"))
            _record_migration(
                cursor,
                qualified_table,
                migration_id=migration.name,
                checksum=checksum,
                app_version=config.app_version,
                source_file=migration,
            )

        _validate_nl2agent_schema(cursor, qualified_table)
        print("[local-sql-migrations] Database schema is ready.")
    finally:
        try:
            if lock_acquired:
                cursor.execute("SELECT pg_advisory_unlock(hashtext(%s));", (LOCK_KEY,))
        finally:
            cursor.close()
            connection.close()


def _default_config() -> MigrationConfig:
    repository_root = Path(__file__).resolve().parents[2]
    backend_root = repository_root / "backend"
    sys.path.insert(0, str(backend_root))
    from consts.const import (  # pylint: disable=import-outside-toplevel
        APP_VERSION,
        NEXENT_POSTGRES_PASSWORD,
        POSTGRES_DB,
        POSTGRES_HOST,
        POSTGRES_PORT,
        POSTGRES_USER,
    )

    return MigrationConfig(
        init_file=repository_root / "deploy/sql/init.sql",
        migration_dir=repository_root / "deploy/sql/migrations",
        migration_table="nexent.schema_migrations",
        app_version=APP_VERSION,
        connection_kwargs={
            "host": POSTGRES_HOST or "localhost",
            "port": POSTGRES_PORT or "5432",
            "user": POSTGRES_USER or "root",
            "password": NEXENT_POSTGRES_PASSWORD or "",
            "dbname": POSTGRES_DB or "nexent",
        },
    )


def main() -> int:
    defaults = _default_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init-file", type=Path, default=defaults.init_file)
    parser.add_argument("--migration-dir", type=Path, default=defaults.migration_dir)
    parser.add_argument("--migration-table", default=defaults.migration_table)
    args = parser.parse_args()
    config = MigrationConfig(
        init_file=args.init_file.resolve(),
        migration_dir=args.migration_dir.resolve(),
        migration_table=args.migration_table,
        app_version=defaults.app_version,
        connection_kwargs=defaults.connection_kwargs,
    )
    try:
        run_migrations(config)
    except Exception as exc:
        print(f"[local-sql-migrations] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
