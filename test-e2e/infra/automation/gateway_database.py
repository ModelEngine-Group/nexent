# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Disposable database and SELECT-only identity login for Gateway integration."""

from contextlib import contextmanager
from datetime import datetime, timedelta
import secrets
import uuid

import psycopg2
from psycopg2 import sql
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import make_url


@contextmanager
def isolated_identity_database(admin_dsn):
    from management.db.base import TableBase
    from management.db.identity.models import UserAccount, UserTenant, UserTokenInfo, UserCasSession

    url = make_url(admin_dsn)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Gateway verification requires a disposable local PostgreSQL server")
    suffix = uuid.uuid4().hex
    database, role, password = "gw_test_" + suffix, "gw_reader_" + suffix, secrets.token_hex(24)
    admin = psycopg2.connect(admin_dsn)
    admin.autocommit = True
    engine = None
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)))
        engine = create_engine(url.set(drivername="postgresql+psycopg2", database=database))
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA nexent")
        TableBase.metadata.create_all(engine, tables=[model.__table__ for model in (UserAccount, UserTenant, UserTokenInfo, UserCasSession)])
        with engine.begin() as connection:
            for user, tenant, user_role in [("u1", "t1", "USER"), ("u2", "t2", "USER"),
                                            ("su", "", "SU"), ("owner", "", "ASSET_OWNER")]:
                connection.execute(insert(UserAccount).values(user_id=user, user_role=user_role,
                                   user_email=user + "@example.test", token_version=3, delete_flag="N"))
                connection.execute(insert(UserTenant).values(user_id=user, tenant_id=tenant, delete_flag="N"))
            connection.execute(insert(UserTokenInfo).values(user_id="u1", access_key="fixture-api-key", delete_flag="N"))
            # Existing services select the first membership; additional relations
            # must not silently change its tenant or make the account unusable.
            connection.execute(insert(UserTenant).values(user_id="u1", tenant_id="secondary", delete_flag="N"))
            for sid, user in [("active", "u1"), ("other-user", "u2")]:
                connection.execute(insert(UserCasSession).values(session_id=sid, user_id=user, cas_user_id=user,
                                   status="active", expires_at=datetime.now() + timedelta(hours=1), delete_flag="N"))
            quoted_role = engine.dialect.identifier_preparer.quote(role)
            connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA nexent TO {quoted_role}")
            columns = {"user_account_t": "user_id,user_email,user_role,token_version,delete_flag",
                       "user_tenant_t": "user_tenant_id,user_id,tenant_id,delete_flag",
                       "user_token_info_t": "user_id,token_id,access_key,delete_flag",
                       "user_cas_session_t": "session_id,user_id,status,expires_at,delete_flag"}
            for table, fields in columns.items():
                connection.exec_driver_sql(f"GRANT SELECT ({fields}) ON nexent.{table} TO {quoted_role}")
        yield dict(host=url.host, port=url.port or 5432, database=database, user=role, password=password,
                   engine=engine, admin=admin)
    finally:
        if engine is not None:
            engine.dispose()
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
            cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        admin.close()
