# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Owned native identity/PG fixture; external catalog installation is controlled.

Every caller owns a UUID database through the existing local-auth factory.
The application uses current identity, group, tenant, model and operations routers.
Only unrelated tool/skill installation and audit transport are controlled boundaries.
"""

import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.extensions import parse_dsn
from sqlalchemy import text, select
from sqlalchemy.orm import sessionmaker
from local_auth import disposable_database, ROOT


@contextmanager
def isolated_runtime():
    with disposable_database() as dsn, pytest.MonkeyPatch.context() as patch:
        params = parse_dsn(dsn)
        for name, value in {
            "POSTGRES_HOST": params["host"],
            "POSTGRES_PORT": params.get("port", "5432"),
            "POSTGRES_USER": params["user"],
            "POSTGRES_DB": params["dbname"],
            "NEXENT_POSTGRES_PASSWORD": params["password"],
            "JWT_SECRET": "isolated-roles-test-signing-secret-at-least-32-bytes",
            "JWT_ISSUER": "nexent-roles-test",
            "DEPLOYMENT_VERSION": "full",
            "ENABLE_ASSET_OWNER_ROLE": "false",
        }.items():
            patch.setenv(name, value)
        from management.db import models
        from management.db.client import db_client
        from sqlalchemy import create_engine
        from sqlalchemy.engine import URL

        engine = create_engine(
            URL.create(
                "postgresql+psycopg2",
                username=params["user"],
                password=params["password"],
                host=params["host"],
                port=int(params.get("port", 5432)),
                database=params["dbname"],
            )
        )
        patch.setattr(db_client, "engine", engine)
        patch.setattr(db_client, "session_maker", sessionmaker(bind=engine))
        patch.setattr(db_client, "database", params["dbname"])
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
            models.TenantConfig,
            models.ModelRecord,
            models.McpRecord,
            models.AgentInfo,
            models.KnowledgeRecord,
        ]
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA nexent"))
            for model in tables:
                model.__table__.create(connection, checkfirst=True)
            # Seed only legacy grants exercised here. New OPS/SU operations grants come from the product upgrade.
            for role in ("ADMIN", "DEV", "USER", "SU"):
                routes = (
                    ["/resource-manage"]
                    if role == "ADMIN"
                    else ["/agents"]
                    if role == "DEV"
                    else ["/newchat"]
                    if role == "USER"
                    else ["/resource-manage", "/agents"]
                )
                for route in ["/", *routes]:
                    connection.execute(
                        models.RolePermission.__table__.insert().values(
                            user_role=role,
                            permission_category="VISIBILITY",
                            permission_type="LEFT_NAV_MENU",
                            permission_subtype=route,
                        )
                    )
                connection.execute(
                    models.RolePermission.__table__.insert().values(
                        user_role=role,
                        permission_category="RESOURCE",
                        permission_type="MODEL",
                        permission_subtype="READ",
                    )
                )
            # Fixture setup applies the current additive role upgrade, never modifies historical SQL.
            upgrades = sorted((ROOT / "deploy/sql/migrations").glob("*_ops_roles.sql"))
            if len(upgrades) != 1:
                raise RuntimeError("Expected the versioned operations-role migration")
            connection.connection.cursor().execute(upgrades[0].read_text(encoding="utf-8"))
        from management.services.permission.identity import authentication as auth
        from management.api.identity import user_management, user, invitation, group, tenant
        from management.api.configuration import tenant_config
        from management.api.model import model_managment
        from gateway.authentication import auth as helpers
        from ops.api import access
        from management.utils.app_factory import create_app

        patch.setattr(auth, "init_tool_list_for_tenant", AsyncMock())
        patch.setattr(auth, "init_skill_list_for_tenant", AsyncMock())
        for routes in (user_management, user, invitation):
            patch.setattr(routes, "record_security_event", lambda *args, **kwargs: None)
        app = create_app(enable_monitoring=False)
        for module in (user_management, user, invitation, group, tenant, tenant_config, model_managment, access):
            app.include_router(module.router if hasattr(module, "router") else module.model_manager_router)
        from permissions import rbac

        rbac.init_rbac()
        runtime = Runtime(app, engine, models, helpers)
        try:
            runtime.seed()
            with TestClient(app, raise_server_exceptions=False) as client:
                runtime.client = client
                yield runtime
        finally:
            engine.dispose()


class Runtime:
    def __init__(self, app, engine, models, helpers):
        self.app, self.engine, self.models, self.helpers = app, engine, models, helpers
        self.users = {}
        self.password = "OwnedPassword123"

    def seed(self):
        from management.db.client import get_db_session
        from management.db.identity.account import create_account
        from management.db.identity.user_tenant import insert_user_tenant
        from infrastructure.security.passwords import hash_password

        definitions = {
            "su": ("platform", ["SU"]),
            "admin1": ("a", ["ADMIN"]),
            "admin2": ("a", ["ADMIN"]),
            "user": ("a", ["USER"]),
            "dev": ("a", ["DEV"]),
            "ops": ("a", ["OPS"]),
            "foreign": ("b", ["ADMIN"]),
            "asset_owner": ("asset_owner_tenant_id", ["ASSET_OWNER"]),
        }
        with get_db_session() as session:
            for logical, (tenant, roles) in definitions.items():
                account = create_account(
                    logical + "@roles.example.com", hash_password(self.password), db_session=session
                )
                insert_user_tenant(
                    account["user_id"], tenant, roles[0], account["email"], db_session=session, roles=roles
                )
                self.users[logical] = account["user_id"]
            for tenant in ("a", "b"):
                group = self.models.TenantGroupInfo(
                    tenant_id=tenant, group_name="Owned group", created_by=self.users["su"], delete_flag="N"
                )
                session.add(group)
                session.flush()
                if tenant == "a":
                    self.group = group.group_id
                for key, value in (("TENANT_NAME", "Owned " + tenant), ("DEFAULT_GROUP_ID", str(group.group_id))):
                    session.add(
                        self.models.TenantConfig(tenant_id=tenant, config_key=key, config_value=value, delete_flag="N")
                    )
            session.add(
                self.models.ModelRecord(
                    tenant_id="a",
                    model_name="Owned model",
                    api_key="MUST-NOT-LEAK",
                    http_headers={"Authorization": "MUST-NOT-LEAK"},
                    delete_flag="N",
                )
            )
            session.add(self.models.ModelRecord(tenant_id="b", model_name="Foreign model", delete_flag="N"))
        self.tokens = {key: self.helpers.generate_session_jwt(uid) for key, uid in self.users.items()}

    def headers(self, actor):
        return {"Authorization": "Bearer " + self.tokens[actor]}

    def assign(self, target, values, actor="su"):
        return self.client.put(
            "/users/" + self.users.get(target, target), headers=self.headers(actor), json={"roles": values}
        )

    def info(self, actor):
        return self.client.get("/user/current_user_info", headers=self.headers(actor))

    def invite(self, roles, actor="admin1", capacity=1):
        return self.client.post(
            "/invitations",
            headers=self.headers(actor),
            json={
                "tenant_id": "a",
                "roles": roles,
                "invitation_code": uuid4().hex.upper(),
                "group_ids": [self.group],
                "capacity": capacity,
            },
        )

    def signup(self, code, email=None):
        return self.client.post(
            "/user/signup",
            json={
                "email": email or uuid4().hex + "@roles.example.com",
                "password": self.password,
                "invite_code": code,
            },
        )


@pytest.fixture
def role_runtime():
    with isolated_runtime() as runtime:
        yield runtime


if __name__ == "__main__":
    import uvicorn

    with isolated_runtime() as runtime:

        @runtime.app.get("/__fixture")
        def owned_fixture():
            return {
                "users": runtime.users,
                "password": runtime.password,
                "owned_database": runtime.engine.url.database,
                "emails": {key: key + "@roles.example.com" for key in runtime.users},
            }

        uvicorn.run(runtime.app, host="0.0.0.0", port=5010, log_level="warning")
