# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Manually recover/remove legacy Supabase containers while retaining database data."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from deploy.sql.tools.supabase_to_postgres.settings import MigrationSetupError, load_settings, source_password

HERE = Path(__file__).resolve().parent


def docker(args, values):
    env = {**os.environ, **{key: str(value) for key, value in values.items() if value is not None}}
    try:
        result = subprocess.run(["docker", *args], env=env, capture_output=True, text=True, timeout=180)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down"])
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy/env/.env")
    parser.add_argument("--with-auth", action="store_true", help="Include old GoTrue/Kong services on startup")
    parser.add_argument("--production", action="store_true", help="Use the relocated production compatibility overlay")
    args = parser.parse_args()
    try:
        execute(args.action, load_settings(args.env_file), with_auth=args.with_auth, production=args.production)
        print("Legacy Supabase operation completed; database directories and volumes are retained.")
        return 0
    except MigrationSetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print("Legacy operation failed (" + type(exc).__name__ + "); check prerequisites.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
