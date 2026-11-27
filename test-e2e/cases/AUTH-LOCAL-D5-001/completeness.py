# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Coverage gaps warn on new and existing account tables without deleting data."""
from uuid import uuid4

import bcrypt
import psycopg2

from local_auth import disposable_database
from deploy.sql.tools.supabase_to_postgres import migrate_docker as migration


def assert_account_coverage(scenario, capsys):
    uid, preserved = str(uuid4()), str(uuid4())
    encoded = bcrypt.hashpw(b"original", bcrypt.gensalt(rounds=4)).decode()
    local_hash = bcrypt.hashpw(b"operator-new", bcrypt.gensalt(rounds=4)).decode()
    row = {"id": uid, "email": "migration@example.com", "encrypted_password": encoded}
    existing = scenario.startswith('existing-')
    with disposable_database() as dsn:
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA nexent; CREATE TABLE nexent.user_tenant_t (user_id varchar(100),tenant_id varchar(100),user_role varchar(30),user_email varchar(255),delete_flag varchar(1) DEFAULT 'N')")
            cursor.execute("INSERT INTO nexent.user_tenant_t VALUES (%s,'original-tenant','USER',%s,'N')", (uid,row['email']))
            if existing:
                # Reproduce standalone SQL having committed before import.
                cursor.execute(migration.merged_migration_section("v2.9.0_001_local_user_accounts.sql"))
                if scenario == 'existing-partial':
                    cursor.execute("INSERT INTO nexent.user_tenant_t (user_id,tenant_id,delete_flag) VALUES (%s,'retained','N')", (preserved,))
                    cursor.execute("INSERT INTO nexent.user_account_t (user_id,user_email,user_role,password_hash,password_hash_scheme,password_login_enabled,token_version) VALUES (%s,'preserved@example.com','USER',%s,'bcrypt',true,7)", (preserved,local_hash))
                cursor.execute("ALTER TABLE nexent.user_tenant_t ADD COLUMN user_email varchar(255)")
                cursor.execute("UPDATE nexent.user_tenant_t SET user_email=%s WHERE user_id=%s", (row["email"],uid))
            if scenario == "banned-provider":
                cursor.execute("CREATE TABLE nexent.user_oauth_account_t (user_id varchar(100),delete_flag varchar(1))")
                cursor.execute("INSERT INTO nexent.user_oauth_account_t VALUES (%s,'N')", (uid,))
        with psycopg2.connect(dsn) as connection:
            state = migration.inspect_accounts(connection)
            assert not state['complete'] and state['unresolved_ids'] == [uid]
            assert state['account_table'] is existing
        rows = [] if scenario == 'source-empty' else [row]
        if scenario == 'source-passwordless':
            row['encrypted_password'] = None
        if scenario == 'excluded':
            row['deleted_at'] = '2020-01-01T00:00:00Z'
        if scenario == "banned-provider":
            row["banned_until"] = "2099-01-01T00:00:00Z"
        if existing:
            with psycopg2.connect(dsn) as connection:
                result = migration.import_users(connection, rows, dry_run=False)
                assert result == {"skipped": len(rows), "complete": False, "dry_run": False}
            warning = capsys.readouterr().err
            assert "[warning]" in warning and uid in warning and row["email"] in warning
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                assert not migration.inspect_accounts(connection)['complete']
                cursor.execute("SELECT to_regclass('nexent.user_account_t') IS NOT NULL")
                assert cursor.fetchone()[0] is existing
                cursor.execute("SELECT to_regclass('nexent.account_migration_exclusion_t') IS NULL")
                assert cursor.fetchone()[0]
                if scenario == 'existing-partial':
                    cursor.execute('SELECT password_hash,token_version FROM nexent.user_account_t WHERE user_id=%s', (preserved,))
                    assert cursor.fetchone() == (local_hash,7)
            return
        if scenario == "source-empty":
            with psycopg2.connect(dsn) as connection:
                assert migration.import_users(connection, rows)["dry_run"]
            preview_warning = capsys.readouterr().err
            assert "[warning]" in preview_warning and uid in preview_warning and row["email"] in preview_warning
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                assert not migration.inspect_accounts(connection)["account_table"]
                cursor.execute("SELECT user_role,user_email FROM nexent.user_tenant_t WHERE user_id=%s", (uid,))
                assert cursor.fetchone() == ("USER", row["email"])
        with psycopg2.connect(dsn) as connection:
            migration.import_users(connection, rows, dry_run=False)
        warning = capsys.readouterr().err
        incomplete = scenario in {"source-empty", "source-passwordless"}
        if incomplete:
            assert "[warning]" in warning and uid in warning and row["email"] in warning
        else:
            assert warning == ""
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            assert migration.inspect_accounts(connection)['complete']
            assert migration.import_users(connection, [], dry_run=False)['complete']
            cursor.execute('SELECT user_email,password_hash,delete_flag FROM nexent.user_account_t WHERE user_id=%s', (uid,))
            assert cursor.fetchone() == {
                "excluded": None,
                "source-empty": (row["email"], None, "Y"),
                "source-passwordless": (row["email"], None, "N"),
                "banned-provider": (row["email"], encoded, "Y"),
            }.get(scenario, (row["email"], encoded, "N"))
            cursor.execute("SELECT tenant_id,delete_flag FROM nexent.user_tenant_t WHERE user_id=%s", (uid,))
            assert cursor.fetchone() == ("original-tenant", "N")
            if incomplete:
                cursor.execute('SELECT exclusion_reason FROM nexent.account_migration_exclusion_t WHERE user_id=%s', (uid,))
                assert cursor.fetchone() == ('incomplete_source_coverage',)
            if scenario == 'excluded':
                cursor.execute('SELECT exclusion_reason FROM nexent.account_migration_exclusion_t WHERE user_id=%s', (uid,))
                assert cursor.fetchone() == ('source_unavailable',)
