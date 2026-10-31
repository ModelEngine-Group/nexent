# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared isolated PostgreSQL/FastAPI fixtures for native authentication contracts."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from psycopg2.extensions import parse_dsn
from sqlalchemy import text

from local_auth import disposable_database


@pytest.fixture(scope="module")
def native_runtime():
    with disposable_database() as dsn, pytest.MonkeyPatch.context() as patch:
        params = parse_dsn(dsn)
        for name, value in {
            "POSTGRES_HOST": params["host"],
            "POSTGRES_PORT": params["port"],
            "POSTGRES_USER": params["user"],
            "POSTGRES_DB": params["dbname"],
            "NEXENT_POSTGRES_PASSWORD": params["password"],
            "JWT_SECRET": "native-auth-test-signing-key-at-least-32-bytes",
            "JWT_ISSUER": "nexent-native-test",
            "DEPLOYMENT_VERSION": "full",
        }.items():
            patch.setenv(name, value)
        from management.db import models
        from management.db.client import db_client
        from management.services.permission.identity import authentication as auth
        from gateway.authentication import auth as helpers
        from management.api.identity import user_management as routes
        from contracts.errors.exceptions import AppException

        tables = [
            models.UserAccount,
            models.UserTenant,
            models.UserOAuthAccount,
            models.UserCasSession,
            models.UserTokenInfo,
            models.UserTokenUsageLog,
            models.RolePermission,
            models.TenantGroupUser,
            models.TenantGroupInfo,
            models.TenantInvitationCode,
            models.TenantInvitationRecord,
        ]
        with db_client.engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA nexent"))
        models.TableBase.metadata.create_all(
            db_client.engine, tables=[model.__table__ for model in tables]
        )
        patch.setattr(auth, "init_tool_list_for_tenant", AsyncMock())
        patch.setattr(auth, "init_skill_list_for_tenant", AsyncMock())
        patch.setattr(routes, "record_security_event", lambda *a, **kw: None)
        app = FastAPI()
        app.include_router(routes.router, prefix="/api")

        @app.exception_handler(AppException)
        async def domain_error(request, exc):
            return JSONResponse(
                status_code=400, content={"detail": "Password validation failed"}
            )

        with TestClient(app) as client:
            yield client, auth, helpers, models
        db_client.engine.dispose()


@pytest.fixture
def runtime(native_runtime):
    client, auth, helpers, models = native_runtime
    from management.db.client import get_db_session

    with get_db_session() as session:
        for model in [
            models.UserAccount,
            models.UserTenant,
            models.UserTokenInfo,
            models.TenantInvitationCode,
            models.TenantInvitationRecord,
            models.UserCasSession,
            models.UserOAuthAccount,
        ]:
            session.execute(model.__table__.delete())
        session.add(
            models.TenantInvitationCode(
                tenant_id="tenant-native",
                invitation_code="NATIVE-INVITE",
                group_ids="[]",
                capacity=20,
                expiry_date=datetime.utcnow() + timedelta(days=1),
                status="IN_USE",
                code_type="USER_INVITE",
                created_by="test",
                updated_by="test",
                delete_flag="N",
            )
        )
    return native_runtime


def register(client):
    response = client.post(
        "/api/user/signup",
        json={
            "email": "native@example.com",
            "password": "Password123",
            "invite_code": "NATIVE-INVITE",
            "auto_login": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def bearer(token):
    return {"Authorization": "Bearer " + token}
