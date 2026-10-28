# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Disposable PostgreSQL databases for native-auth HTTP and migration proofs."""

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn, make_dsn

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "backend"), str(ROOT / "sdk")]


@contextmanager
def disposable_database():
    dsn = os.environ.get("NEXENT_AUTH_TEST_DSN")
    if not dsn:
        raise RuntimeError(
            "NEXENT_AUTH_TEST_DSN must identify an isolated PostgreSQL test instance"
        )
    name = "auth_test_" + uuid4().hex
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        params = parse_dsn(dsn)
        params["dbname"] = name
        yield make_dsn(**params)
    finally:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )
        admin.close()


def initialize_target(dsn):
    with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA nexent")
        cursor.execute(
            "CREATE TABLE nexent.user_tenant_t (user_id varchar(100), tenant_id varchar(100), user_role varchar(30), user_email varchar(255), delete_flag varchar(1) DEFAULT 'N')"
        )
        cursor.execute(
            (
                ROOT / "deploy/sql/migrations/v2.8.1_001_local_user_accounts.sql"
            ).read_text(encoding="utf-8")
        )
