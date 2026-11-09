# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""New migrations reject incomplete data before commit; old inconsistencies stop."""
from uuid import uuid4

import bcrypt
import psycopg2
import pytest

from local_auth import disposable_database
from deploy.sql.tools.supabase_to_postgres import migrate_docker as migration


def assert_account_coverage(scenario):
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
                cursor.execute((migration.ROOT / 'deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql').read_text(encoding='utf-8'))
                if scenario == 'existing-partial':
                    cursor.execute("INSERT INTO nexent.user_tenant_t (user_id,tenant_id,delete_flag) VALUES (%s,'retained','N')", (preserved,))
                    cursor.execute("INSERT INTO nexent.user_account_t (user_id,user_email,user_role,password_hash,password_hash_scheme,password_login_enabled,token_version) VALUES (%s,'preserved@example.com','USER',%s,'bcrypt',true,7)", (preserved,local_hash))
        with psycopg2.connect(dsn) as connection:
            state = migration.inspect_accounts(connection)
            assert not state['complete'] and state['unresolved_ids'] == [uid]
            assert state['account_table'] is existing
        rows = [] if scenario == 'source-empty' else [row]
        if scenario == 'source-passwordless':
            row['encrypted_password'] = None
        if scenario == 'excluded':
            row['deleted_at'] = '2020-01-01T00:00:00Z'
        if existing or scenario in {'source-empty','source-passwordless'}:
            error_type = migration.MigrationSetupError if existing else migration.MigrationConflict
            with pytest.raises(error_type, match=uid), psycopg2.connect(dsn) as connection:
                migration.import_users(connection, rows, dry_run=False)
            with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
                assert not migration.inspect_accounts(connection)['complete']
                cursor.execute("SELECT to_regclass('nexent.user_account_t') IS NOT NULL")
                assert cursor.fetchone()[0] is existing
                cursor.execute("SELECT to_regclass('nexent.account_migration_exclusion_t') IS NULL")
                assert cursor.fetchone()[0]
                if scenario == 'existing-partial':
                    cursor.execute('SELECT password_hash,token_version FROM nexent.user_account_t WHERE user_id=%s', (preserved,))
                    assert cursor.fetchone() == (local_hash,7)
                if not existing:
                    cursor.execute('SELECT user_role,user_email FROM nexent.user_tenant_t WHERE user_id=%s', (uid,))
                    assert cursor.fetchone() == ('USER',row['email'])
            return
        with psycopg2.connect(dsn) as connection:
            migration.import_users(connection, rows, dry_run=False)
        with psycopg2.connect(dsn) as connection, connection.cursor() as cursor:
            assert migration.inspect_accounts(connection)['complete']
            assert migration.import_users(connection, [], dry_run=False)['complete']
            cursor.execute('SELECT password_hash FROM nexent.user_account_t WHERE user_id=%s', (uid,))
            assert cursor.fetchone() == (None if scenario == 'excluded' else (encoded,))
            if scenario == 'excluded':
                cursor.execute('SELECT exclusion_reason FROM nexent.account_migration_exclusion_t WHERE user_id=%s', (uid,))
                assert cursor.fetchone() == ('source_unavailable',)
