# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run the deployment entry point twice against a disposable Ops database."""

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import psycopg2
from psycopg2 import sql


pytestmark = [pytest.mark.case_id("OPS-MODEL-MONITORING-D5-001"), pytest.mark.stage("D5")]


def test_ops_database_migration():
    host = os.environ.get("OPS_MONITORING_TEST_POSTGRES_HOST")
    if not host or os.environ.get("OPS_MONITORING_TEST_ISOLATED") != "1":
        pytest.skip("An isolated Ops monitoring PostgreSQL service is required")
    project = Path(__file__).resolve().parents[3]
    db, business = f"ops_{uuid4().hex}", f"nexent_{uuid4().hex}"
    connection = psycopg2.connect(host=host, dbname="postgres", user="postgres")
    connection.autocommit = True
    try:
        for database in (db, business):
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        env = {
            **os.environ, "OPS_POSTGRES_HOST": host, "OPS_POSTGRES_USER": "postgres",
            "OPS_POSTGRES_DB": db, "POSTGRES_DB": business,
            "NEXENT_SQL_WAIT_TIMEOUT_SECONDS": "15",
        }
        for _ in range(2):
            subprocess.run(["bash", str(project / "deploy/common/run-ops-sql-migrations.sh")],
                           env=env, check=True, capture_output=True, timeout=30)
            for database, expected in ((db, 2), (business, 0)):
                target = psycopg2.connect(host=host, dbname=database, user="postgres")
                try:
                    with target.cursor() as cursor:
                        cursor.execute("SELECT count(*) FROM information_schema.tables WHERE "
                                       "table_schema='ops' AND table_name LIKE 'ops_monitoring_%'")
                        assert cursor.fetchone() == (expected,)
                finally:
                    target.close()
    finally:
        for database in (db, business):
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
        connection.close()
