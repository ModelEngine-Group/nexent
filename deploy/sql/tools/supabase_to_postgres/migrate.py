# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Standalone historical account migration and deployment upgrade coordinator."""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
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
AUTH_SQL = "v2.9.0_001_local_user_accounts.sql"
DATA_MARKER = "__local_auth_data_2.9.0__"
CLEANUP_MARKER = "__local_auth_cleanup_2.9.0__"


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
    # An explicitly reachable host uses that connection directly; service aliases
    # and defaults retain automatic local container discovery/startup.
    return source, target, service_host or not values.get("SUPABASE_POSTGRES_HOST")


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
        cas_only = (row.get("raw_user_meta_data") or {}).get("provider") == "cas"
        return {
            "user_id": user_id,
            "email": email,
            "password_hash": encoded,
            "password_hash_scheme": scheme,
            "password_login_enabled": bool(encoded) and not cas_only,
            "account_status": "disabled" if disabled else "active",
            "token_version": 0,
            "email_confirmed_at": utc_time(row.get("email_confirmed_at")),
            "create_time": utc_time(row.get("created_at")) or datetime.now(timezone.utc).replace(tzinfo=None),
            "update_time": utc_time(row.get("updated_at")) or datetime.now(timezone.utc).replace(tzinfo=None),
            "delete_flag": "Y" if deleted else "N",
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


def import_users(target, source_rows: list, *, dry_run: bool = True) -> dict:
    """Import credentials, hydrating only schema-created pending identities."""
    from psycopg2.extras import Json, RealDictCursor

    rows = [map_source_user(row) for row in source_rows]
    ids, emails = set(), set()
    for row in rows:
        if row["user_id"] in ids or (row["delete_flag"] == "N" and row["email"] in emails):
            raise MigrationConflict("Source has conflicting stable IDs or normalized emails")
        ids.add(row["user_id"])
        if row["delete_flag"] == "N":
            emails.add(row["email"])
    result = {"source": len(rows), "inserted": 0, "updated": 0, "skipped": 0,
              "disabled_orphans": 0, "dry_run": dry_run}
    plans = []
    with target.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('account-writers'))")
        for row in rows:
            cursor.execute(
                "SELECT user_id,user_email,source_metadata,password_hash,token_version,delete_flag,user_role "
                "FROM nexent.user_account_t WHERE user_id=%s OR (user_email=%s AND delete_flag='N' AND %s='N') FOR UPDATE",
                (row["user_id"], row["email"], row["delete_flag"]),
            )
            existing = cursor.fetchall()
            pending = False
            if existing:
                account = existing[0]
                profile_pending = (len(existing) == 1 and (account["source_metadata"] or {}).get("credential_migration_pending") is True
                           and account["password_hash"] is None and account["token_version"] == 0)
                pending = profile_pending and account["delete_flag"] == "N"
                if (len(existing) != 1 or account["user_id"] != row["user_id"]
                        or (account["user_email"] != row["email"] and not (profile_pending and account["user_email"] is None))):
                    raise MigrationConflict("Target account conflicts with a source identity")
                if not pending:
                    result["skipped"] += 1
                    continue
            cursor.execute("SELECT delete_flag FROM nexent.user_tenant_t WHERE user_id=%s", (row["user_id"],))
            active = [member for member in cursor.fetchall() if member["delete_flag"] == "N"]
            if active and not existing:
                raise MigrationConflict("Membership account profile is missing; apply the account SQL migration first")
            if not active or (pending and not account["user_role"]):
                row["account_status"] = "disabled"
                result["disabled_orphans"] += 1
            values = dict(row)
            values["user_email"] = values.pop("email")
            if not pending:
                values["user_role"] = None
            plans.append((pending, values))
            result["updated" if pending else "inserted"] += 1
        if dry_run:
            return result
        for pending, row in plans:
            values = dict(row, source_metadata=Json(row["source_metadata"]))
            if pending:
                user_id = values.pop("user_id")
                cursor.execute(
                    "UPDATE nexent.user_account_t SET " + ",".join(name + "=%s" for name in values)
                    + ",updated_by='auth-migration' WHERE user_id=%s AND password_hash IS NULL AND token_version=0 "
                    "AND delete_flag='N' AND source_metadata->>'credential_migration_pending'='true'",
                    [*values.values(), user_id],
                )
                if cursor.rowcount != 1:
                    raise MigrationConflict("Pending account changed concurrently; retry preflight")
            else:
                names = list(values)
                cursor.execute(
                    "INSERT INTO nexent.user_account_t (" + ",".join(names) + ",created_by,updated_by) VALUES ("
                    + ",".join(["%s"] * len(names)) + ",%s,%s)",
                    [*values.values(), "auth-migration", "auth-migration"],
                )
    return result


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


def _command(command, *, data=None, env=None):
    try:
        result = subprocess.run(command, input=data.encode("utf-8") if data is not None else None,
                                env=env, capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise MigrationSetupError("Deployment migration command is unavailable or timed out") from None
    if result.returncode:
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


def _history_table(values):
    name = values.get("NEXENT_SQL_MIGRATION_TABLE") or "nexent.schema_migrations"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)?", name):
        raise MigrationSetupError("Invalid SQL migration table name")
    return ".".join('"' + part + '"' for part in name.split("."))


def deployment_status(args, values):
    table = _history_table(values)
    plain = table.replace('"', '')
    sql = rf"""
SELECT to_regclass('{plain}') IS NOT NULL AS has_history \gset
\if :has_history
SELECT coalesce(json_agg(row_to_json(m)), '[]') FROM {table} m
WHERE migration_id IN ('{AUTH_SQL}','{DATA_MARKER}','{CLEANUP_MARKER}');
\else
SELECT '[]';
\endif
SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='source_metadata') AS has_accounts \gset
\if :has_accounts
SELECT json_build_object('pending',count(*)) FROM nexent.user_account_t
WHERE delete_flag='N' AND source_metadata->>'credential_migration_pending'='true';
\else
SELECT '{{"pending":0}}';
\endif
SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_tenant_t' AND column_name='user_email') AS has_legacy \gset
\if :has_legacy
SELECT json_build_object('legacy_logins',exists(SELECT 1 FROM nexent.user_tenant_t WHERE delete_flag='N' AND nullif(trim(user_email),'') IS NOT NULL));
\else
SELECT '{{"legacy_logins":false}}';
\endif
"""
    rows = _psql(args, args.database_target, sql, values).splitlines()
    history = {row["migration_id"]: row for row in json.loads(rows[0]) if row["status"] in {"applied", "baselined"}}
    return {"history": history, **json.loads(rows[1]), **json.loads(rows[2])}


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


def _preserve_source_storage(args, source, path):
    if args.deployment != "kubernetes":
        return
    prefix = ["kubectl", "--namespace", args.namespace]
    claim = _command([*prefix, "get", "pvc", source["target"], "--ignore-not-found", "-o", "json"])
    if not claim:
        return
    claim = json.loads(claim)
    volume_name = claim.get("spec", {}).get("volumeName")
    if not volume_name:
        raise MigrationSetupError("Source Supabase PVC is not bound; preserving the old release")
    volume = json.loads(_command(["kubectl", "get", "pv", volume_name, "-o", "json"]))
    _private_json(path.with_name(path.stem + "-storage.json"), {"claim": claim, "volume": volume})
    if volume["spec"].get("persistentVolumeReclaimPolicy") != "Retain":
        _command(["kubectl", "patch", "pv", volume_name, "--type=merge", "-p", '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'])


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
    values = dict(os.environ)
    params = {"host": values.get("POSTGRES_HOST") or "nexent-postgresql",
              "port": int(values.get("POSTGRES_PORT") or 5432), "dbname": values.get("POSTGRES_DB") or "nexent",
              "user": values.get("POSTGRES_USER") or "root", "password": values.get("NEXENT_POSTGRES_PASSWORD"),
              "connect_timeout": 5}
    table = _history_table(values)
    connection = psycopg2.connect(**params)
    try:
        with connection:  # noqa: SIM117 -- Close the cursor before committing the transaction.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext('local-auth-upgrade'))")
                cursor.execute(f"SELECT checksum FROM {table} WHERE migration_id=%s AND status IN ('applied','baselined')", (AUTH_SQL,))
                sql_record = cursor.fetchone()
                if not sql_record or sql_record[0] != job["checksum"]:
                    raise MigrationSetupError("Account SQL has not reached the expected version/checksum")
                marker = CLEANUP_MARKER if job["action"] == "cleanup" else DATA_MARKER
                cursor.execute(f"SELECT checksum FROM {table} WHERE migration_id=%s", (marker,))
                recorded = cursor.fetchone()
                pending = False
                if marker == DATA_MARKER:
                    cursor.execute("SELECT count(*) FROM nexent.user_account_t WHERE delete_flag='N' AND source_metadata->>'credential_migration_pending'='true'")
                    pending = bool(cursor.fetchone()[0])
                if recorded and recorded[0] == job["checksum"] and not pending:
                    result = {"automatic": True, "skipped": True}
                else:
                    result = import_users(connection, job.get("rows", []), dry_run=False) if marker == DATA_MARKER else {"cleanup": True}
                    if marker == DATA_MARKER:
                        cursor.execute("SELECT count(*) FROM nexent.user_account_t WHERE delete_flag='N' AND source_metadata->>'credential_migration_pending'='true'")
                        if cursor.fetchone()[0]:
                            raise MigrationConflict("Historical account credentials remain pending; source snapshot is incomplete")
                    cursor.execute(f"INSERT INTO {table} (migration_id,checksum,status,app_version,source_file) VALUES (%s,%s,'applied','2.9.0',%s) ON CONFLICT (migration_id) DO UPDATE SET checksum=excluded.checksum,status='applied',executed_at=now(),app_version=excluded.app_version,source_file=excluded.source_file",
                                   (marker, job["checksum"], str(HERE / "migrate.py")))
        print(json.dumps(result))
    finally:
        connection.close()


def _run_worker(args, job):
    script = Path(__file__).read_text(encoding="utf-8")
    loader = '''import json,sys
p=json.load(sys.stdin)
n={"__name__":"auth_migration_worker","__file__":"/opt/deploy/sql/tools/supabase_to_postgres/migrate.py"}
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
    # deploy.sh has already exported its complete root environment. This path
    # deliberately imports no database/dotenv libraries on the deployment host.
    values = dict(os.environ)
    sql_file = ROOT / "deploy/sql/migrations" / AUTH_SQL
    checksum = hashlib.sha256(sql_file.read_bytes()).hexdigest()
    path = (args.state_dir or args.env_file.parent / ".migration-state") / (args.deployment + "-" + args.namespace + "-" + AUTH_SQL + ".json")
    status = deployment_status(args, values)
    complete = not status["pending"] and all(status["history"].get(marker, {}).get("checksum") == checksum for marker in [AUTH_SQL, DATA_MARKER, CLEANUP_MARKER])
    target = {"deployment": args.deployment, "namespace": args.namespace, "database": args.database_target,
              "dbname": values.get("POSTGRES_DB") or "nexent"}
    if getattr(args, "cluster_identity", None):
        target["cluster"] = args.cluster_identity
    snapshot = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if snapshot and snapshot["target"] != target:
        raise MigrationSetupError("Retained account snapshot belongs to a different deployment target")
    if complete:
        if path.exists():
            path.unlink()
        return {"automatic": True, "skipped": True}
    if args.deploy_phase == "prepare":
        if snapshot:
            return {"automatic": True, "prepared": True, "retained": True}
        source = (source_resolver or _source_target)(args, values)
        if not source and (status["pending"] or status["legacy_logins"]):
            raise MigrationSetupError("Historical login accounts need the original Supabase source; old application rollout was preserved")
        if source and not source.get("remote"):
            (storage_preserver or _preserve_source_storage)(args, source, path)
        rows = source_snapshot(args, values, source) if source else []
        # Validate the complete snapshot before application replacement.
        for row in rows:
            map_source_user(row)
        _private_json(path, {"target": target, "source": source, "rows": rows})
        return {"automatic": True, "prepared": True, "source": len(rows)}
    if not snapshot:
        raise MigrationSetupError("Deployment account snapshot is missing; rerun deploy.sh from the prepare phase")
    deadline = time.monotonic() + args.wait_timeout
    while status["history"].get(AUTH_SQL, {}).get("checksum") != checksum:
        if time.monotonic() >= deadline:
            raise MigrationSetupError("Waiting for the versioned account SQL timed out; snapshot was retained")
        time.sleep(1)
        status = deployment_status(args, values)
    result = _run_worker(args, {"action": "apply", "checksum": checksum, "rows": snapshot["rows"]})
    source = snapshot["source"]
    if source and not source.get("remote"):
        if args.deployment == "docker":
            cleanup_source_stack(source["configuration"])
        else:
            for name in ["nexent-supabase-kong", "nexent-supabase-auth", source["target"]]:
                _command(["kubectl", "--namespace", args.namespace, "delete", "deployment,service", name, "--ignore-not-found"])
    _run_worker(args, {"action": "cleanup", "checksum": checksum})
    path.unlink(missing_ok=True)
    return result


def main(*, upgrade=automatic_upgrade):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["up", "down"], help="Manual legacy stack recovery/removal")
    parser.add_argument("--with-auth", action="store_true")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--deploy-phase", choices=["prepare", "apply"])
    parser.add_argument("--deployment", choices=["docker", "kubernetes"], default="docker")
    parser.add_argument("--namespace", default="nexent")
    parser.add_argument("--database-target", default="nexent-postgresql")
    parser.add_argument("--config-target", default="nexent-config")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write after preflight; default is dry-run")
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy/env/.env")
    parser.add_argument("--source-container", help="Existing local Supabase database container name")
    parser.add_argument("--no-start-source", action="store_true", help="Fail if the local source container is stopped")
    parser.add_argument("--wait-timeout", type=int, default=30, help="Source readiness timeout in seconds")
    args = parser.parse_args()
    if args.deploy_phase == "apply" and not args.apply:
        parser.error("--deploy-phase apply requires --apply")
    if args.wait_timeout < 1 or args.wait_timeout > 300:
        parser.error("--wait-timeout must be between 1 and 300")
    if args.deploy_phase or args.action:
        try:
            if args.deploy_phase:
                print(json.dumps(upgrade(args)))
            else:
                execute(args.action, load_settings(args.env_file), with_auth=args.with_auth, production=args.production)
                print("Legacy Supabase operation completed; data volumes are retained.")
            return 0
        except (MigrationSetupError, MigrationConflict) as exc:
            print("Account upgrade rejected: " + str(exc), file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 -- Never expose raw database/container credentials.
            print("Account upgrade failed (" + type(exc).__name__ + "); retained migration state is available for retry.", file=sys.stderr)
        return 1
    import psycopg2


    cleanup_started = False
    try:
        values = load_settings(args.env_file)
        source_params, target_params, managed = connections(values)
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
        if cleanup_values is not None:
            cleanup_started = True
            cleanup_source_stack(cleanup_values)
            print("Removed source Supabase DB/Auth/Kong containers; data volumes and backups were retained.", file=sys.stderr)
        print(json.dumps(result))
        return 0
    except (MigrationConflict, MigrationSetupError) as exc:
        prefix = "Account migration committed; source cleanup failed: " if cleanup_started else "Account migration preflight rejected: "
        print(prefix + str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 -- Never expose raw database/container credentials.
        print(("Account migration committed; source cleanup failed (" if cleanup_started else "Account migration failed (") + type(exc).__name__
              + "); inspect prerequisites and run preflight again.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
