# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real deployment coordinator, SQL runner, import failure and recovery proof."""

import json
import os
import subprocess
import time
from uuid import uuid4

import bcrypt


def docker(*args, data=None):
    result = subprocess.run(["docker", *args], input=data.encode() if data is not None else None, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.decode().strip()


def assert_automatic_upgrade(root, temporary):
    run_id = uuid4().hex
    names = {key: "supabase-auto-" + key + "-" + run_id for key in ["db", "auth", "kong"]}
    target = "auth-auto-target-" + run_id
    worker = "auth-auto-config-" + run_id
    network = "auth-auto-network-" + run_id
    label = "codex.test=" + run_id
    password = "IsolatedAutoTest123"
    user_id = str(uuid4())
    encoded = bcrypt.hashpw(b"original-password", bcrypt.gensalt(rounds=4)).decode()
    sql_file = root / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql"
    env = {**os.environ, "SUPABASE_MIGRATION_DB_CONTAINER": names["db"],
           "SUPABASE_MIGRATION_AUTH_CONTAINER": names["auth"], "SUPABASE_MIGRATION_KONG_CONTAINER": names["kong"],
           "SUPABASE_POSTGRES_USER": "postgres", "SUPABASE_POSTGRES_DB": "postgres",
           "POSTGRES_USER": "postgres", "POSTGRES_DB": "postgres", "NEXENT_POSTGRES_PASSWORD": password, "APP_VERSION": "2.9.0"}
    # Automatic mode must recover the source password from the original container.
    env.pop("SUPABASE_POSTGRES_PASSWORD", None)
    env_file = temporary / ".env"
    env_file.write_text("")
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "bash"

    def phase(name, success=True):
        shell = 'source "$1/deploy/common/common.sh"; export DEPLOYMENT_ROOT_ENV="$2"; deployment_upgrade_local_accounts "$3" docker nexent "$4" "$5"'
        result = subprocess.run([bash, "-c", shell, "case", root.as_posix(), env_file.as_posix(), name, target, worker],
                                env=env, capture_output=True, text=True, check=False)
        assert result.returncode == (0 if success else 1), result.stdout + result.stderr
        assert encoded not in result.stdout + result.stderr
        if not success:
            return result
        output = (result.stdout.strip().splitlines() or [""])[-1]
        return json.loads(output) if output.startswith("{") else {"skipped": True}

    def query(sql):
        return docker("exec", "-i", target, "psql", "-U", "postgres", "-qAt", "-v", "ON_ERROR_STOP=1", data=sql)

    docker("network", "create", "--label", label, network)
    try:
        for name in [target, names["db"]]:
            docker("run", "-d", "--name", name, "--label", label, "--network", network,
                   "-e", "POSTGRES_PASSWORD=" + password, "postgres:15-alpine")
        for name in [names["auth"], names["kong"]]:
            docker("run", "-d", "--name", name, "--label", label,
                   "--entrypoint", "sh", "postgres:15-alpine", "-c", "sleep 600")
        docker("run", "-d", "--name", worker, "--label", label, "--network", network,
               "-e", "POSTGRES_HOST=" + target, "-e", "POSTGRES_USER=postgres", "-e", "POSTGRES_DB=postgres",
               "-e", "POSTGRES_PORT=5432", "-e", "NEXENT_POSTGRES_PASSWORD=" + password,
               "--entrypoint", "sh", "nexent/nexent:latest", "-c", "sleep 600")
        for name in [target, names["db"]]:
            deadline = time.monotonic() + 30
            while subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], capture_output=True, check=False).returncode:
                assert time.monotonic() < deadline
                time.sleep(0.2)
        docker("exec", "-i", names["db"], "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
               data="CREATE SCHEMA auth; CREATE TABLE auth.users (id uuid,email text,encrypted_password text);"
                    f"INSERT INTO auth.users VALUES ('{user_id}','auto@example.com','{encoded}');")
        assert phase("prepare")["skipped"]  # No prior SQL version is a fresh installation.
        query("CREATE SCHEMA nexent; CREATE TABLE nexent.user_tenant_t (user_id varchar(100),tenant_id varchar(100),"
              "user_role varchar(30),user_email varchar(255),delete_flag varchar(1) DEFAULT 'N');"
              f"INSERT INTO nexent.user_tenant_t VALUES ('{user_id}','retained-tenant','SU','auto@example.com','N');")
        query("INSERT INTO nexent.user_tenant_t VALUES ('user_id','tenant_id','SPEED',NULL,'N');")
        query("CREATE TABLE nexent.schema_migrations (migration_id text PRIMARY KEY,checksum text NOT NULL,status text NOT NULL DEFAULT 'applied',executed_at timestamptz DEFAULT now(),app_version text,source_file text); "
              "INSERT INTO nexent.schema_migrations (migration_id,checksum,app_version) VALUES ('v2.8.3_001_previous.sql','synthetic','2.8.3')")
        env["APP_VERSION"] = "2.8.3"
        assert phase("prepare")["skipped"]
        env["APP_VERSION"] = "2.9.0"
        query("UPDATE nexent.schema_migrations SET app_version='latest'")
        phase("prepare", success=False)
        query("UPDATE nexent.schema_migrations SET app_version='2.8.3'")
        query("CREATE TABLE nexent.user_token_info_t (user_id varchar(100),delete_flag varchar(1)); "
              "INSERT INTO nexent.user_tenant_t VALUES ('api-only','api-tenant','USER',NULL,'N'); "
              "INSERT INTO nexent.user_token_info_t VALUES ('api-only','Y')")
        docker("stop", names["db"])
        assert phase("prepare")["source"] == 1
        snapshots = list((temporary / ".migration-state").glob("*.json"))
        assert len(snapshots) == 1
        assert json.loads(snapshots[0].read_text())["rows"][0]["encrypted_password"] == encoded
        docker("exec", worker, "mkdir", "-p", "/tmp/auth-migrations")
        docker("cp", str(sql_file), worker + ":/tmp/auth-migrations/" + sql_file.name)
        runner = (root / "deploy/common/run-sql-migrations.sh").read_text(encoding="utf-8")
        docker("exec", "-i", worker, "sh", "-c", "cat > /tmp/run-auth-sql.sh", data=runner)
        docker("exec", "-i", worker, "sh", "-c", "cat > /tmp/init-auth.sql", data="CREATE SCHEMA IF NOT EXISTS nexent;\n")
        sql_command = ["exec", "-e", "NEXENT_APP_VERSION=2.9.0", "-e", "NEXENT_SQL_MIGRATION_DIR=/tmp/auth-migrations", "-e", "NEXENT_SQL_INIT_FILE=/tmp/init-auth.sql",
                       worker, "bash", "/tmp/run-auth-sql.sh", "--migrate"]
        docker(*sql_command)
        assert query("SELECT count(*) FROM nexent.schema_migrations WHERE migration_id='v2.9.0_001_local_user_accounts.sql'") == "1"
        assert query("SELECT source_metadata->>'system_identity' FROM nexent.user_account_t WHERE user_id='user_id'") == "speed"
        # An import failure after SQL completion must not create the data checkpoint.
        query(f"UPDATE nexent.user_account_t SET user_email='conflicting@example.com' WHERE user_id='{user_id}'")
        phase("apply", success=False)
        assert snapshots[0].is_file()
        assert not json.loads(snapshots[0].read_text()).get("imported")
        assert all(name in docker("ps", "-a", "--format", "{{.Names}}").splitlines() for name in names.values())
        query(f"UPDATE nexent.user_account_t SET user_email='auto@example.com' WHERE user_id='{user_id}'")
        assert phase("prepare")["retained"]
        assert phase("apply")["updated"] == 1
        assert not snapshots[0].exists()
        assert all(name not in docker("ps", "-a", "--format", "{{.Names}}").splitlines() for name in names.values())
        stored = query(f"SELECT password_hash FROM nexent.user_account_t WHERE user_id='{user_id}'")
        assert stored == encoded and bcrypt.checkpw(b"original-password", stored.encode())
        assert query(f"SELECT tenant_id FROM nexent.user_tenant_t WHERE user_id='{user_id}'") == "retained-tenant"
        assert query("SELECT account_status FROM nexent.user_account_t WHERE user_id='api-only'") == 'active'
        assert query("SELECT delete_flag FROM nexent.user_token_info_t WHERE user_id='api-only'") == 'Y'
        # Same/later SQL versions must skip data migration regardless of account
        # state or a schema checksum change. No source is rediscovered.
        query("UPDATE nexent.user_account_t SET source_metadata='{\"credential_migration_pending\":true}'; "
              "UPDATE nexent.schema_migrations SET checksum='different' WHERE migration_id='v2.9.0_001_local_user_accounts.sql'")
        assert phase("prepare")["skipped"]
        assert phase("apply")["skipped"]
        query("INSERT INTO nexent.schema_migrations (migration_id,checksum,app_version) VALUES ('v3.0.0_001_future.sql','future','3.0.0')")
        assert phase("prepare")["skipped"]

    finally:
        existing = docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        for name in [*names.values(), target, worker]:
            if name in existing and docker("inspect", "--format", '{{index .Config.Labels "codex.test"}}', name) == run_id:
                docker("rm", "-f", name)
        if docker("network", "inspect", "--format", '{{index .Labels "codex.test"}}', network) == run_id:
            docker("network", "rm", network)
