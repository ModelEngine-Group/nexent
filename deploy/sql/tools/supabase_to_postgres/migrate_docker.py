# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Database-only worker for the Shell-orchestrated account migration."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "deploy/sql/migrations").is_dir()), Path.cwd())


def password_scheme(encoded):
    """Validate imported hash formats without importing application code."""
    if re.fullmatch(r"\$2[aby]\$(0[4-9]|1[0-6])\$[./A-Za-z0-9]{53}", encoded or ""):
        return "bcrypt"
    parts = (encoded or "").split("$")
    if len(parts) == 6 and parts[:4] == ["scrypt", "16384", "8", "1"]:
        try:
            if len(base64.b64decode(parts[4], validate=True)) == 16 and len(base64.b64decode(parts[5], validate=True)) == 32:
                return "scrypt"
        except ValueError:
            pass
    raise ValueError("Unsupported password hash format")


class MigrationSetupError(ValueError):
    """Operator-actionable prerequisite error containing no credential values."""


def _port(value):
    try:
        result = int(value)
        if not 1 <= result <= 65535:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise MigrationSetupError("Database port must be between 1 and 65535") from None


class MigrationConflict(ValueError):
    """Sanitized migration error; never include source rows or credentials."""


def utc_time(value):
    if not value:
        return None
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo:
        result = result.astimezone(timezone.utc).replace(tzinfo=None)
    return result


def map_source_user(row: dict) -> dict:
    """Map explicit fields only. Provider metadata never supplies application roles."""
    try:
        user_id = str(UUID(str(row["id"])))
        email = str(row.get("email") or "").strip().lower()
        if not email or len(email) > 255 or "@" not in email:
            raise MigrationConflict("Source contains an unsupported email identity")
        encoded = row.get("encrypted_password") or None
        scheme = password_scheme(encoded) if encoded else None
        metadata = {
            "raw_user_meta_data": row.get("raw_user_meta_data") or {},
            "raw_app_meta_data": row.get("raw_app_meta_data") or {},
            "source_provider_identities": row.get("source_provider_identities") or [],
            "phone": row.get("phone"),
            "phone_confirmed_at": row.get("phone_confirmed_at"),
            "last_sign_in_at": row.get("last_sign_in_at"),
            "invited_at": row.get("invited_at"),
            "banned_until": row.get("banned_until"),
            "source_deleted_at": row.get("deleted_at"),
        }
        if len(json.dumps(metadata, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
            raise MigrationConflict("Source account metadata exceeds the import limit")
        banned = utc_time(row.get("banned_until"))
        deleted = bool(row.get("deleted_at"))
        disabled = (
            deleted
            or (banned and banned > datetime.now(timezone.utc).replace(tzinfo=None))
            or bool(row.get("is_anonymous"))
        )
        return {
            "user_id": user_id,
            "email": email,
            "password_hash": encoded,
            "password_hash_scheme": scheme,
            "password_login_enabled": bool(encoded),
            "token_version": 0,
            "email_confirmed_at": utc_time(row.get("email_confirmed_at")),
            "create_time": utc_time(row.get("created_at")) or datetime.now(timezone.utc).replace(tzinfo=None),
            "update_time": utc_time(row.get("updated_at")) or datetime.now(timezone.utc).replace(tzinfo=None),
            "delete_flag": "Y" if disabled else "N",
            "source_metadata": metadata,
        }
    except MigrationConflict:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise MigrationConflict(
            "Source account has an unsupported identifier, date or password hash"
        ) from None


def read_source_users(source) -> list:
    """Caller must configure this source connection as read-only/repeatable-read."""
    with source.cursor() as cursor:
        cursor.execute("SELECT row_to_json(u) FROM auth.users u ORDER BY id")
        users = [record[0] for record in cursor.fetchall()]
        cursor.execute("SELECT to_regclass('auth.identities') IS NOT NULL")
        if cursor.fetchone()[0]:
            cursor.execute(
                "SELECT row_to_json(i) FROM auth.identities i ORDER BY user_id"
            )
            identities = {}
            for (identity,) in cursor.fetchall():
                identities.setdefault(str(identity["user_id"]), []).append(identity)
            for user in users:
                user["source_provider_identities"] = identities.get(str(user["id"]), [])
    return users


def inspection_sql():
    """Inspect membership coverage and usable credentials without persistent writes."""
    return (HERE / "inspect_accounts.sql").read_text(encoding="utf-8")


def inspect_accounts(target):
    with target.cursor() as cursor:
        cursor.execute(inspection_sql())
        return cursor.fetchone()[0]


def account_data_complete(state):
    """Reject incomplete existing tables; automatic migration never repairs them."""
    if state["complete"]:
        return True
    if state.get("account_table"):
        raise MigrationSetupError("Existing account data is incomplete; IDs: "
            + json.dumps(state.get("unresolved_ids", []))
            + "; restore the consistent pre-upgrade backup before retrying; no automatic repair was attempted")
    return False


def _account_import_sql(source_rows, *, dry_run=False):
    """Build one credential/schema transaction body, shared by host and psql."""
    rows = [map_source_user(row) for row in source_rows]
    ids = set()
    for row in rows:
        if row["user_id"] in ids:
            raise MigrationConflict("Account migration conflict IDs: " + json.dumps([row["user_id"]]))
        ids.add(row["user_id"])
        row["user_email"] = row.pop("email")
    encoded = json.dumps(rows, default=lambda value: value.isoformat()).replace("'", "''")
    schema = (ROOT / "deploy/sql/migrations/v2.9.0_001_local_user_accounts.sql").read_text(encoding="utf-8")
    roles_schema = (ROOT / "deploy/sql/migrations/v2.9.0_010_account_and_ops_roles.sql").read_text(encoding="utf-8")
    return "SET LOCAL standard_conforming_strings=on;\n" + inspection_sql() + r"""
SET LOCAL nexent.account_import='on';
""" + schema + "\n" + roles_schema + "\n" + r"""
CREATE TABLE IF NOT EXISTS nexent.account_migration_exclusion_t (
    exclusion_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL UNIQUE,
    exclusion_reason VARCHAR(100) NOT NULL,
    created_by VARCHAR(100) NOT NULL DEFAULT 'auth-migration',
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) NOT NULL DEFAULT 'auth-migration',
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N'
);
COMMENT ON TABLE nexent.account_migration_exclusion_t IS 'Per-identity evidence for unavailable historical accounts intentionally excluded from local authentication';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.exclusion_id IS 'Technical exclusion evidence identifier';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.user_id IS 'Original historical user identifier';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.exclusion_reason IS 'Source eligibility decision without credential material';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.created_by IS 'Migration actor that recorded the exclusion';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.create_time IS 'UTC exclusion creation time';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.updated_by IS 'Migration actor that last changed the exclusion';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.update_time IS 'UTC exclusion update time';
COMMENT ON COLUMN nexent.account_migration_exclusion_t.delete_flag IS 'N for applicable historical exclusion, Y for retired evidence';

CREATE TEMP TABLE account_import ON COMMIT DROP AS
SELECT s.*, (s.delete_flag='Y') AS source_inactive, coalesce(CASE WHEN p.role_value IS NOT NULL THEN ARRAY[p.role_value]::varchar[] END,a.user_roles) AS role_values,
       coalesce(p.email_value,a.user_email) AS profile_email,
       (p.user_id IS NOT NULL OR a.user_id IS NOT NULL) AS existing,
       NOT EXISTS (SELECT 1 FROM nexent.user_tenant_t u
                   WHERE u.user_id=s.user_id AND u.delete_flag='N') AS orphan
FROM jsonb_populate_recordset(NULL::nexent.user_account_t, '__ROWS__'::jsonb) s
LEFT JOIN pg_temp.account_migration_profiles p ON p.user_id=s.user_id
LEFT JOIN nexent.user_account_t a ON a.user_id=s.user_id;
UPDATE account_import SET delete_flag='Y' WHERE orphan OR role_values IS NULL OR cardinality(role_values)=0;
DO $validate$
DECLARE conflict_ids json;
BEGIN
    SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids FROM (
        SELECT DISTINCT user_id FROM account_import
        WHERE delete_flag='N' AND profile_email IS NOT NULL AND profile_email<>user_email
    ) conflicts;
    IF conflict_ids IS NOT NULL THEN
        RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids;
    END IF;
END
$validate$;
UPDATE nexent.user_account_t a SET
    user_email=s.user_email,user_roles=s.role_values,password_hash=s.password_hash,password_hash_scheme=s.password_hash_scheme,
    password_login_enabled=s.password_login_enabled,token_version=s.token_version,
    email_confirmed_at=s.email_confirmed_at,source_metadata=s.source_metadata,
    create_time=s.create_time,update_time=s.update_time,delete_flag=s.delete_flag,updated_by='auth-migration'
FROM account_import s WHERE a.user_id=s.user_id;
INSERT INTO nexent.user_account_t
    (user_id,user_email,user_roles,password_hash,password_hash_scheme,password_login_enabled,token_version,
     email_confirmed_at,source_metadata,create_time,update_time,delete_flag,created_by,updated_by)
SELECT user_id,user_email,role_values,password_hash,password_hash_scheme,password_login_enabled,token_version,
       email_confirmed_at,source_metadata,create_time,update_time,delete_flag,'auth-migration','auth-migration'
FROM account_import s WHERE delete_flag='N'
AND NOT EXISTS (SELECT 1 FROM nexent.user_account_t a WHERE a.user_id=s.user_id);
DELETE FROM nexent.user_account_t WHERE delete_flag='Y'
AND coalesce(source_metadata->>'system_identity','')<>'speed';
DO $email_conflicts$
DECLARE conflict_ids json;
BEGIN
    SELECT json_agg(user_id ORDER BY user_id) INTO conflict_ids
    FROM nexent.user_account_t
    WHERE delete_flag='N' AND lower(trim(user_email)) IN (
        SELECT lower(trim(user_email)) FROM nexent.user_account_t
        WHERE delete_flag='N' AND user_email IS NOT NULL
        GROUP BY lower(trim(user_email)) HAVING count(*)>1
    );
    IF conflict_ids IS NOT NULL THEN
        RAISE EXCEPTION 'NEXENT_ACCOUNT_CONFLICT=%',conflict_ids;
    END IF;
END
$email_conflicts$;
INSERT INTO nexent.account_migration_exclusion_t (user_id,exclusion_reason)
SELECT user_id,'source_unavailable' FROM account_import WHERE source_inactive AND NOT orphan
ON CONFLICT (user_id) DO NOTHING;
DO $coverage$
DECLARE unresolved json := pg_temp.inspect_local_accounts()->'unresolved_ids';
BEGIN
    IF json_array_length(unresolved)>0 THEN
        RAISE EXCEPTION 'NEXENT_ACCOUNT_INCOMPLETE=%',unresolved;
    END IF;
END
$coverage$;
SET LOCAL nexent.account_import='off';
SELECT json_build_object('source',__SOURCE_COUNT__,'inserted',count(*) FILTER (WHERE NOT existing AND delete_flag='N'),
                         'updated',count(*) FILTER (WHERE existing AND delete_flag='N'),
                         'skipped',count(*) FILTER (WHERE delete_flag='Y'),
                         'excluded_inactive',count(*) FILTER (WHERE delete_flag='Y'),
                         'disabled_orphans',count(*) FILTER (WHERE orphan),'dry_run',__DRY_RUN__)
FROM account_import;
""".replace("__DRY_RUN__", "true" if dry_run else "false").replace("__SOURCE_COUNT__", str(len(rows))).replace("__ROWS__", encoded)


def import_users(target, source_rows: list, *, dry_run: bool = True) -> dict:
    """Commit only complete new migrations; existing inconsistent tables require recovery."""
    with target.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('account-writers'))")
        state = inspect_accounts(target)
        if account_data_complete(state):
            return {"skipped": len(source_rows), "complete": True, "dry_run": dry_run}
        cursor.execute("SAVEPOINT account_migration")
        try:
            cursor.execute(_account_import_sql(source_rows, dry_run=dry_run))
            result = cursor.fetchone()[0]
        except Exception as exc:
            conflict = _migration_conflict(getattr(getattr(exc, "diag", None), "message_primary", ""))
            cursor.execute("ROLLBACK TO SAVEPOINT account_migration")
            cursor.execute("RELEASE SAVEPOINT account_migration")
            if conflict:
                raise conflict from None
            raise
        if dry_run:
            cursor.execute("ROLLBACK TO SAVEPOINT account_migration")
        cursor.execute("RELEASE SAVEPOINT account_migration")
        return result


def _migration_conflict(message):
    """Extract only structured account identifiers, never raw database output."""
    match = re.search(r'(?:^|ERROR:\s*)NEXENT_ACCOUNT_(CONFLICT|INCOMPLETE)=(\[[^\r\n]*\])', message or '', re.M)
    if not match:
        return None
    try:
        ids = json.loads(match.group(2))
        if not isinstance(ids, list) or not ids:
            return None
        if any(not isinstance(value,str) or not 0<len(value)<=100 or any(ord(c)<32 for c in value) for value in ids):
            return None
        ids = sorted(set(ids))
    except (ValueError, TypeError, AttributeError):
        return None
    if match.group(1) == "INCOMPLETE":
        return MigrationConflict("Incomplete account migration IDs: " + json.dumps(ids)
            + "; verify original Supabase coverage and restore missing legacy role/email profiles from backup")
    return MigrationConflict("Account migration conflict IDs: " + json.dumps(ids))


def container_main(argv=None):
    """Database-only worker; platform lifecycle belongs to the host Shell."""
    import psycopg2

    parser = argparse.ArgumentParser(description="Run account migration inside an isolated container")
    parser.add_argument("--container", action="store_true", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wait-timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if not 1 <= args.wait_timeout <= 300:
        parser.error("--wait-timeout must be between 1 and 300")

    def parameters(prefix, password_key):
        values = os.environ
        required = [prefix + "POSTGRES_HOST", password_key]
        if any(not values.get(key) for key in required):
            raise MigrationSetupError("Database host/password is missing from the migration environment")
        return {
            "host": values[prefix + "POSTGRES_HOST"],
            "port": _port(values.get(prefix + "POSTGRES_PORT") or 5432),
            "dbname": values.get(prefix + "POSTGRES_DB") or ("supabase" if prefix else "nexent"),
            "user": values.get(prefix + "POSTGRES_USER") or "postgres",
            "password": values[password_key], "connect_timeout": 5,
        }

    try:
        with psycopg2.connect(**parameters("", "NEXENT_POSTGRES_PASSWORD")) as target:
            try:
                with target.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('account-writers'))")
                state = inspect_accounts(target)
                complete, legacy = account_data_complete(state), state["legacy"]
                if complete or not legacy:
                    print(json.dumps({"skipped": True, "complete": complete, "new": not legacy}))
                    return 0
                source_params = parameters("SUPABASE_", "SUPABASE_POSTGRES_PASSWORD")
                deadline = time.monotonic() + args.wait_timeout
                while True:
                    try:
                        source = psycopg2.connect(**source_params)
                        break
                    except psycopg2.OperationalError:
                        if time.monotonic() >= deadline:
                            raise MigrationSetupError("Original Supabase is unavailable; check source readiness and credentials") from None
                        time.sleep(1)
                try:
                    with source:
                        source.set_session(readonly=True, isolation_level="REPEATABLE READ")
                        rows = read_source_users(source)
                        print("[account-migration][snapshot] Source rows=" + str(len(rows))
                              + " rows_with_password=" + str(sum(bool(row.get("encrypted_password")) for row in rows)), file=sys.stderr)
                finally:
                    source.close()
                result = import_users(target, rows, dry_run=not args.apply)
            except Exception:
                target.rollback()
                raise
        result["committed"] = args.apply and not result.get("complete", False)
        print(json.dumps(result))
        return 0
    except (MigrationConflict, MigrationSetupError) as error:
        print("Account upgrade rejected: " + str(error), file=sys.stderr)
    except Exception as error:  # noqa: BLE001 -- Never log driver text or credentials.
        print("Account upgrade failed (" + type(error).__name__ + "); target transaction rolled back", file=sys.stderr)
    finally:
        if "target" in locals():
            target.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(container_main())
