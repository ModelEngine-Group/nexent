# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prove automatic independent Ops initialization through the deployment launcher."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

pytestmark = [pytest.mark.case_id("OPS-MODEL-MONITORING-D5-001"), pytest.mark.stage("D5")]


def test_ops_database_migration(tmp_path):
    host = os.environ.get("OPS_MONITORING_TEST_POSTGRES_HOST")
    if not host or os.environ.get("OPS_MONITORING_TEST_ISOLATED") != "1":
        pytest.skip("An isolated PostgreSQL server is required")
    root = Path(__file__).resolve().parents[3]
    business = f"nexent_{uuid4().hex}"
    default_db = business + "_ops"
    databases, roles, processes = {business, default_db}, [], []
    admin = psycopg2.connect(host=host, dbname="postgres", user="postgres")
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(business)))
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("OPS_POSTGRES_", "POSTGRES_", "NEXENT_SQL_"))
           and key not in {"OPS_MONITORING_ENABLED", "NEXENT_POSTGRES_PASSWORD"}}
    env.update(POSTGRES_HOST=host, POSTGRES_PORT="5432", POSTGRES_USER="postgres", POSTGRES_DB=business,
               NEXENT_POSTGRES_PASSWORD="", NEXENT_SQL_STARTUP_MODE="off", NEXENT_SQL_WAIT_TIMEOUT_SECONDS="15")

    def start(**overrides):
        process = subprocess.Popen(
            ["bash", str(root / "deploy/common/start-ops.sh"), sys.executable, "-c", "print('OPS_READY')"],
            env={**env, **overrides}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(process)
        return process

    def finish(process, success=True):
        stdout, stderr = process.communicate(timeout=25)
        assert (process.returncode == 0) is success, stdout + stderr
        assert ("OPS_READY" in stdout) is success, stdout + stderr

    def exists(database):
        with admin.cursor() as cursor:
            cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)", (database,))
            return cursor.fetchone()[0]

    def query(database, statement):
        target = psycopg2.connect(host=host, dbname=database, user="postgres")
        try:
            with target, target.cursor() as cursor:
                cursor.execute(statement)
                return cursor.fetchall() if cursor.description else None
        finally:
            target.close()

    def control_tables(database):
        return query(database, "SELECT count(*) FROM information_schema.tables WHERE "
                     "table_schema='ops' AND table_name LIKE 'ops_monitoring_%'")[0][0]

    try:
        assert not exists(default_db)
        finish(start())
        assert control_tables(default_db) == 2 and control_tables(business) == 0
        query(default_db, "CREATE TABLE ops.deployment_probe(value integer); INSERT INTO ops.deployment_probe VALUES (42)")
        finish(start())
        assert control_tables(default_db) == 2 and query(default_db, "SELECT value FROM ops.deployment_probe") == [(42,)]

        concurrent_db = 'ops_quote_"' + uuid4().hex
        databases.add(concurrent_db)
        first, second = start(OPS_POSTGRES_DB=concurrent_db), start(OPS_POSTGRES_DB=concurrent_db)
        finish(first)
        finish(second)
        assert control_tables(concurrent_db) == 2 and control_tables(business) == 0

        waiting_db = "ops_wait_" + uuid4().hex
        databases.add(waiting_db)
        consumer = subprocess.Popen(
            ["bash", str(root / "deploy/common/run-ops-sql-migrations.sh"), "--wait"],
            env={**env, "OPS_POSTGRES_DB": waiting_db},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(consumer)
        time.sleep(0.5)
        assert consumer.poll() is None and not exists(waiting_db)
        finish(start(OPS_POSTGRES_DB=waiting_db))
        stdout, stderr = consumer.communicate(timeout=25)
        assert consumer.returncode == 0, stdout + stderr
        assert control_tables(waiting_db) == 2

        disabled_db = "ops_disabled_" + uuid4().hex
        databases.add(disabled_db)
        finish(start(OPS_MONITORING_ENABLED="false", OPS_POSTGRES_DB=disabled_db))
        assert not exists(disabled_db)

        # DataProcess does not package Ops SQL helpers, even when monitoring is globally enabled.
        unrelated_db = "ops_unrelated_" + uuid4().hex
        databases.add(unrelated_db)
        launcher = tmp_path / "data-process"
        launcher.mkdir()
        shutil.copy(root / "deploy/common/start-backend.sh", launcher / "start-backend.sh")
        unrelated = subprocess.Popen(
            ["bash", str(launcher / "start-backend.sh"), sys.executable, "-c",
             "import os; assert os.environ['OPS_MONITORING_ENABLED'] == 'true'; print('OPS_READY')"],
            env={**env, "OPS_MONITORING_ENABLED": "true", "OPS_POSTGRES_DB": unrelated_db},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        processes.append(unrelated)
        finish(unrelated)
        assert not exists(unrelated_db)
        assert not (launcher / "run-ops-sql-migrations.sh").exists()

        finish(start(OPS_POSTGRES_DB=business), success=False)
        finish(start(OPS_POSTGRES_DB="o" * 64), success=False)
        assert control_tables(business) == 0
        role = "ops_limited_" + uuid4().hex[:20]
        roles.append(role)
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOCREATEDB").format(sql.Identifier(role)))
        denied_db = "ops_denied_" + uuid4().hex
        databases.add(denied_db)
        finish(start(POSTGRES_USER=role, OPS_POSTGRES_DB=denied_db), success=False)
        assert not exists(denied_db)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
        for database in databases:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
        for role in roles:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        admin.close()
