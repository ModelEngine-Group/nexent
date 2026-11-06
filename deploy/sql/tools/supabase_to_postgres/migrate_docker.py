# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Standalone historical account migration and deployment upgrade coordinator."""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "deploy/sql/migrations").is_dir()), Path.cwd())


def password_scheme(encoded):
    """Validate imported hash formats without importing application code."""
    if re.fullmatch(r"\$2[aby]\$(0[4-9]|1[0-6])\$[./A-Za-z0-9]{53}", encoded or ""):
        return "bcrypt"
    parts = (encoded or "").split("$")
    if len(parts) == 6 and parts[:4] == ["scrypt", "16384", "8", "1"]:
        try:
            if len(base64.b64decode(parts[4], validate=True)) == 16 and len(base64.b64decode(parts[5], validate=True)) == 32:
                return "scrypt"
        except ValueError:
            pass
    raise ValueError("Unsupported password hash format")


class MigrationSetupError(ValueError):
    """Operator-actionable prerequisite error containing no credential values."""


def load_settings(env_file, environ=None):
    from dotenv import dotenv_values

    file_values = dotenv_values(env_file) if env_file.is_file() else {}
    return {**file_values, **(os.environ if environ is None else environ)}


def _port(value):
    try:
        result = int(value)
        if not 1 <= result <= 65535:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise MigrationSetupError("Database port must be between 1 and 65535") from None


def source_password(values):
    if values.get("SUPABASE_POSTGRES_PASSWORD"):
        return values["SUPABASE_POSTGRES_PASSWORD"]
    if not sys.stdin.isatty():
        raise MigrationSetupError(
            "Set SUPABASE_POSTGRES_PASSWORD before noninteractive migration"
        )
    value = getpass.getpass("Supabase PostgreSQL password: ")
    if not value:
        raise MigrationSetupError("Supabase PostgreSQL password is required")
    return value


def connections(values):
    """Use existing deployment settings and translate Docker-only hostnames."""
    host = values.get("SUPABASE_POSTGRES_HOST")
    service_host = host in {"supabase_db", "supabase-db-mini", "nexent-supabase-db"}
    source = {
        "host": "127.0.0.1" if not host or service_host else host,
        "port": _port(values.get("SUPABASE_POSTGRES_PORT") or 5436),
        "dbname": values.get("SUPABASE_POSTGRES_DB") or "supabase",
        "user": values.get("SUPABASE_POSTGRES_USER") or "postgres",
        "password": source_password(values),
        "connect_timeout": 3,
    }
    return source, target_connection(values), service_host or not values.get("SUPABASE_POSTGRES_HOST")


def target_connection(values):
    """Resolve the target without asking for source credentials on completed upgrades."""
    host = values.get("POSTGRES_HOST") or "127.0.0.1"
    internal = host == "nexent-postgresql"
    target = {
        "host": "127.0.0.1" if internal else host,
        "port": _port(5434 if internal else values.get("POSTGRES_PORT") or 5434),
        "user": values.get("POSTGRES_USER") or "root",
        "dbname": values.get("POSTGRES_DB") or "nexent",
        "password": values.get("NEXENT_POSTGRES_PASSWORD"),
        "connect_timeout": 3,
    }
    if not target["password"]:
        raise MigrationSetupError("Set NEXENT_POSTGRES_PASSWORD")
    return target


class MigrationConflict(ValueError):
    """Sanitized migration error; never include source rows or credentials."""


def utc_time(value):
    if not value:
        return None
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo:
        result = result.astimezone(timezone.utc).replace(tzinfo=None)
    return result


def map_source_user(row: dict) -> dict:
    """Map explicit fields only. Provider metadata never supplies application roles."""
    try:
        user_id = str(UUID(str(row["id"])))
        email = str(row.get("email") or "").strip().lower()
        if not email or len(email) > 255 or "@" not in email:
            raise MigrationConflict("Source contains an unsupported email identity")
        encoded = row.get("encrypted_password") or None
        scheme = password_scheme(encoded) if encoded else None
        metadata = {
            "raw_user_meta_data": row.get("raw_user_meta_data") or {},
            "raw_app_meta_data": row.get("raw_app_meta_data") or {},
            "source_provider_identities": row.get("source_provider_identities") or [],
            "phone": row.get("phone"),
            "phone_confirmed_at": row.get("phone_confirmed_at"),
            "last_sign_in_at": row.get("last_sign_in_at"),
            "invited_at": row.get("invited_at"),
            "banned_until": row.get("banned_until"),
            "source_deleted_at": row.get("deleted_at"),
        }
        if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
            raise MigrationConflict("Source account metadata exceeds the import limit")
        banned = utc_time(row.get("banned_until"))
        deleted = bool(row.get("deleted_at"))
        disabled = (
            deleted
            or (banned and banned > datetime.now(timezone.utc).replace(tzinfo=None))
            or bool(row.get("is_anonymous"))
        )
        return {
            "user_id": user_id,
            "email": email,
            "password_hash": encoded,
            "password_hash_scheme": scheme,
            "password_login_enabled": bool(encoded),
            "token_version": 0,
            "email_confirmed_at": utc_time(row.get("email_confirmed_at")),
            "create_time": utc_time(row.get("created_at")) or datetime.now(timezone.utc).replace(tzinfo=None),
            "update_time": utc_time(row.get("updated_at")) or datetime.now(timezone.utc).replace(tzinfo=None),
            "delete_flag": "Y" if disabled else "N",
            "source_metadata": metadata,
        }
    except MigrationConflict:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise MigrationConflict(
            "Source account has an unsupported identifier, date or password hash"
        ) from None


def read_source_users(source) -> list:
    """Caller must configure this source connection as read-only/repeatable-read."""
    with source.cursor() as cursor:
        cursor.execute("SELECT row_to_json(u) FROM auth.users u ORDER BY id")
        users = [record[0] for record in cursor.fetchall()]
        cursor.execute("SELECT to_regclass('auth.identities') IS NOT NULL")
        if cursor.fetchone()[0]:
            cursor.execute(
                "SELECT row_to_json(i) FROM auth.identities i ORDER BY user_id"
            )
            identities = {}
            for (identity,) in cursor.fetchall():
                identities.setdefault(str(identity["user_id"]), []).append(identity)
            for user in users:
                user["source_provider_identities"] = identities.get(str(user["id"]), [])
    return users


def inspection_sql():
    """Inspect membership coverage and usable credentials without persistent writes."""
    return (HERE / "inspect_accounts.sql").read_text(encoding="utf-8")


def inspect_accounts(target):
    with target.cursor() as cursor:
        cursor.execute(inspection_sql())
        return cursor.fetchone()[0]


def account_data_complete(state):
    """Reject incomplete existing tables; automatic migration never repairs them."""
    if state["complete"]:
        return True
    if state.get("account_table"):
        raise MigrationSetupError("Existing account data is incomplete; IDs: "
            + json.dumps(state.get("unresolved_ids", []))
            + "; restore the consistent pre-upgrade backup before retrying; no automatic repair was attempted")
    return False


def _account_import_sql(source_rows, *, dry_run=False):
    """Build one credential/schema transaction body, shared by host and psql."""
    rows = [map_source_user(row) for row in source_rows]
    ids = set()
    for row in rows:
        if row["user_id"] in ids:
            raise MigrationConflict("Account migration conflict IDs: " + json.dumps([row["user_id"]]))
        ids.add(row["user_id"])
        row["user_email"] = row.pop("email")
    encoded = json.dumps(rows, default=lambda value: value.isoformat()).replace("'", "''")
    schema = (ROOT / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql").read_text(encoding="utf-8")
    return "SET LOCAL standard_conforming_strings=on;\n" + inspection_sql() + r"""
SET LOCAL nexent.account_import='on';
""" + schema + "\n" + r"""
CREATE TABLE IF NOT EXISTS nexent.account_migration_exclusion_t (
    exclusion_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL UNIQUE,
    exclusion_reason VARCHAR(100) NOT NULL,
    created_by VARCHAR(100) NOT NULL DEFAULT 'auth-migration',
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) NOT NULL DEFAULT 'auth-migration',
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);
COMMENT ON TABLE nexent.account_migration_exclusion_t IS 'Per-identity evidence for unavailable historical accounts intentionally excluded from local authentication';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.exclusion_id IS 'Technical exclusion evidence identifier';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.user_id IS 'Original historical user identifier';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.exclusion_reason IS 'Source eligibility decision without credential material';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.created_by IS 'Migration actor that recorded the exclusion';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.create_time IS 'UTC exclusion creation time';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.updated_by IS 'Migration actor that last changed the exclusion';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.update_time IS 'UTC exclusion update time';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.delete_flag IS 'N for applicable historical exclusion, Y for retired evidence';

CREATE TEMP TABLE account_import ON COMMIT DROP AS
SELECT s.*, (s.delete_flag='Y') AS source_inactive, coalesce(p.role_value,a.user_role) AS role_value,
       coalesce(p.email_value,a.user_email) AS profile_email,
       (p.user_id IS NOT NULL OR a.user_id IS NOT NULL) AS existing,
       NOT EXISTS (SELECT 1 FROM nexent.user_tenant_t u
                   WHERE u.user_id=s.user_id AND u.delete_flag='N') AS orphan
FROM jsonb_populate_recordset(NULL::nexent.user_account_t, '__ROWS__'::jsonb) s
LEFT JOIN pg_temp.account_migration_profiles p ON p.user_id=s.user_id
LEFT JOIN nexent.user_account_t a ON a.user_id=s.user_id;
UPDATE account_import SET delete_flag='Y' WHERE orphan OR nullif(trim(role_value),'') IS NULL;
DO $validate$
DECLARE conflict_ids json;
BEGIN
    SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids FROM (
        SELECT DISTINCT user_id FROM account_import
        WHERE delete_flag='N' AND profile_email IS NOT NULL AND profile_email<>user_email
    ) conflicts;
    IF conflict_ids IS NOT NULL THEN
        RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids;
    END IF;
END
$validate$;
UPDATE nexent.user_account_t a SET
    user_email=s.user_email,user_role=s.role_value,password_hash=s.password_hash,password_hash_scheme=s.password_hash_scheme,
    password_login_enabled=s.password_login_enabled,token_version=s.token_version,
    email_confirmed_at=s.email_confirmed_at,source_metadata=s.source_metadata,
    create_time=s.create_time,update_time=s.update_time,delete_flag=s.delete_flag,updated_by='auth-migration'
FROM account_import s WHERE a.user_id=s.user_id;
INSERT INTO nexent.user_account_t
    (user_id,user_email,user_role,password_hash,password_hash_scheme,password_login_enabled,token_version,
     email_confirmed_at,source_metadata,create_time,update_time,delete_flag,created_by,updated_by)
SELECT user_id,user_email,role_value,password_hash,password_hash_scheme,password_login_enabled,token_version,
       email_confirmed_at,source_metadata,create_time,update_time,delete_flag,'auth-migration','auth-migration'
FROM account_import s WHERE delete_flag='N'
AND NOT EXISTS (SELECT 1 FROM nexent.user_account_t a WHERE a.user_id=s.user_id);
DELETE FROM nexent.user_account_t WHERE delete_flag='Y'
AND coalesce(source_metadata->>'system_identity','')<>'speed';
DO $email_conflicts$
DECLARE conflict_ids json;
BEGIN
    SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids
    FROM nexent.user_account_t
    WHERE delete_flag='N' AND lower(trim(user_email)) IN (
        SELECT lower(trim(user_email)) FROM nexent.user_account_t
        WHERE delete_flag='N' AND user_email IS NOT NULL
        GROUP BY lower(trim(user_email)) HAVING count(*)>1
    );
    IF conflict_ids IS NOT NULL THEN
        RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids;
    END IF;
END
$email_conflicts$;
INSERT INTO nexent.account_migration_exclusion_t (user_id,exclusion_reason)
SELECT user_id,'source_unavailable' FROM account_import WHERE source_inactive AND NOT orphan
ON CONFLICT (user_id) DO NOTHING;
DO $coverage$
DECLARE unresolved json := pg_temp.inspect_local_accounts()->'unresolved_ids';
BEGIN
    IF json_array_length(unresolved)>0 THEN
        RAISE EXCEPTION 'NEXENT_ACCOUNT_INCOMPLETE=%',unresolved;
    END IF;
END
$coverage$;
SET LOCAL nexent.account_import='off';
SELECT json_build_object('source',__SOURCE_COUNT__,'inserted',count(*) FILTER (WHERE NOT existing AND delete_flag='N'),
                         'updated',count(*) FILTER (WHERE existing AND delete_flag='N'),
                         'skipped',count(*) FILTER (WHERE delete_flag='Y'),
                         'excluded_inactive',count(*) FILTER (WHERE delete_flag='Y'),
                         'disabled_orphans',count(*) FILTER (WHERE orphan),'dry_run',__DRY_RUN__)
FROM account_import;
""".replace("__DRY_RUN__", "true" if dry_run else "false").replace("__SOURCE_COUNT__", str(len(rows))).replace("__ROWS__", encoded)


def import_users(target, source_rows: list, *, dry_run: bool = True) -> dict:
    """Commit only complete new migrations; existing inconsistent tables require recovery."""
    with target.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('account-writers'))")
        state = inspect_accounts(target)
        if account_data_complete(state):
            return {"skipped": len(source_rows), "complete": True, "dry_run": dry_run}
        cursor.execute("SAVEPOINT account_migration")
        try:
            cursor.execute(_account_import_sql(source_rows, dry_run=dry_run))
            result = cursor.fetchone()[0]
        except Exception as exc:
            conflict = _migration_conflict(getattr(getattr(exc, "diag", None), "message_primary", ""))
            cursor.execute("ROLLBACK TO SAVEPOINT account_migration")
            cursor.execute("RELEASE SAVEPOINT account_migration")
            if conflict:
                raise conflict from None
            raise
        if dry_run:
            cursor.execute("ROLLBACK TO SAVEPOINT account_migration")
        cursor.execute("RELEASE SAVEPOINT account_migration")
        return result


def _migration_sql(rows, *, dry_run=False):
    """psql releases the entire failed transaction when its connection exits."""
    body = _account_import_sql(rows, dry_run=dry_run)
    return "BEGIN;\n" + r"""
SET LOCAL standard_conforming_strings=on;
SELECT pg_advisory_xact_lock(hashtext('account-writers'));
""" + inspection_sql() + r"""
DO $existing$
DECLARE state json := pg_temp.inspect_local_accounts();
BEGIN
    IF (state->>'account_table')::boolean AND NOT (state->>'complete')::boolean THEN
        RAISE EXCEPTION 'NEXENT_ACCOUNT_INCOMPLETE=%',state->'unresolved_ids';
    END IF;
END
$existing$;
SELECT (pg_temp.inspect_local_accounts()->>'complete')::boolean AS complete \gset
\if :complete
SELECT '{"skipped":true,"complete":true}';
\else
""" + body + "\n\\endif\n" + ("ROLLBACK;" if dry_run else "COMMIT;")


def _docker(*args):
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise MigrationSetupError(
            "Docker is unavailable; start the source database or configure SUPABASE_POSTGRES_HOST/PORT"
        ) from None
    if result.returncode:
        raise MigrationSetupError(
            "Docker source database operation failed; check Docker and the existing container"
        )
    return result.stdout


def prepare_source(params, container=None, *, allow_start=True):
    if not container:
        names = _docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        candidates = [name for name in names if "supabase" in name.lower() and "db" in name.lower()]
        if len(candidates) != 1:
            raise MigrationSetupError(
                "Cannot identify one existing Supabase database container; use --source-container "
                "or configure SUPABASE_POSTGRES_HOST/PORT. No empty database will be created"
            )
        container = candidates[0]
    template = ('{"running":{{json .State.Running}},'
                '"ports":{{json .NetworkSettings.Ports}},"bindings":{{json .HostConfig.PortBindings}}}')
    try:
        state = json.loads(_docker("inspect", "--format", template, container))
    except (TypeError, ValueError):
        raise MigrationSetupError("Cannot read source container state") from None
    if not state.get("running"):
        if not allow_start:
            raise MigrationSetupError("Source container is stopped; start it or remove --no-start-source")
        _docker("start", container)
        try:
            state = json.loads(_docker("inspect", "--format", template, container))
        except (TypeError, ValueError):
            raise MigrationSetupError("Cannot read source container published port") from None
        print("Started the existing Supabase database container; waiting for PostgreSQL.", file=sys.stderr)
    ports = state.get("ports") or state.get("bindings") or {}
    key = str(params["port"]) + "/tcp"
    if key not in ports:
        key = "5432/tcp" if "5432/tcp" in ports else next(iter(ports), "")
    bindings = ports.get(key) or []
    if not bindings or not bindings[0].get("HostPort"):
        raise MigrationSetupError(
            "Source container has no published PostgreSQL port; configure a reachable SUPABASE_POSTGRES_HOST/PORT"
        )
    binding = next((item for item in bindings if item.get("HostIp") != "::"), bindings[0])
    host = binding.get("HostIp") or "127.0.0.1"
    params["host"] = "127.0.0.1" if host == "0.0.0.0" else "::1" if host == "::" else host
    params["port"] = int(binding["HostPort"])
    return container


def source_stack_configuration(values, container):
    """Resolve only the selected local source and configured legacy peers."""

    return configuration({**values, "SUPABASE_MIGRATION_DB_CONTAINER": container})[0]


def cleanup_source_stack(values):
    """Remove source DB/Auth/Kong containers without deleting persistent volumes."""

    execute("down", values)


def docker(args, values):
    env = {**os.environ, **{key: str(value) for key, value in values.items() if value is not None}}
    try:
        result = subprocess.run(["docker", *args], env=env, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise MigrationSetupError("Docker is unavailable or the legacy operation timed out") from None
    if result.returncode:
        raise MigrationSetupError("Legacy Docker operation failed; inspect Docker status, image availability and configuration")
    return result.stdout


def host_path(value):
    if sys.platform == "win32" and re.match(r"^/[A-Za-z]/", str(value)):
        value = str(value)[1].upper() + ":/" + str(value)[3:]
    return Path(value).expanduser().resolve()


def configuration(values):
    values = dict(values)
    project = values.setdefault("SUPABASE_MIGRATION_PROJECT", "nexent-supabase-migration")
    values.setdefault("SUPABASE_MIGRATION_NETWORK", "nexent_supabase_migration")
    values.setdefault("SUPABASE_DB_CONFIG_VOLUME", project + "_db-config")
    names = {service: values.setdefault("SUPABASE_MIGRATION_" + key + "_CONTAINER", default)
             for service, key, default in [("db", "DB", "supabase-db-mini"),
                                          ("auth", "AUTH", "supabase-auth-mini"),
                                          ("kong", "KONG", "supabase-kong-mini")]}
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or "supabase" not in name.lower()
           for name in names.values()) or len(set(names.values())) != 3:
        raise MigrationSetupError("Use three distinct Supabase container names for legacy operations")
    return values, names


def execute(action, values, *, with_auth=False, production=False):
    values, names = configuration(values)
    requested = [names[key] for key in (["db", "auth", "kong"] if with_auth else ["db"])]
    if action == "up":
        data = values.get("SUPABASE_DATA_DIR")
        if not data and values.get("ROOT_DIR"):
            data = str(host_path(values["ROOT_DIR"]) / "volumes/db/data")
        if not data or not (host_path(data) / "PG_VERSION").is_file():
            raise MigrationSetupError("Set ROOT_DIR or SUPABASE_DATA_DIR to original data containing PG_VERSION; refusing empty source initialization")
        values["SUPABASE_DATA_DIR"] = str(host_path(data))
        values["SUPABASE_LOG_DIR"] = str(host_path(values.get("SUPABASE_LOG_DIR") or (
            str(host_path(values["ROOT_DIR"]) / "volumes/logs") if values.get("ROOT_DIR")
            else str(host_path(data).parent / "logs"))))
        values["SUPABASE_POSTGRES_PASSWORD"] = source_password(values)
        if with_auth and any(not values.get(key) for key in ("JWT_SECRET", "SUPABASE_KEY", "SERVICE_ROLE_KEY", "DASHBOARD_PASSWORD")):
            raise MigrationSetupError("Full legacy auth requires the original JWT_SECRET, SUPABASE_KEY, SERVICE_ROLE_KEY and DASHBOARD_PASSWORD")
    existing = set(docker(["ps", "-a", "--format", "{{.Names}}"], values).splitlines())
    if action == "down":
        # Exact legacy names only; never down the application Compose project or remove volumes.
        for name in [names["kong"], names["auth"], names["db"]]:
            if name not in existing:
                continue
            running = docker(["inspect", "--format", "{{json .State.Running}}", name], values).strip()
            if running == "true":
                docker(["stop", name], values)
            docker(["rm", name], values)
        network = values["SUPABASE_MIGRATION_NETWORK"]
        networks = docker(["network", "ls", "--format", "{{.Name}}"], values).splitlines()
        if network in networks and network != "nexent_network":
            project = docker(["network", "inspect", "--format", '{{index .Labels "com.docker.compose.project"}}', network], values).strip()
            if project == values["SUPABASE_MIGRATION_PROJECT"]:
                docker(["network", "rm", network], values)
        return
    present = [name for name in requested if name in existing]
    if present:
        if len(present) != len(requested):
            raise MigrationSetupError("Some legacy containers already exist; use down then up with the original data path to restore the requested stack")
        for name in requested:
            running = docker(["inspect", "--format", "{{json .State.Running}}", name], values).strip()
            if running != "true":
                docker(["start", name], values)
        return
    args = ["compose", "--project-name", values["SUPABASE_MIGRATION_PROJECT"],
            "--project-directory", str(HERE), "-f", str(HERE / "docker-compose-supabase.yml")]
    if production:
        args += ["-f", str(HERE / "docker-compose-supabase.prod.yml")]
    if with_auth:
        args += ["--profile", "legacy-auth"]
    args += ["up", "-d", *(["db", "auth", "kong"] if with_auth else ["db"])]
    docker(args, values)


def _migration_conflict(message):
    """Extract only structured account identifiers, never raw database output."""
    match = re.search(r'(?:^|ERROR:\s*)NEXENT_ACCOUNT_(CONFLICT|INCOMPLETE)=(\[[^\r\n]*\])', message or '', re.M)
    if not match:
        return None
    try:
        ids = json.loads(match.group(2))
        if not isinstance(ids, list) or not ids:
            return None
        if any(not isinstance(value,str) or not 0<len(value)<=100 or any(ord(c)<32 for c in value) for value in ids):
            return None
        ids = sorted(set(ids))
    except (ValueError, TypeError, AttributeError):
        return None
    if match.group(1) == "INCOMPLETE":
        return MigrationConflict("Incomplete account migration IDs: " + json.dumps(ids)
            + "; verify original Supabase coverage and restore missing legacy role/email profiles from backup")
    return MigrationConflict("Account migration conflict IDs: " + json.dumps(ids))


def _command(command, *, data=None, env=None):
    try:
        result = subprocess.run(command, input=data.encode("utf-8") if data is not None else None,
                                env=env, capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise MigrationSetupError("Deployment migration command is unavailable or timed out") from None
    if result.returncode:
        conflict = _migration_conflict(result.stderr.decode("utf-8", errors="replace"))
        if conflict:
            raise conflict
        raise MigrationSetupError("Deployment migration command failed; inspect the selected database/workload readiness")
    return result.stdout.decode("utf-8").strip()


def _exec(args, target, command, data=None):
    prefix = ["docker", "exec", "-i", target] if args.deployment == "docker" else [
        "kubectl", "--namespace", args.namespace, "exec", "-i",
        target if "/" in target else "deployment/" + target, "--",
    ]
    return _command([*prefix, *command], data=data)


def _database_environment(args, target):
    if args.deployment == "docker":
        values = json.loads(_command(["docker", "inspect", "--format", "{{json .Config.Env}}", target]))
    else:
        values = _exec(args, target, ["env"]).splitlines()
    return dict(value.split("=", 1) for value in values if "=" in value)


def _psql(args, target, sql, values, *, source=False):
    inside = _database_environment(args, target)
    prefix = "SUPABASE_" if source else ""
    user = values.get(prefix + "POSTGRES_USER") or inside.get("POSTGRES_USER") or "postgres"
    database = values.get(prefix + "POSTGRES_DB") or inside.get("POSTGRES_DB") or ("supabase" if source else "nexent")
    password = values.get("SUPABASE_POSTGRES_PASSWORD" if source else "NEXENT_POSTGRES_PASSWORD") or inside.get("POSTGRES_PASSWORD") or inside.get("PGPASSWORD")
    if not password:
        raise MigrationSetupError("Original database password is unavailable in deployment/container settings")
    port = inside.get("PGPORT") or "5432"
    shell = 'IFS= read -r encoded; PGPASSWORD="$(printf "%s" "$encoded" | base64 -d)"; export PGPASSWORD; exec "$@"'
    secret_line = base64.b64encode(password.encode()).decode()
    return _exec(args, target, ["sh", "-c", shell, "migration", "psql", "-X", "-qAt",
                 "-h", "127.0.0.1", "-p", port, "-U", user, "-d", database,
                 "-v", "ON_ERROR_STOP=1"], secret_line + "\n" + sql)


def _private_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _source_target(args, values):
    host = values.get("SUPABASE_POSTGRES_HOST")
    if host and host not in {"supabase_db", "supabase-db-mini", "nexent-supabase-db"} and not (
        args.source_container or values.get("SUPABASE_MIGRATION_DB_CONTAINER")
    ):
        return {"remote": True}
    if args.deployment == "docker":
        names = _docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        selected = args.source_container or values.get("SUPABASE_MIGRATION_DB_CONTAINER")
        candidates = [name for name in names if "supabase" in name.lower() and "db" in name.lower()]
        if selected and selected not in names:
            raise MigrationSetupError("Configured source Supabase container is missing")
        if not selected and len(candidates) > 1:
            raise MigrationSetupError("Multiple Supabase databases exist; configure the original source container name")
        selected = selected or (candidates[0] if candidates else None)
        if selected:
            config = source_stack_configuration(values, selected)
            running = _docker("inspect", "--format", "{{json .State.Running}}", selected).strip()
            if running != "true":
                _docker("start", selected)
            return {"target": selected, "configuration": {key: config[key] for key in config if key.startswith("SUPABASE_MIGRATION_")}}
    else:
        selected = args.source_container or "nexent-supabase-db"
        present = _command(["kubectl", "--namespace", args.namespace, "get", "deployment", selected, "--ignore-not-found", "-o", "name"])
        if present:
            return {"target": selected}
    host = values.get("SUPABASE_POSTGRES_HOST")
    if host and host not in {"supabase_db", "supabase-db-mini", "nexent-supabase-db"}:
        return {"remote": True}
    return None


def source_snapshot(args, values, source):
    if source.get("remote"):
        if not values.get("SUPABASE_POSTGRES_PASSWORD"):
            raise MigrationSetupError("Remote source requires SUPABASE_POSTGRES_PASSWORD in deployment settings")
        params = {"host": values["SUPABASE_POSTGRES_HOST"], "port": _port(values.get("SUPABASE_POSTGRES_PORT") or 5436),
                  "dbname": values.get("SUPABASE_POSTGRES_DB") or "supabase", "user": values.get("SUPABASE_POSTGRES_USER") or "postgres",
                  "password": values["SUPABASE_POSTGRES_PASSWORD"], "connect_timeout": 5}
        return _run_worker(args, {"action": "snapshot", "params": params})["rows"]
    # Only account/provider tables are read, in one consistent read-only snapshot.
    sql = r"""BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT coalesce(json_agg(row_to_json(u) ORDER BY id),'[]') FROM auth.users u;
SELECT to_regclass('auth.identities') IS NOT NULL AS has_identities \gset
\if :has_identities
SELECT coalesce(json_agg(row_to_json(i) ORDER BY user_id),'[]') FROM auth.identities i;
\else
SELECT '[]';
\endif
COMMIT;
"""
    deadline = time.monotonic() + args.wait_timeout
    while True:
        try:
            output = _psql(args, source["target"], sql, values, source=True)
            break
        except MigrationSetupError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    users, identities = [json.loads(line) for line in output.splitlines()]
    for user in users:
        user["source_provider_identities"] = [identity for identity in identities if str(identity["user_id"]) == str(user["id"])]
    return users


def _worker(job):
    """Executed in Config's existing Python environment; no host packages needed."""
    import psycopg2

    if job["action"] == "snapshot":
        source = psycopg2.connect(**job["params"])
        try:
            with source:
                source.set_session(readonly=True, isolation_level="REPEATABLE READ")
                print(json.dumps({"rows": read_source_users(source)}))
        finally:
            source.close()
        return
    raise MigrationSetupError("Unsupported migration worker action")


def _run_worker(args, job):
    script = Path(__file__).read_text(encoding="utf-8")
    loader = '''import json,sys
p=json.load(sys.stdin)
n={"__name__":"auth_migration_worker","__file__":"/opt/deploy/sql/tools/supabase_to_postgres/migrate_docker.py"}
exec(compile(p["script"],n["__file__"],"exec"),n)
try:
    n["_worker"](p["job"])
except (n["MigrationSetupError"], n["MigrationConflict"]) as error:
    print(json.dumps({"migration_error":str(error)}))
'''
    result = json.loads(_exec(args, args.config_target, ["python", "-c", loader], json.dumps({"script": script, "job": job})))
    if "migration_error" in result:
        raise MigrationConflict(result["migration_error"])
    return result


def automatic_upgrade(args, *, source_resolver=None, storage_preserver=None):
    values = load_settings(args.env_file)
    state = json.loads(_psql(args, args.database_target,
        inspection_sql(), values))
    if account_data_complete(state):
        return {"skipped": True, "complete": True}
    if not state["legacy"]:
        return {"skipped": True, "new": True}
    source = (source_resolver or _source_target)(args, values)
    if not source:
        raise MigrationSetupError("The original Supabase database is required; restore its original data before retrying")
    # Storage backups are recovery artifacts, never migration completion markers.
    if storage_preserver and not source.get("remote"):
        backup = args.env_file.parent / "backups" / (args.deployment + "-" + args.namespace + "-supabase.json")
        storage_preserver(args, source, backup)
    rows = source_snapshot(args, values, source)
    sql = _migration_sql(rows, dry_run=not args.apply)
    output = _psql(args, args.database_target, sql, values)
    result = json.loads(output.splitlines()[-1])
    if args.apply and not result.get("skipped") and not source.get("remote"):
        try:
            if args.deployment == "docker":
                cleanup_source_stack(source["configuration"])
            else:
                for name in ["nexent-supabase-kong", "nexent-supabase-auth", source["target"]]:
                    _command(["kubectl", "--namespace", args.namespace, "delete", "deployment,service", name, "--ignore-not-found"])
        except Exception:  # noqa: BLE001 -- Cleanup is independent of the committed import.
            # The transaction already committed. Never erase imported credentials
            # after source cleanup has started; report its independent outcome.
            print("Account migration committed; source container cleanup incomplete. Remove the remaining legacy resources manually; data volumes are retained.", file=sys.stderr)
    return result


def container_main(argv=None):
    """Database-only worker; platform lifecycle belongs to the host Shell."""
    import psycopg2

    parser = argparse.ArgumentParser(description="Run account migration inside an isolated container")
    parser.add_argument("--container", action="store_true", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wait-timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if not 1 <= args.wait_timeout <= 300:
        parser.error("--wait-timeout must be between 1 and 300")

    def parameters(prefix, password_key):
        values = os.environ
        required = [prefix + "POSTGRES_HOST", password_key]
        if any(not values.get(key) for key in required):
            raise MigrationSetupError("Database host/password is missing from the migration environment")
        return {
            "host": values[prefix + "POSTGRES_HOST"],
            "port": _port(values.get(prefix + "POSTGRES_PORT") or 5432),
            "dbname": values.get(prefix + "POSTGRES_DB") or ("supabase" if prefix else "nexent"),
            "user": values.get(prefix + "POSTGRES_USER") or "postgres",
            "password": values[password_key], "connect_timeout": 5,
        }

    try:
        with psycopg2.connect(**parameters("", "NEXENT_POSTGRES_PASSWORD")) as target:
            try:
                with target.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('account-writers'))")
                state = inspect_accounts(target)
                complete, legacy = account_data_complete(state), state["legacy"]
                if complete or not legacy:
                    print(json.dumps({"skipped": True, "complete": complete, "new": not legacy}))
                    return 0
                source_params = parameters("SUPABASE_", "SUPABASE_POSTGRES_PASSWORD")
                deadline = time.monotonic() + args.wait_timeout
                while True:
                    try:
                        source = psycopg2.connect(**source_params)
                        break
                    except psycopg2.OperationalError:
                        if time.monotonic() >= deadline:
                            raise MigrationSetupError("Original Supabase is unavailable; check source readiness and credentials") from None
                        time.sleep(1)
                try:
                    with source:
                        source.set_session(readonly=True, isolation_level="REPEATABLE READ")
                        rows = read_source_users(source)
                        print("[account-migration][snapshot] Source rows=" + str(len(rows))
                              + " rows_with_password=" + str(sum(bool(row.get("encrypted_password")) for row in rows)), file=sys.stderr)
                finally:
                    source.close()
                result = import_users(target, rows, dry_run=not args.apply)
            except Exception:
                target.rollback()
                raise
        result["committed"] = args.apply and not result.get("complete", False)
        print(json.dumps(result))
        return 0
    except (MigrationConflict, MigrationSetupError) as error:
        print("Account upgrade rejected: " + str(error), file=sys.stderr)
    except Exception as error:  # noqa: BLE001 -- Never log driver text or credentials.
        print("Account upgrade failed (" + type(error).__name__ + "); target transaction rolled back", file=sys.stderr)
    finally:
        if "target" in locals():
            target.close()
    return 1


def main(*, upgrade=automatic_upgrade):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["up", "down"], help="Manual legacy stack recovery/removal")
    parser.add_argument("--with-auth", action="store_true")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--deploy", action="store_true", help="Upgrade through the deployment database container or pod")
    parser.add_argument("--deployment", choices=["docker", "kubernetes"], default="docker")
    parser.add_argument("--namespace", default="nexent")
    parser.add_argument("--database-target", default="nexent-postgresql")
    parser.add_argument("--config-target", default="nexent-config")
    parser.add_argument("--apply", action="store_true", help="Write after preflight; default is dry-run")
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy/env/.env")
    parser.add_argument("--source-container", help="Existing local Supabase database container name")
    parser.add_argument("--no-start-source", action="store_true", help="Fail if the local source container is stopped")
    parser.add_argument("--wait-timeout", type=int, default=30, help="Source readiness timeout in seconds")
    args = parser.parse_args()
    if args.wait_timeout < 1 or args.wait_timeout > 300:
        parser.error("--wait-timeout must be between 1 and 300")
    if args.deploy or args.action:
        try:
            if args.deploy:
                print(json.dumps(upgrade(args)))
            else:
                execute(args.action, load_settings(args.env_file), with_auth=args.with_auth, production=args.production)
                print("Legacy Supabase operation completed; data volumes are retained.")
            return 0
        except (MigrationSetupError, MigrationConflict) as exc:
            print("Account upgrade rejected: " + str(exc), file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 -- Never expose raw database/container credentials.
            print("Account upgrade failed (" + type(exc).__name__ + "); target changes were rolled back; retry with the original source.", file=sys.stderr)
        return 1
    import psycopg2


    try:
        values = load_settings(args.env_file)
        target_params = target_connection(values)
        target = psycopg2.connect(**target_params)
        try:
            with target, target.cursor() as cursor:
                cursor.execute(inspection_sql())
                complete = account_data_complete(cursor.fetchone()[0])
        finally:
            target.close()
        if complete:
            print(json.dumps({"skipped": True, "complete": True, "dry_run": not args.apply}))
            return 0
        source_params, _, managed = connections(values)
        cleanup_values = None
        if managed or args.source_container:
            selected = prepare_source(source_params, args.source_container, allow_start=not args.no_start_source)
            if args.apply:
                cleanup_values = source_stack_configuration(values, selected)
        deadline = time.monotonic() + args.wait_timeout
        while True:
            try:
                source = psycopg2.connect(**source_params)
                break
            except psycopg2.OperationalError:
                if not managed or time.monotonic() >= deadline:
                    raise MigrationSetupError(
                        "Cannot connect to source PostgreSQL; check its readiness, published port and source password"
                    ) from None
                time.sleep(1)
        try:
            with source:
                source.set_session(readonly=True, isolation_level="REPEATABLE READ")
                rows = read_source_users(source)
        finally:
            source.close()
        target = psycopg2.connect(**target_params)
        try:
            with target:
                result = import_users(target, rows, dry_run=not args.apply)
        finally:
            target.close()
        if cleanup_values is not None and not result.get("complete"):
            try:
                cleanup_source_stack(cleanup_values)
                print("Removed source Supabase DB/Auth/Kong containers; data volumes and backups were retained.", file=sys.stderr)
            except Exception:  # noqa: BLE001 -- Never discard committed accounts after cleanup starts.
                print("Account migration committed; source cleanup failed. Remove remaining legacy resources manually; data volumes are retained.", file=sys.stderr)
        print(json.dumps(result))
        return 0
    except (MigrationConflict, MigrationSetupError) as exc:
        print("Account migration preflight rejected: " + str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- Never expose raw database/container credentials.
        print("Account migration failed (" + type(exc).__name__
              + "); inspect prerequisites and run preflight again.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(container_main() if "--container" in sys.argv else main())
