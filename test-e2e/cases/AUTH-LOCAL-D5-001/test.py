# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""D5: real PostgreSQL account import, transaction recovery and credential retention."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import bcrypt
import psycopg2
import pytest
from psycopg2.extras import Json
from psycopg2.extensions import parse_dsn

pytestmark = [pytest.mark.case_id("AUTH-LOCAL-D5-001"), pytest.mark.stage("D5")]

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test-e2e/infra/automation"))
from local_auth import disposable_database, initialize_target
from deploy.sql.tools.supabase_to_postgres.migrate import (
    MigrationConflict,
    import_users,
    read_source_users,
)
from infrastructure.security.passwords import verify_password


def test_deployment_automatic_upgrade_retries_after_sql_success(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("automatic_upgrade_proof", Path(__file__).with_name("automatic_upgrade.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.assert_automatic_upgrade(ROOT, tmp_path)


def test_legacy_api_only_keys_survive_upgrade_and_replay(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import sessionmaker
    from management.db.client import db_client
    from management.db import models
    from gateway.authentication import northbound_auth

    sql = (ROOT / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql").read_text(encoding="utf-8")
    with disposable_database() as dsn:
        params = parse_dsn(dsn)
        engine = create_engine(URL.create("postgresql+psycopg2", username=params["user"], password=params["password"], host=params["host"], port=int(params["port"]), database=params["dbname"]))
        try:
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA nexent")
                cursor.execute("CREATE TABLE nexent.user_tenant_t (user_id varchar(100), tenant_id varchar(100), user_role varchar(30), user_email varchar(255), delete_flag varchar(1) DEFAULT 'N')")
            models.UserTokenInfo.__table__.create(engine)
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                cursor.executemany("INSERT INTO nexent.user_tenant_t VALUES (%s,'tenant',%s,%s,%s)", [
                    ("api", "USER", None, "N"), ("revoked", "DEV", "", "N"),
                    ("normal", "USER", "normal@example.com", "N"), ("unknown", "USER", None, "N"),
                    ("deleted", "USER", None, "Y"), ("admin", "SU", None, "N"),
                ])
                for token_id, uid in enumerate(["api", "revoked", "normal", "deleted", "admin"], 1):
                    cursor.execute("INSERT INTO nexent.user_token_info_t (token_id,access_key,user_id,delete_flag) VALUES (%s,%s,%s,%s)",
                                   (token_id, "nexent-original-" + uid, uid, "Y" if uid == "revoked" else "N"))
                cursor.execute(sql)
                cursor.execute("SELECT user_id,account_status,password_login_enabled,password_hash,user_email,source_metadata,delete_flag FROM nexent.user_account_t")
                rows = {r[0]: r[1:] for r in cursor.fetchall()}
                assert rows["api"][:4] == rows["revoked"][:4] == ("active", False, None, None)
                assert rows["api"][4] == {"api_only": True}
                assert all(rows[uid][0] == "disabled" for uid in ["normal", "unknown", "deleted", "admin"])
                assert rows["deleted"][-1] == "Y"
                # Repair a placeholder produced by the previous draft migration.
                cursor.execute("UPDATE nexent.user_account_t SET account_status='disabled',source_metadata='{" + '"credential_migration_pending":true' + "}',updated_by='account-schema-migration' WHERE user_id='api'")
                cursor.execute(sql)
                cursor.execute("SELECT account_status FROM nexent.user_account_t WHERE user_id='api'")
                assert cursor.fetchone()[0] == "active"
                cursor.execute("UPDATE nexent.user_account_t SET account_status='disabled',source_metadata=%s,updated_by='operator' WHERE user_id='revoked'",
                               (Json({"credential_migration_pending": True}),))
                cursor.execute(sql)
                cursor.execute("SELECT account_status FROM nexent.user_account_t WHERE user_id='revoked'")
                assert cursor.fetchone()[0] == "disabled"
            with monkeypatch.context() as patch:
                patch.setattr(db_client, "session_maker", sessionmaker(bind=engine))
                assert northbound_auth.validate_bearer_token("nexent-original-api")[0]
                assert not northbound_auth.validate_bearer_token("nexent-original-revoked")[0]
                assert not northbound_auth.validate_bearer_token("nexent-original-deleted")[0]
                with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                    cursor.execute("UPDATE nexent.user_account_t SET account_status='disabled',updated_by='operator' WHERE user_id='api'")
                    cursor.execute(sql)
                assert not northbound_auth.validate_bearer_token("nexent-original-api")[0]
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT access_key,user_id FROM nexent.user_token_info_t ORDER BY user_id")
                assert cursor.fetchall() == [("nexent-original-" + uid, uid) for uid in sorted(["api", "revoked", "normal", "deleted", "admin"])]
        finally:
            engine.dispose()


def test_successful_apply_reclaims_source_stack_and_retains_data(target):
    import importlib.util

    spec = importlib.util.spec_from_file_location("auth_source_cleanup", Path(__file__).with_name("source_cleanup.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.assert_source_cleanup(ROOT, target)


@pytest.fixture
def target():
    with disposable_database() as dsn:
        initialize_target(dsn)
        yield dsn


def historical_user(**extra):
    return dict(
        id=str(uuid4()),
        email="historical@example.com",
        encrypted_password=bcrypt.hashpw(
            b"OriginalPassword123", bcrypt.gensalt(rounds=4)
        ).decode(),
        email_confirmed_at="2020-01-01T00:00:00Z",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-02T00:00:00Z",
        raw_app_meta_data={"role": "admin"},
        **extra,
    )


def member(dsn, row):
    with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO nexent.user_tenant_t (user_id,tenant_id) VALUES (%s,'tenant')",
            (row["id"],),
        )
        cursor.execute(
            "INSERT INTO nexent.user_account_t (user_id,user_email,user_role,account_status,source_metadata) "
            "VALUES (%s,%s,'USER','disabled',%s)",
            (row["id"],row["email"],Json({"credential_migration_pending":True})),
        )


def count(dsn):
    with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM nexent.user_account_t WHERE NOT (source_metadata ? 'credential_migration_pending')")
        return cursor.fetchone()[0]


def test_account_migration_retains_original_password_and_repeat_safety(target):
    row = historical_user()
    member(target, row)
    with psycopg2.connect(target) as connection:
        assert import_users(connection, [row])["dry_run"] is True
    assert count(target) == 0
    with psycopg2.connect(target) as connection:
        assert import_users(connection, [row], dry_run=False)["updated"] == 1
    with psycopg2.connect(target) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT user_id,password_hash,create_time,source_metadata FROM nexent.user_account_t"
        )
        identity, encoded, created, metadata = cursor.fetchone()
        assert identity == row["id"]
        assert encoded == row["encrypted_password"]
        assert verify_password("OriginalPassword123", encoded)
        assert not verify_password("wrong", encoded)
        assert created.year == 2020
        assert metadata["raw_app_meta_data"] == {"role": "admin"}
        cursor.execute(
            "UPDATE nexent.user_account_t SET password_hash=NULL,password_login_enabled=false,token_version=1"
        )
    with psycopg2.connect(target) as connection:
        assert import_users(connection, [row], dry_run=False)["skipped"] == 1
    with psycopg2.connect(target) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT password_hash,token_version FROM nexent.user_account_t")
        assert cursor.fetchone() == (None, 1)
        cursor.execute(
            "SELECT ut.user_id,a.user_email,ut.delete_flag FROM nexent.user_tenant_t ut JOIN nexent.user_account_t a ON a.user_id=ut.user_id"
        )
        assert cursor.fetchone() == (row["id"], row["email"], "N")


def test_account_migration_conflict_rolls_back_all_users(target):
    first = historical_user()
    conflict = historical_user()
    with pytest.raises(MigrationConflict), psycopg2.connect(target) as connection:
        import_users(connection, [first, conflict], dry_run=False)
    assert count(target) == 0
    with psycopg2.connect(target) as connection:
        import_users(connection, [first], dry_run=False)
    with pytest.raises(MigrationConflict), psycopg2.connect(target) as connection:
        import_users(connection, [conflict], dry_run=False)
    assert count(target) == 1


def test_account_migration_keeps_orphans_disabled(target):
    row = historical_user()
    with psycopg2.connect(target) as connection:
        assert import_users(connection, [row], dry_run=False)["disabled_orphans"] == 1
    with psycopg2.connect(target) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT user_id,account_status FROM nexent.user_account_t")
        assert cursor.fetchone() == (row["id"], "disabled")


def test_account_migration_source_snapshot_without_audit_import(target, capsys):
    row = historical_user()
    member(target, row)
    with disposable_database() as source_dsn:
        with psycopg2.connect(source_dsn) as source, source.cursor() as cursor:
            cursor.execute(
                "CREATE SCHEMA auth; CREATE TABLE auth.users (id uuid, email text, encrypted_password text, email_confirmed_at timestamptz,created_at timestamptz)"
            )
            cursor.execute(
                "CREATE TABLE auth.identities (user_id uuid,provider text,identity_data jsonb)"
            )
            cursor.execute(
                "CREATE FUNCTION auth.reject_audit_read() RETURNS jsonb LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'audit reads are forbidden'; END $$; "
                "CREATE VIEW auth.audit_log_entries AS SELECT "
                "'00000000-0000-0000-0000-000000000001'::uuid AS id, "
                "auth.reject_audit_read() AS payload"
            )
            cursor.execute(
                "INSERT INTO auth.users VALUES (%s,%s,%s,%s,%s)",
                (
                    row["id"],
                    row["email"],
                    row["encrypted_password"],
                    row["email_confirmed_at"],
                    row["created_at"],
                ),
            )
            cursor.execute(
                "INSERT INTO auth.identities VALUES (%s,'email',%s)",
                (row["id"], Json({"email": row["email"]})),
            )
        with psycopg2.connect(source_dsn) as source:
            source.set_session(readonly=True, isolation_level="REPEATABLE READ")
            rows = read_source_users(source)
            assert rows[0]["id"] == row["id"]
        params = parse_dsn(target)
        source_params = parse_dsn(source_dsn)
        env = {
            **os.environ,
            "SUPABASE_POSTGRES_HOST": source_params["host"],
            "SUPABASE_POSTGRES_PORT": source_params["port"],
            "SUPABASE_POSTGRES_USER": source_params["user"],
            "SUPABASE_POSTGRES_DB": source_params["dbname"],
            "SUPABASE_POSTGRES_PASSWORD": source_params["password"],
            "POSTGRES_HOST": params["host"],
            "POSTGRES_PORT": params["port"],
            "POSTGRES_USER": params["user"],
            "POSTGRES_DB": params["dbname"],
            "NEXENT_POSTGRES_PASSWORD": params["password"],
        }
        command = [sys.executable, str(ROOT / "deploy/sql/tools/supabase_to_postgres/migrate.py")]

        def run_cli(*args):
            result = subprocess.run(command + list(args), cwd=ROOT / "backend", env=env,
                                    capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            assert row["encrypted_password"] not in result.stdout + result.stderr
            assert source_dsn not in result.stdout + result.stderr
            return json.loads(result.stdout)

        preview = run_cli()
        assert preview["dry_run"] is True and preview["updated"] == 1
        with psycopg2.connect(target) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM nexent.user_account_t WHERE NOT (source_metadata ? 'credential_migration_pending')")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT to_regclass('nexent.user_auth_history_t')")
            assert cursor.fetchone()[0] is None
        applied = run_cli("--apply")
        assert applied["updated"] == 1
        assert "audit_history" not in preview and "audit_history" not in applied
        repeated = run_cli("--apply")
        assert repeated["skipped"] == 1
        assert "audit_history" not in repeated
    output = capsys.readouterr()
    assert row["encrypted_password"] not in output.out + output.err
    with psycopg2.connect(target) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT source_metadata->'source_provider_identities' FROM nexent.user_account_t"
        )
        assert cursor.fetchone()[0][0]["provider"] == "email"
        cursor.execute("SELECT to_regclass('nexent.user_auth_history_t')")
        assert cursor.fetchone()[0] is None


def test_account_migration_database_error_rolls_back_partial_inserts(target):
    first = historical_user()
    second = historical_user()
    second["email"] = "reject@example.com"
    with psycopg2.connect(target) as connection, connection.cursor() as cursor:
        cursor.execute("""CREATE FUNCTION nexent.reject_test_row() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.user_email='reject@example.com' THEN RAISE EXCEPTION 'test rejection'; END IF; RETURN NEW; END $$;
            CREATE TRIGGER reject_test_row BEFORE INSERT ON nexent.user_account_t
            FOR EACH ROW EXECUTE PROCEDURE nexent.reject_test_row();""")
    with pytest.raises(psycopg2.Error), psycopg2.connect(target) as connection:
        import_users(connection, [first, second], dry_run=False)
    assert count(target) == 0


def test_account_migration_serializes_online_creation_with_one_writer_lock(target):
    with psycopg2.connect(target) as migration, psycopg2.connect(target) as writer:
        import_users(migration, [historical_user()], dry_run=True)
        with writer.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock_shared(hashtext('account-writers'))")
            assert cursor.fetchone()[0] is False
        migration.commit()
        with writer.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock_shared(hashtext('account-writers'))")
            assert cursor.fetchone()[0] is True


def test_account_profile_single_sql_upgrade_and_replay():
    sql = (ROOT / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql").read_text(encoding="utf-8")
    original = historical_user()
    pending = historical_user()
    pending["email"] = "pending@example.com"
    with disposable_database() as dsn:
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA nexent")
            cursor.execute(sql)
            cursor.execute("ALTER TABLE nexent.user_account_t RENAME COLUMN user_email TO email; ALTER TABLE nexent.user_account_t DROP COLUMN user_role")
            cursor.execute("CREATE TABLE nexent.user_tenant_t (user_id varchar(100),tenant_id varchar(100),user_role varchar(30),user_email varchar(255),delete_flag varchar(1) DEFAULT 'N')")
            cursor.execute("INSERT INTO nexent.user_account_t (user_id,email,password_hash,token_version) VALUES (%s,%s,%s,7)",
                           (original["id"],original["email"],original["encrypted_password"]))
            cursor.execute("INSERT INTO nexent.user_tenant_t (user_id,tenant_id,user_role,user_email) VALUES (%s,'tenant','USER',%s),(%s,'tenant','SU',%s)",
                           (original["id"],original["email"],pending["id"],pending["email"]))
            cursor.execute("INSERT INTO nexent.user_tenant_t (user_id,tenant_id,user_role,user_email,delete_flag) VALUES ('deleted-identity','tenant','DEV','deleted@example.com','Y')")
            cursor.execute(sql)
            cursor.execute(sql)
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_tenant_t'")
            assert not {"user_role","user_email"} & {row[0] for row in cursor.fetchall()}
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='nexent' AND table_name='user_account_t'")
            columns = {row[0] for row in cursor.fetchall()}
            assert {"user_role","user_email"} <= columns and "email" not in columns
            cursor.execute("SELECT password_hash,token_version,user_role FROM nexent.user_account_t WHERE user_id=%s",(original["id"],))
            assert cursor.fetchone() == (original["encrypted_password"],7,"USER")
            cursor.execute("SELECT password_hash,account_status,source_metadata FROM nexent.user_account_t WHERE user_id=%s",(pending["id"],))
            placeholder = cursor.fetchone()
            assert placeholder[0] is None and placeholder[1] == "disabled"
            assert placeholder[2]["credential_migration_pending"] is True
            cursor.execute("SELECT user_role,user_email,delete_flag,account_status FROM nexent.user_account_t WHERE user_id='deleted-identity'")
            assert cursor.fetchone() == ("DEV","deleted@example.com","Y","disabled")
        with psycopg2.connect(dsn) as connection:
            assert import_users(connection,[pending],dry_run=False)["updated"] == 1
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT user_role,password_hash FROM nexent.user_account_t WHERE user_id=%s",(pending["id"],))
            assert cursor.fetchone() == ("SU",pending["encrypted_password"])
            cursor.execute("UPDATE nexent.user_account_t SET user_role='ADMIN',user_email='edited@example.com' WHERE user_id=%s",(original["id"],))
            cursor.execute(sql)
            cursor.execute("SELECT user_role,user_email,password_hash,token_version FROM nexent.user_account_t WHERE user_id=%s",(original["id"],))
            assert cursor.fetchone() == ("ADMIN","edited@example.com",original["encrypted_password"],7)


@pytest.mark.parametrize("role,email", [("SU","same@example.com"),("USER","different@example.com")])
def test_account_profile_conflict_rolls_back_single_sql(role, email):
    sql = (ROOT / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql").read_text(encoding="utf-8")
    with disposable_database() as dsn:
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA nexent; CREATE TABLE nexent.user_tenant_t (user_id varchar(100),user_role varchar(30),user_email varchar(255),delete_flag varchar(1) DEFAULT 'N')")
            cursor.execute("INSERT INTO nexent.user_tenant_t (user_id,user_role,user_email) VALUES ('same-id','USER','same@example.com'),('same-id',%s,%s)",(role,email))
        with pytest.raises(psycopg2.Error), psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(sql)
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('nexent.user_account_t')")
            assert cursor.fetchone()[0] is None
            cursor.execute("SELECT count(*) FROM nexent.user_tenant_t WHERE user_role IS NOT NULL AND user_email IS NOT NULL")
            assert cursor.fetchone()[0] == 2
