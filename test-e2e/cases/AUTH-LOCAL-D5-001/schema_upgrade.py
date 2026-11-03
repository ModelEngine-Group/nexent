# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Consolidated SQL proves provider/password identities and final-state uniqueness."""

from uuid import uuid4

import bcrypt
import psycopg2
import pytest

from local_auth import disposable_database
from deploy.sql.tools.supabase_to_postgres.migrate_docker import MigrationConflict, import_users


def assert_consolidated_schema(root):
    sql = (root / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql").read_text(encoding="utf-8")
    assert not (root / "deploy/sql/migrations/v2.9.0_002_account_availability.sql").exists()
    assert "ADD COLUMN account_status" not in sql and "account_status VARCHAR" not in sql
    dual_id, banned_id = str(uuid4()), str(uuid4())
    encoded = bcrypt.hashpw(b"OriginalPassword123", bcrypt.gensalt(rounds=4)).decode()
    for conflict in (False, True):
        with disposable_database() as dsn:
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA nexent; CREATE TABLE nexent.user_tenant_t (user_id varchar(100),tenant_id varchar(100),user_role varchar(30),user_email varchar(255),delete_flag varchar(1)); CREATE TABLE nexent.user_oauth_account_t (user_id varchar(100),provider varchar(30),delete_flag varchar(1))")
                members = [
                    ("cas-only", "USER", "cas@example.com", "N"),
                    ("oauth-only", "DEV", "oauth@example.com", "N"),
                    (dual_id, "ADMIN", "dual@example.com", "N"),
                    (banned_id, "USER", "cas@example.com", "N"),
                    ("deleted-binding", "USER", "gone@example.com", "N"),
                    ("deleted-member", "USER", "old@example.com", "Y"),
                ]
                if conflict:
                    members.append(("duplicate-cas", "USER", "cas@example.com", "N"))
                cursor.executemany("INSERT INTO nexent.user_tenant_t VALUES (%s,'tenant',%s,%s,%s)", members)
                bindings = [(uid, "cas" if uid.startswith("cas") else "github", "Y" if uid == "deleted-binding" else "N") for uid, _, _, _ in members]
                cursor.executemany("INSERT INTO nexent.user_oauth_account_t VALUES (%s,%s,%s)", bindings)
            rows = [
                {"id": dual_id, "email": "dual@example.com", "encrypted_password": encoded, "raw_user_meta_data": {"provider": "cas"}},
                {"id": banned_id, "email": "cas@example.com", "banned_until": "2999-01-01T00:00:00Z"},
            ]
            if conflict:
                with pytest.raises(MigrationConflict) as error, psycopg2.connect(dsn) as connection:
                    import_users(connection, rows, dry_run=False)
                assert "cas-only" in str(error.value) and "duplicate-cas" in str(error.value)
                with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                    cursor.execute("SELECT to_regclass('nexent.user_account_t')")
                    assert cursor.fetchone()[0] is None
                    cursor.execute("SELECT count(*) FROM nexent.user_tenant_t WHERE user_role IS NOT NULL")
                    assert cursor.fetchone()[0] == len(members)
                continue
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                import_users(connection, rows, dry_run=False)
                cursor.execute("SELECT user_id,user_role,password_login_enabled,password_hash,delete_flag FROM nexent.user_account_t ORDER BY user_id")
                accounts = {r[0]: r[1:] for r in cursor.fetchall()}
                assert accounts == {
                    "cas-only": ("USER", False, None, "N"),
                    "oauth-only": ("DEV", False, None, "N"),
                    dual_id: ("ADMIN", True, encoded, "N"),
                }
                cursor.execute("SELECT count(*) FROM nexent.user_oauth_account_t")
                assert cursor.fetchone()[0] == len(bindings)
                cursor.execute("UPDATE nexent.user_account_t SET delete_flag='Y',token_version=8,updated_by='operator' WHERE user_id='cas-only'")
                cursor.execute(sql)
                cursor.execute(sql)
                cursor.execute("SELECT delete_flag,token_version,updated_by FROM nexent.user_account_t WHERE user_id='cas-only'")
                assert cursor.fetchone() == ("Y", 8, "operator")
                cursor.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t' AND column_name='account_status'")
                assert cursor.fetchone()[0] == 0
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('pg_temp.account_migration_profiles')")
                assert cursor.fetchone()[0] is None


def assert_legacy_account_columns(root):
    sql = (root / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql").read_text(encoding="utf-8")
    ddl = sql[sql.index("CREATE TABLE IF NOT EXISTS"):].split(");", 1)[0] + ");"
    ddl = ddl.replace("user_email VARCHAR(255)", "email VARCHAR(255),account_status VARCHAR(30) DEFAULT 'active'")
    with disposable_database() as dsn:
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA nexent")
            cursor.execute(ddl)
            cursor.execute("CREATE TABLE nexent.user_tenant_t (user_id varchar(100),tenant_id varchar(100),user_role varchar(30),user_email varchar(255),delete_flag varchar(1)); INSERT INTO nexent.user_tenant_t VALUES ('legacy','tenant','DEV','legacy@example.com','N')")
            cursor.execute("INSERT INTO nexent.user_account_t (user_id,email,password_hash,token_version,updated_by) VALUES ('legacy','legacy@example.com','retained-opaque-hash',7,'operator')")
            cursor.execute("INSERT INTO nexent.user_account_t (user_id,email,account_status,delete_flag,source_metadata) VALUES ('disabled','disabled@example.com','disabled','N','{\"credential_migration_pending\":true}'),('deleted','deleted@example.com','active','Y','{}')")
            cursor.execute(sql)
            cursor.execute(sql)
            cursor.execute("SELECT user_role,user_email,password_hash,token_version,delete_flag FROM nexent.user_account_t WHERE user_id='legacy'")
            assert cursor.fetchone() == ('DEV','legacy@example.com','retained-opaque-hash',7,'N')
            cursor.execute("SELECT user_id,delete_flag,source_metadata FROM nexent.user_account_t WHERE user_id<>'legacy' ORDER BY user_id")
            assert cursor.fetchall() == [('deleted','Y',{}),('disabled','Y',{})]
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t'")
            columns = {r[0] for r in cursor.fetchall()}
            assert 'user_email' in columns and not {'email','account_status'} & columns
            cursor.execute("ALTER TABLE nexent.user_account_t ADD COLUMN email varchar(255); UPDATE nexent.user_account_t SET email='conflict@example.com' WHERE user_id='legacy'")
        with pytest.raises(psycopg2.Error, match='legacy'), psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(sql)
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT user_email,email,password_hash FROM nexent.user_account_t WHERE user_id='legacy'")
            assert cursor.fetchone() == ('legacy@example.com','conflict@example.com','retained-opaque-hash')
