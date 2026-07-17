#!/usr/bin/env python3
"""Temporarily create the NL2AGENT persistence tables for local runtimes."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import psycopg2
from dotenv import load_dotenv
from psycopg2.extensions import connection as PgConnection


SCHEMA: Final = "nexent"
TABLES: Final = (
    "nl2agent_catalog_snapshot_t",
    "nl2agent_session_t",
)
LOCK_NAME: Final = "nexent_nl2agent_temporary_schema_repair"

EXPECTED_COLUMNS: Final = {
    "nl2agent_catalog_snapshot_t": {
        "tenant_id": ("varchar", False),
        "snapshot_id": ("varchar", False),
        "schema_version": ("int4", False),
        "catalogs": ("jsonb", False),
        "create_time": ("timestamp", True),
        "update_time": ("timestamp", True),
        "created_by": ("varchar", True),
        "updated_by": ("varchar", True),
        "delete_flag": ("varchar", True),
    },
    "nl2agent_session_t": {
        "session_id": ("int8", False),
        "tenant_id": ("varchar", False),
        "user_id": ("varchar", False),
        "draft_agent_id": ("int4", False),
        "conversation_id": ("int4", False),
        "status": ("varchar", False),
        "workflow_schema_version": ("int4", False),
        "workflow_revision": ("int4", False),
        "catalog_snapshot_id": ("varchar", False),
        "workflow_state": ("jsonb", False),
        "create_time": ("timestamp", True),
        "update_time": ("timestamp", True),
        "created_by": ("varchar", True),
        "updated_by": ("varchar", True),
        "delete_flag": ("varchar", True),
    },
}

EXPECTED_CONSTRAINTS: Final = {
    "nl2agent_catalog_snapshot_t_pk": "p",
    "nl2agent_session_t_pkey": "p",
    "fk_nl2agent_session_catalog_snapshot": "f",
    "uq_nl2agent_session_tenant_draft": "u",
    "uq_nl2agent_session_tenant_conversation": "u",
    "ck_nl2agent_session_status": "c",
}

EXPECTED_INDEXES: Final = {
    "idx_nl2agent_session_owner_status",
    "idx_nl2agent_session_status_update",
}

DDL_STATEMENTS: Final = (
    """
    CREATE TABLE nexent.nl2agent_catalog_snapshot_t (
        tenant_id VARCHAR(100) NOT NULL,
        snapshot_id VARCHAR(64) NOT NULL,
        schema_version INTEGER NOT NULL DEFAULT 1,
        catalogs JSONB NOT NULL,
        create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        delete_flag VARCHAR(1) DEFAULT 'N',
        CONSTRAINT nl2agent_catalog_snapshot_t_pk
            PRIMARY KEY (tenant_id, snapshot_id)
    )
    """,
    """
    CREATE TABLE nexent.nl2agent_session_t (
        session_id BIGSERIAL PRIMARY KEY,
        tenant_id VARCHAR(100) NOT NULL,
        user_id VARCHAR(100) NOT NULL,
        draft_agent_id INTEGER NOT NULL,
        conversation_id INTEGER NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        workflow_schema_version INTEGER NOT NULL,
        workflow_revision INTEGER NOT NULL DEFAULT 0,
        catalog_snapshot_id VARCHAR(64) NOT NULL,
        workflow_state JSONB NOT NULL,
        create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        created_by VARCHAR(100),
        updated_by VARCHAR(100),
        delete_flag VARCHAR(1) DEFAULT 'N',
        CONSTRAINT fk_nl2agent_session_catalog_snapshot
            FOREIGN KEY (tenant_id, catalog_snapshot_id)
            REFERENCES nexent.nl2agent_catalog_snapshot_t (tenant_id, snapshot_id),
        CONSTRAINT uq_nl2agent_session_tenant_draft
            UNIQUE (tenant_id, draft_agent_id),
        CONSTRAINT uq_nl2agent_session_tenant_conversation
            UNIQUE (tenant_id, conversation_id),
        CONSTRAINT ck_nl2agent_session_status
            CHECK (status IN ('active', 'completed', 'abandoned'))
    )
    """,
    """
    CREATE INDEX idx_nl2agent_session_owner_status
    ON nexent.nl2agent_session_t (tenant_id, user_id, status)
    """,
    """
    CREATE INDEX idx_nl2agent_session_status_update
    ON nexent.nl2agent_session_t (status, update_time)
    """,
    """
    COMMENT ON TABLE nexent.nl2agent_session_t
    IS 'Durable NL2AGENT workflow session snapshots'
    """,
)


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    database: str
    password: str


def load_database_config(env_file: Path | None = None) -> DatabaseConfig:
    """Load the same PostgreSQL environment variables used by the runtime."""
    if env_file is not None:
        resolved_env_file = env_file.expanduser().resolve()
        if not resolved_env_file.is_file():
            raise RuntimeError(f"Environment file does not exist: {resolved_env_file}")
        load_dotenv(resolved_env_file, override=True)
        print(f"Loaded environment file: {resolved_env_file}")
    else:
        repository_root = Path(__file__).resolve().parent
        candidates = (repository_root / "backend" / ".env", repository_root / ".env")
        loaded_file = next((path for path in candidates if path.is_file()), None)
        if loaded_file is not None:
            load_dotenv(loaded_file, override=True)
            print(f"Loaded environment file: {loaded_file}")
    required = {
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST"),
        "POSTGRES_PORT": os.getenv("POSTGRES_PORT"),
        "POSTGRES_USER": os.getenv("POSTGRES_USER"),
        "POSTGRES_DB": os.getenv("POSTGRES_DB"),
        "NEXENT_POSTGRES_PASSWORD": os.getenv("NEXENT_POSTGRES_PASSWORD"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    try:
        port = int(required["POSTGRES_PORT"] or "")
    except ValueError as exc:
        raise RuntimeError("POSTGRES_PORT must be an integer") from exc

    return DatabaseConfig(
        host=required["POSTGRES_HOST"] or "",
        port=port,
        user=required["POSTGRES_USER"] or "",
        database=required["POSTGRES_DB"] or "",
        password=required["NEXENT_POSTGRES_PASSWORD"] or "",
    )


def connect(config: DatabaseConfig) -> PgConnection:
    """Open a dedicated connection without exposing the password in output."""
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        dbname=config.database,
        password=config.password,
        connect_timeout=10,
        application_name="nexent_nl2agent_temporary_schema_repair",
    )


def print_connection_identity(conn: PgConnection, config: DatabaseConfig) -> None:
    """Print configured and server-reported connection identity."""
    print(
        "Configured target: "
        f"host={config.host} port={config.port} database={config.database} user={config.user}"
    )
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT current_database(), current_user,
                   COALESCE(inet_server_addr()::text, '<local socket>'),
                   inet_server_port()
            """
        )
        database, user, address, port = cursor.fetchone()
    print(
        "Connected server: "
        f"address={address} port={port} database={database} user={user}"
    )


def acquire_lock(conn: PgConnection) -> None:
    """Serialize concurrent executions of this temporary repair."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_NAME,))


def ensure_schema_exists(conn: PgConnection) -> None:
    """Refuse to create a schema because its absence usually means the wrong DB."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT to_regnamespace(%s)", (SCHEMA,))
        exists = cursor.fetchone()[0]
    if exists is None:
        raise RuntimeError(
            "Schema 'nexent' does not exist. Refusing to modify this database; "
            "check the Runtime PostgreSQL settings."
        )


def get_table_presence(conn: PgConnection) -> dict[str, bool]:
    """Return whether each required table exists in the target schema."""
    presence: dict[str, bool] = {}
    with conn.cursor() as cursor:
        for table in TABLES:
            cursor.execute("SELECT to_regclass(%s)", (f"{SCHEMA}.{table}",))
            presence[table] = cursor.fetchone()[0] is not None
    return presence


def validate_columns(conn: PgConnection) -> list[str]:
    """Validate exact required column names, PostgreSQL types, and nullability."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name, column_name, udt_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = ANY(%s)
            """,
            (SCHEMA, list(TABLES)),
        )
        rows = cursor.fetchall()

    actual: dict[str, dict[str, tuple[str, bool]]] = {table: {} for table in TABLES}
    for table, column, udt_name, is_nullable in rows:
        actual[table][column] = (udt_name, is_nullable == "YES")

    errors: list[str] = []
    for table, expected_columns in EXPECTED_COLUMNS.items():
        actual_columns = actual[table]
        missing = sorted(set(expected_columns) - set(actual_columns))
        unexpected = sorted(set(actual_columns) - set(expected_columns))
        if missing:
            errors.append(f"{table}: missing columns {', '.join(missing)}")
        if unexpected:
            errors.append(f"{table}: unexpected columns {', '.join(unexpected)}")
        for column, expected_shape in expected_columns.items():
            actual_shape = actual_columns.get(column)
            if actual_shape is not None and actual_shape != expected_shape:
                errors.append(
                    f"{table}.{column}: expected {expected_shape}, found {actual_shape}"
                )
    return errors


def validate_constraints(conn: PgConnection) -> list[str]:
    """Validate the named constraints required by the ORM contract."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT constraint_record.conname, constraint_record.contype
            FROM pg_constraint AS constraint_record
            JOIN pg_class AS table_record
              ON table_record.oid = constraint_record.conrelid
            JOIN pg_namespace AS schema_record
              ON schema_record.oid = table_record.relnamespace
            WHERE schema_record.nspname = %s
              AND table_record.relname = ANY(%s)
            """,
            (SCHEMA, list(TABLES)),
        )
        actual = dict(cursor.fetchall())

    errors: list[str] = []
    for name, constraint_type in EXPECTED_CONSTRAINTS.items():
        if name not in actual:
            errors.append(f"missing constraint {name}")
        elif actual[name] != constraint_type:
            errors.append(
                f"constraint {name}: expected type {constraint_type}, found {actual[name]}"
            )
    return errors


def validate_indexes_and_sequence(conn: PgConnection) -> list[str]:
    """Validate cleanup indexes and the BIGSERIAL backing sequence."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = 'nl2agent_session_t'
            """,
            (SCHEMA,),
        )
        indexes = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT to_regclass('nexent.nl2agent_session_t_session_id_seq')")
        sequence_exists = cursor.fetchone()[0] is not None

    errors = [f"missing index {name}" for name in sorted(EXPECTED_INDEXES - indexes)]
    if not sequence_exists:
        errors.append("missing sequence nl2agent_session_t_session_id_seq")
    return errors


def validate_complete_schema(conn: PgConnection) -> list[str]:
    """Return all deviations from the required final NL2AGENT schema."""
    return (
        validate_columns(conn)
        + validate_constraints(conn)
        + validate_indexes_and_sequence(conn)
    )


def create_tables(conn: PgConnection) -> None:
    """Create only the two final-form NL2AGENT tables and their indexes."""
    with conn.cursor() as cursor:
        for statement in DDL_STATEMENTS:
            cursor.execute(statement)


def run(apply: bool, env_file: Path | None = None) -> int:
    """Inspect the target database and optionally apply the temporary repair."""
    config = load_database_config(env_file)
    conn = connect(config)
    try:
        print_connection_identity(conn, config)
        acquire_lock(conn)
        ensure_schema_exists(conn)

        presence = get_table_presence(conn)
        existing_count = sum(presence.values())
        if existing_count == len(TABLES):
            errors = validate_complete_schema(conn)
            if errors:
                raise RuntimeError(
                    "Both tables exist but their structure is incompatible:\n- "
                    + "\n- ".join(errors)
                )
            conn.rollback()
            print(
                "Result: NL2AGENT persistence schema is already complete; no changes made."
            )
            return 0

        if existing_count:
            state = ", ".join(
                f"{table}={'present' if exists else 'missing'}"
                for table, exists in presence.items()
            )
            raise RuntimeError(
                f"Partial NL2AGENT schema detected ({state}). "
                "Refusing an automatic repair to avoid overwriting an intermediate migration."
            )

        if not apply:
            conn.rollback()
            print("Result: both NL2AGENT persistence tables are missing.")
            print("Run this script again with --apply to create them.")
            return 2

        create_tables(conn)
        errors = validate_complete_schema(conn)
        if errors:
            raise RuntimeError(
                "Post-create validation failed; the transaction will be rolled back:\n- "
                + "\n- ".join(errors)
            )
        conn.commit()
        print("Result: NL2AGENT persistence tables created and validated successfully.")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or temporarily create the two PostgreSQL tables required by "
            "the directly started NL2AGENT Runtime service."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create the tables. Without this flag, the script is read-only.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help=(
            "Load PostgreSQL settings from this file. By default, backend/.env "
            "and then the repository-root .env are checked."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return run(apply=args.apply, env_file=args.env_file)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
