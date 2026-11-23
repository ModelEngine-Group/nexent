# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the Ops page identifier upgrade against owned PostgreSQL data."""

import os

import psycopg2
from psycopg2.extensions import parse_dsn
import pytest
from sqlalchemy import create_engine, select, text

from local_auth import ROOT, disposable_database
from management.db.models import RolePermission
from management.services.permission.identity.authentication import format_role_permissions

pytestmark = [pytest.mark.case_id("AUTH-MULTI-ROLE-D5-002"), pytest.mark.stage("D5")]


def test_ops_page_upgrade_preserves_grants_and_is_repeatable():
    migrations = list((ROOT / "deploy/sql/migrations").glob("*_ops_page_identifiers.sql"))
    assert len(migrations) == 1, "Expected one additive Ops page identifier migration"
    migration = migrations[0].read_text(encoding="utf-8")
    table = RolePermission.__table__
    replacements = {
        "/ops/dashboard": "ops-dashboard",
        "/ops/configuration": "ops-configuration",
    }

    with disposable_database() as dsn:
        engine = create_engine("postgresql+psycopg2://", creator=lambda: psycopg2.connect(dsn))
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE SCHEMA nexent"))
                table.create(connection)
                grants = [
                    (role, "VISIBILITY", "LEFT_NAV_MENU", path)
                    for role in ("OPS", "SU", "DEV")
                    for path in replacements
                ] + [
                    ("OPS", "VISIBILITY", "LEFT_NAV_MENU", "ops-dashboard"),
                    ("OPS", "VISIBILITY", "LEFT_NAV_MENU", "/resource-manage"),
                    ("OPS", "RESOURCE", "OPS.DASHBOARD", "READ"),
                    ("OPS", "RESOURCE", "LEFT_NAV_MENU", "/ops/dashboard"),
                    ("OPS", "VISIBILITY", "OTHER", "/ops/configuration"),
                ]
                for role, category, kind, subtype in grants:
                    connection.execute(table.insert().values(
                        user_role=role, permission_category=category,
                        permission_type=kind, permission_subtype=subtype,
                    ))

            def snapshot(connection):
                return [dict(row) for row in connection.execute(
                    select(table).order_by(table.c.role_permission_id)
                ).mappings()]

            def effective_grants(rows):
                return {
                    role: format_role_permissions([
                        row for row in rows if row["user_role"] == role
                    ])
                    for role in ("OPS", "SU", "DEV")
                }

            with engine.begin() as connection:
                before = snapshot(connection)
                assert connection.exec_driver_sql(migration).rowcount == 6
                after = snapshot(connection)
                assert len(after) == len(before)
                for original, updated in zip(before, after, strict=True):
                    matching = (
                        original["permission_category"] == "VISIBILITY"
                        and original["permission_type"] == "LEFT_NAV_MENU"
                        and original["permission_subtype"] in replacements
                    )
                    if matching:
                        assert updated["permission_subtype"] == replacements[original["permission_subtype"]]
                        unchanged = set(original) - {"permission_subtype"}
                        assert {key: updated[key] for key in unchanged} == {
                            key: original[key] for key in unchanged
                        }
                    else:
                        assert updated == original
                assert effective_grants(after) == effective_grants(before)
                assert effective_grants(after)["OPS"]["accessibleRoutes"] == [
                    "/ops/dashboard", "/ops/configuration", "/resource-manage"
                ]
            # A separate transaction verifies repeatability across deployment attempts.
            with engine.begin() as connection:
                assert connection.exec_driver_sql(migration).rowcount == 0
                assert snapshot(connection) == after
        finally:
            engine.dispose()

    # The factory must remove its UUID database after all pooled connections close.
    with psycopg2.connect(os.environ["NEXENT_AUTH_TEST_DSN"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_database WHERE datname = %s", (parse_dsn(dsn)["dbname"],))
            assert cursor.fetchone()[0] == 0
