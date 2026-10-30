# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned Docker resources for a real migration source lifecycle assertion."""

import json
import os
import subprocess
import sys
import time
from uuid import uuid4

import psycopg2
from psycopg2.extensions import parse_dsn


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout.strip()


def assert_source_cleanup(root, target):
    run_id = uuid4().hex
    names = {kind: "supabase-auth-test-" + kind + "-" + run_id for kind in ["db", "auth", "kong"]}
    volume = "auth-source-test-" + run_id
    unrelated = "unrelated-auth-test-" + run_id
    password = "SourceTestOnly123"
    docker("volume", "create", "--label", "codex.test=" + run_id, volume)
    try:
        docker("run", "-d", "--name", names["db"], "--label", "codex.test=" + run_id,
               "-e", "POSTGRES_PASSWORD=" + password, "-p", "127.0.0.1::5432",
               "-v", volume + ":/var/lib/postgresql/data", "postgres:15-alpine")
        for kind in ["auth", "kong"]:
            docker("run", "-d", "--name", names[kind], "--label", "codex.test=" + run_id,
                   "--entrypoint", "sh", "postgres:15-alpine", "-c", "sleep 300")
        docker("run", "-d", "--name", unrelated, "--label", "codex.test=" + run_id,
               "--entrypoint", "sh", "postgres:15-alpine", "-c", "sleep 300")
        port = json.loads(docker("inspect", "--format", '{{json .NetworkSettings.Ports}}', names["db"]))["5432/tcp"][0]["HostPort"]
        deadline = time.monotonic() + 30
        while True:
            try:
                source = psycopg2.connect(host="127.0.0.1", port=port, user="postgres", password=password, dbname="postgres")
                break
            except psycopg2.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        try:
            with source, source.cursor() as cursor:
                cursor.execute("CREATE SCHEMA auth; CREATE TABLE auth.users (id uuid,email text,encrypted_password text)")
            docker("exec", names["db"], "sh", "-c", "printf retained-backup > /var/lib/postgresql/data/migration-test-backup")
            docker("stop", names["db"])
            params = parse_dsn(target)
            env = {**os.environ, "SUPABASE_POSTGRES_HOST": "supabase_db", "SUPABASE_POSTGRES_DB": "postgres",
                   "SUPABASE_POSTGRES_PASSWORD": password, "SUPABASE_POSTGRES_USER": "postgres",
                   "POSTGRES_HOST": params["host"], "POSTGRES_PORT": params["port"], "POSTGRES_DB": params["dbname"],
                   "POSTGRES_USER": params["user"], "NEXENT_POSTGRES_PASSWORD": params["password"],
                   "SUPABASE_MIGRATION_DB_CONTAINER": names["db"], "SUPABASE_MIGRATION_AUTH_CONTAINER": names["auth"],
                   "SUPABASE_MIGRATION_KONG_CONTAINER": names["kong"], "SUPABASE_MIGRATION_NETWORK": "unused-" + run_id}
            command = [sys.executable, str(root / "deploy/sql/tools/supabase_to_postgres/migrate.py"), "--source-container", names["db"], "--wait-timeout", "30"]
            preview = subprocess.run(command, env=env, capture_output=True, text=True)
            assert preview.returncode == 0, preview.stderr
            assert json.loads(preview.stdout)["dry_run"]
            assert all(name in docker("ps", "-a", "--format", "{{.Names}}").splitlines() for name in names.values())
            # Source connection was closed by docker stop; connect again.
            source.close()
            port = json.loads(docker("inspect", "--format", '{{json .NetworkSettings.Ports}}', names["db"]))["5432/tcp"][0]["HostPort"]
            source = psycopg2.connect(host="127.0.0.1", port=port, user="postgres", password=password, dbname="postgres")
            with source, source.cursor() as cursor:
                cursor.execute("INSERT INTO auth.users VALUES (%s,'broken@example.com','unsupported-hash')", (str(uuid4()),))
            failed = subprocess.run([*command, "--apply"], env=env, capture_output=True, text=True)
            assert failed.returncode == 1
            assert all(name in docker("ps", "-a", "--format", "{{.Names}}").splitlines() for name in names.values())
            with source, source.cursor() as cursor:
                cursor.execute("DELETE FROM auth.users")
            applied = subprocess.run([*command, "--apply"], env=env, capture_output=True, text=True)
            assert applied.returncode == 0, applied.stderr
            assert json.loads(applied.stdout)["dry_run"] is False
            assert all(name not in docker("ps", "-a", "--format", "{{.Names}}").splitlines() for name in names.values())
            assert unrelated in docker("ps", "--format", "{{.Names}}").splitlines()
            assert docker("volume", "inspect", "--format", '{{index .Labels "codex.test"}}', volume) == run_id
            # The retained volume can still start the original database data.
            docker("run", "-d", "--name", names["db"], "--label", "codex.test=" + run_id,
                   "-v", volume + ":/var/lib/postgresql/data", "postgres:15-alpine")
            deadline = time.monotonic() + 30
            while True:
                ready = subprocess.run(["docker", "exec", names["db"], "pg_isready", "-U", "postgres"], capture_output=True)
                if ready.returncode == 0:
                    break
                assert time.monotonic() < deadline, "Retained source data did not restart"
                time.sleep(0.2)
            assert "auth.users" in docker("exec", names["db"], "psql", "-U", "postgres", "-Atc", "SELECT to_regclass('auth.users')")
            assert docker("exec", names["db"], "cat", "/var/lib/postgresql/data/migration-test-backup") == "retained-backup"
        finally:
            source.close()
    finally:
        existing = docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        for name in [*names.values(), unrelated]:
            if name in existing and docker("inspect", "--format", '{{index .Config.Labels "codex.test"}}', name) == run_id:
                docker("rm", "-f", name)
        if docker("volume", "inspect", "--format", '{{index .Labels "codex.test"}}', volume) == run_id:
            docker("volume", "rm", volume)
