# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real deployment coordinator, SQL runner, import failure and recovery proof."""

import io
import json
import os
import subprocess
import tarfile
import time
from uuid import uuid4

import bcrypt


def docker(*args, data=None):
    result = subprocess.run(["docker", *args], input=data.encode() if data is not None else None, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.decode().strip()


def build_worker_image(root, image, run_id):
    sql_file = root / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql"
    role_sql = root / "deploy/sql/migrations/v2.9.0_009_account_user_roles.sql"
    context = io.BytesIO()
    with tarfile.open(fileobj=context, mode="w") as archive:
        content = ("FROM nexent/nexent:latest\nLABEL codex.test=" + run_id + "\n"
                   "COPY migrate_docker.py /opt/deploy/sql/tools/supabase_to_postgres/migrate_docker.py\n"
                   "COPY inspect_accounts.sql /opt/deploy/sql/tools/supabase_to_postgres/inspect_accounts.sql\n"
                   "COPY account.sql /opt/deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql\n"
                   "COPY account_roles.sql /opt/deploy/sql/migrations/v2.9.0_009_account_user_roles.sql\n"
                   'ENTRYPOINT ["sh","-c","exit 88"]\n').encode()
        info = tarfile.TarInfo("Dockerfile"); info.size = len(content); archive.addfile(info, io.BytesIO(content))
        for source, destination in [(root / "deploy/sql/tools/supabase_to_postgres/migrate_docker.py", "migrate_docker.py"), (sql_file, "account.sql"), (role_sql, "account_roles.sql"), (root / "deploy/sql/tools/supabase_to_postgres/inspect_accounts.sql", "inspect_accounts.sql")]:
            archive.add(source, arcname=destination)
    built = subprocess.run(["docker", "build", "-t", image, "-"], input=context.getvalue(), capture_output=True)
    assert built.returncode == 0, built.stderr

def assert_automatic_upgrade(root, temporary):
    # Exercise peer names containing "db" without treating Auth or Kong as the database.
    run_id = "db" + uuid4().hex
    names = {key: "supabase-auto-" + key + "-" + run_id for key in ["db", "auth", "kong"]}
    target = "auth-auto-target-" + run_id
    worker = "auth-auto-config-" + run_id
    network = "auth-auto-network-" + run_id
    image = "nexent-account-worker-test:" + run_id
    source_network = network + "-source"
    recovery_project = "auth-auto-recovery-" + run_id
    recovery_volume = recovery_project + "_db-config"
    recovery_network = recovery_project + "-network"
    old_root = temporary / "original storage"
    source_data = old_root / "volumes/db/data"
    source_data.mkdir(parents=True)
    label = "codex.test=" + run_id
    password = "IsolatedAutoTest123"
    user_id = str(uuid4())
    encoded = bcrypt.hashpw(b"original-password", bcrypt.gensalt(rounds=4)).decode()
    sql_file = root / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql"
    role_sql = root / "deploy/sql/migrations/v2.9.0_009_account_user_roles.sql"
    env = {**os.environ, "SUPABASE_MIGRATION_DB_CONTAINER": names["db"],
           "SUPABASE_MIGRATION_AUTH_CONTAINER": names["auth"], "SUPABASE_MIGRATION_KONG_CONTAINER": names["kong"],
           "SUPABASE_POSTGRES_USER": "postgres", "SUPABASE_POSTGRES_DB": "postgres",
           "POSTGRES_USER": "postgres", "POSTGRES_DB": "postgres", "NEXENT_POSTGRES_PASSWORD": password, "APP_VERSION": "2.9.0", "NEXENT_IMAGE": image, "DEPLOYMENT_IMAGE_SOURCE": "local-latest"}
    # Automatic mode must recover the source password from the original container.
    for key in ("SUPABASE_POSTGRES_PASSWORD", "SUPABASE_POSTGRES_HOST", "SUPABASE_DATA_DIR", "SUPABASE_DB"):
        env.pop(key, None)
    env.update(ROOT_DIR=old_root.as_posix(), SUPABASE_MIGRATION_PROJECT=recovery_project,
               SUPABASE_MIGRATION_NETWORK=recovery_network, SUPABASE_DB_CONFIG_VOLUME=recovery_volume,
               SUPABASE_PUBLISHED_PORT="0")
    env_file = temporary / ".env"
    env_file.write_text("")
    no_python = temporary / "no-host-python"
    no_python.mkdir()
    for executable in ("python", "python3"):
        path = no_python / executable
        path.write_text('#!/usr/bin/env bash\nprintf "host Python was invoked" >&2\nexit 97\n', encoding="utf-8")
        path.chmod(0o755)
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "bash"

    def phase(name, success=True):
        shell = 'source "$1/deploy/common/common.sh"; export DEPLOYMENT_ROOT_ENV="$2"; deployment_upgrade_local_accounts docker nexent "$4" "$5"'
        shell = 'export PATH="$(cygpath -u "$6" 2>/dev/null || printf "%s" "$6"):$PATH"; ' + shell
        result = subprocess.run([bash, "-c", shell, "case", root.as_posix(), env_file.as_posix(), name, target, worker, no_python.as_posix()],
                                env=env, capture_output=True, text=True, check=False)
        assert result.returncode == (0 if success else 1), result.stdout + result.stderr
        assert encoded not in result.stdout + result.stderr
        if not success:
            return result
        output = (result.stdout.strip().splitlines() or [""])[-1]
        return json.loads(output) if output.startswith("{") else {"skipped": True}

    def query(sql):
        return docker("exec", "-i", target, "psql", "-U", "postgres", "-qAt", "-v", "ON_ERROR_STOP=1", data=sql)

    build_worker_image(root, image, run_id)
    docker("network", "create", "--label", label, network)
    docker("network", "create", "--label", label, source_network)
    try:
        for name in [target, names["db"]]:
            storage = ["-v", f"{source_data.as_posix()}:/var/lib/postgresql/data",
                       "-e", "POSTGRES_INITDB_ARGS=--locale=C"] if name == names["db"] else []
            docker("run", "-d", "--name", name, "--label", label, "--network", source_network if name == names["db"] else network,
                   "-e", "POSTGRES_PASSWORD=" + password, *storage, "postgres:15-alpine")
        for name in [names["auth"], names["kong"]]:
            docker("run", "-d", "--name", name, "--label", label,
                   "--entrypoint", "sh", "postgres:15-alpine", "-c", "sleep 600")
        docker("run", "-d", "--name", worker, "--label", label, "--network", network,
               "-e", "POSTGRES_HOST=" + target, "-e", "POSTGRES_USER=postgres", "-e", "POSTGRES_DB=postgres",
               "-e", "POSTGRES_PORT=5432", "-e", "NEXENT_POSTGRES_PASSWORD=" + password,
               "--entrypoint", "sh", "nexent/nexent:latest", "-c", "sleep 600")
        for name in [target, names["db"]]:
            deadline = time.monotonic() + 30
            while subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], capture_output=True, check=False).returncode:
                assert time.monotonic() < deadline
                time.sleep(0.2)
        docker("exec", "-i", names["db"], "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
               data="CREATE SCHEMA auth; CREATE TABLE auth.users (id uuid,email text,encrypted_password text);"
                    f"INSERT INTO auth.users VALUES ('{user_id}','auto@example.com','{encoded}');")
        # Infrastructure executes only this baseline, before Python inspects the
        # target. It must not create the account completion marker prematurely.
        # Production POSTGRES_USER creates this baseline owner at initialization;
        # the disposable fixture uses postgres instead and must provide it here.
        query("CREATE ROLE root")
        query((root / "deploy/sql/init.sql").read_text(encoding="utf-8"))
        assert query("SELECT to_regclass('nexent.user_account_t') IS NULL") == "t"
        assert phase("prepare")["new"]
        query("CREATE SCHEMA IF NOT EXISTS nexent; CREATE TABLE nexent.user_tenant_t (user_id varchar(100),tenant_id varchar(100),"
              "user_role varchar(30),user_email varchar(255),delete_flag varchar(1) DEFAULT 'N');"
              f"INSERT INTO nexent.user_tenant_t VALUES ('{user_id}','retained-tenant','SU','auto@example.com','N');")
        query("INSERT INTO nexent.user_tenant_t VALUES ('user_id','tenant_id','SPEED',NULL,'N');")
        query("CREATE TABLE nexent.user_token_info_t (user_id varchar(100),delete_flag varchar(1)); "
              "INSERT INTO nexent.user_tenant_t VALUES ('api-only','api-tenant','USER',NULL,'N'); "
              "INSERT INTO nexent.user_token_info_t VALUES ('api-only','Y')")
        docker("stop", names["db"])
        # A conflict fails after schema creation, rolling back both the new
        # table and the removal of legacy profile fields. Retry starts fresh.
        query(f"UPDATE nexent.user_tenant_t SET user_email='conflict@example.com' WHERE user_id='{user_id}'")
        rejected = phase("prepare", success=False)
        assert user_id in rejected.stderr
        assert query("SELECT to_regclass('nexent.user_account_t') IS NULL") == "t"
        assert query(f"SELECT user_role,user_email FROM nexent.user_tenant_t WHERE user_id='{user_id}'") == "SU|conflict@example.com"
        assert all(name in docker("ps", "-a", "--format", "{{.Names}}").splitlines() for name in names.values())
        assert not (temporary / ".migration-state").exists()
        docker("stop", names["db"])
        docker("rm", names["db"])
        empty_dir = temporary / "empty-source"
        empty_dir.mkdir()
        env.update(SUPABASE_DATA_DIR=empty_dir.as_posix(), SUPABASE_POSTGRES_PASSWORD=password)
        rejected = phase("prepare", success=False)
        assert "refusing empty source initialization" in rejected.stderr, rejected.stdout + rejected.stderr
        assert not list(empty_dir.iterdir())
        assert names["db"] not in docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        del env["SUPABASE_DATA_DIR"]
        rejected = phase("prepare", success=False)
        assert user_id in rejected.stderr and "checking original PostgreSQL data" in rejected.stderr, rejected.stdout + rejected.stderr
        assert docker("inspect", "--format", '{{index .Config.Labels "com.docker.compose.project"}}', names["db"]) == recovery_project
        assert query("SELECT to_regclass('nexent.user_account_t') IS NULL") == "t"
        query(f"UPDATE nexent.user_tenant_t SET user_email='auto@example.com' WHERE user_id='{user_id}'")
        assert phase("prepare")["updated"] == 1
        assert (source_data / "PG_VERSION").is_file()
        assert (source_data / "global/pg_control").is_file()
        assert query("SELECT source_metadata->>'system_identity' FROM nexent.user_account_t WHERE user_id='user_id'") == "speed"
        docker("exec", worker, "mkdir", "-p", "/tmp/auth-migrations")
        for file in [sql_file, role_sql]:
            docker("cp", str(file), worker + ":/tmp/auth-migrations/" + file.name)
        runner = (root / "deploy/common/run-sql-migrations.sh").read_text(encoding="utf-8")
        docker("exec", "-i", worker, "sh", "-c", "cat > /tmp/run-auth-sql.sh", data=runner)
        docker("exec", "-i", worker, "sh", "-c", "cat > /tmp/init-auth.sql", data="CREATE SCHEMA IF NOT EXISTS nexent;\n")
        sql_command = ["exec", "-e", "NEXENT_APP_VERSION=2.9.0", "-e", "NEXENT_SQL_MIGRATION_DIR=/tmp/auth-migrations", "-e", "NEXENT_SQL_INIT_FILE=/tmp/init-auth.sql",
                       worker, "bash", "/tmp/run-auth-sql.sh", "--migrate"]
        docker(*sql_command)
        assert query("SELECT count(*) FROM nexent.schema_migrations WHERE migration_id='v2.9.0_001_local_user_accounts.sql'") == "1"
        # Old 002 execution records are retained even though the file is consolidated.
        query("INSERT INTO nexent.schema_migrations (migration_id,checksum,status,app_version,source_file) VALUES ('v2.9.0_002_account_availability.sql','legacy','applied','2.9.0','legacy-002')")
        # Normal startup must also support unchanged checksums and forced replay.
        docker(*sql_command)
        query("UPDATE nexent.schema_migrations SET checksum='force-replay' WHERE migration_id='v2.9.0_001_local_user_accounts.sql'")
        docker(*sql_command)
        assert query("SELECT count(*) FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='account_status'") == "0"
        assert query("SELECT checksum FROM nexent.schema_migrations WHERE migration_id='v2.9.0_002_account_availability.sql'") == "legacy"
        # A failed historical replay must roll back its schema/data changes,
        # preserving the already committed accounts instead of deleting them.
        query("ALTER TABLE nexent.user_tenant_t ADD COLUMN user_email varchar(255); "
              f"UPDATE nexent.user_tenant_t SET user_email='conflict@example.com' WHERE user_id='{user_id}'; "
              "UPDATE nexent.schema_migrations SET checksum='force-failure' WHERE migration_id='v2.9.0_001_local_user_accounts.sql'")
        failed = subprocess.run(["docker", *sql_command], capture_output=True, check=False)
        assert failed.returncode != 0
        assert query("SELECT count(*) FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='account_status'") == "0"
        assert query(f"SELECT password_hash FROM nexent.user_account_t WHERE user_id='{user_id}'") == encoded
        query("ALTER TABLE nexent.user_tenant_t DROP COLUMN user_email")
        docker(*sql_command)
        assert all(name not in docker("ps", "-a", "--format", "{{.Names}}").splitlines() for name in names.values())
        stored = query(f"SELECT password_hash FROM nexent.user_account_t WHERE user_id='{user_id}'")
        assert stored == encoded and bcrypt.checkpw(b"original-password", stored.encode())
        assert query(f"SELECT tenant_id FROM nexent.user_tenant_t WHERE user_id='{user_id}'") == "retained-tenant"
        assert query("SELECT delete_flag FROM nexent.user_account_t WHERE user_id='api-only'") == 'N'
        assert query("SELECT delete_flag FROM nexent.user_token_info_t WHERE user_id='api-only'") == 'Y'
        # An emptied account table cannot skip migration. Missing source must
        # stop rollout even when version history has been removed.
        query("DELETE FROM nexent.user_account_t; DROP TABLE nexent.schema_migrations")
        env["APP_VERSION"] = "unreadable"
        rejected = phase("prepare", success=False)
        assert 'incomplete' in rejected.stderr.lower() and user_id in rejected.stderr
        assert not (temporary / ".migration-state").exists()

    finally:
        existing = docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        for name in [*names.values(), target, worker]:
            if name in existing:
                labels = json.loads(docker("inspect", "--format", "{{json .Config.Labels}}", name))
                if labels.get("codex.test") == run_id or labels.get("com.docker.compose.project") == recovery_project:
                    docker("rm", "-f", name)
        if docker("image", "inspect", "--format", '{{index .Config.Labels "codex.test"}}', image) == run_id:
            docker("image", "rm", image)
        for owned_network in (network, source_network):
            if docker("network", "inspect", "--format", '{{index .Labels "codex.test"}}', owned_network) == run_id:
                docker("network", "rm", owned_network)
        for kind, resource in (("network", recovery_network), ("volume", recovery_volume)):
            resources = docker(kind, "ls", "--filter", f"label=com.docker.compose.project={recovery_project}", "--format", "{{.Name}}")
            if resource in resources.splitlines():
                docker(kind, "rm", resource)
