# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Atomic, repeat-safe import from a read-only GoTrue PostgreSQL snapshot."""

import json
from datetime import datetime, timezone
from uuid import UUID

from psycopg2.extras import Json, RealDictCursor

from infrastructure.security.passwords import password_scheme


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
            or (banned and banned > datetime.utcnow())
            or bool(row.get("is_anonymous"))
        )
        cas_only = (row.get("raw_user_meta_data") or {}).get("provider") == "cas"
        return {
            "user_id": user_id,
            "email": email,
            "password_hash": encoded,
            "password_hash_scheme": scheme,
            "password_login_enabled": bool(encoded) and not cas_only,
            "account_status": "disabled" if disabled else "active",
            "token_version": 0,
            "email_confirmed_at": utc_time(row.get("email_confirmed_at")),
            "create_time": utc_time(row.get("created_at")) or datetime.utcnow(),
            "update_time": utc_time(row.get("updated_at")) or datetime.utcnow(),
            "delete_flag": "Y" if deleted else "N",
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






def import_users(target, source_rows: list, *, dry_run: bool = True) -> dict:
    """Import credentials, hydrating only schema-created pending identities."""
    rows = [map_source_user(row) for row in source_rows]
    ids, emails = set(), set()
    for row in rows:
        if row["user_id"] in ids or (row["delete_flag"] == "N" and row["email"] in emails):
            raise MigrationConflict("Source has conflicting stable IDs or normalized emails")
        ids.add(row["user_id"])
        if row["delete_flag"] == "N":
            emails.add(row["email"])
    result = {"source": len(rows), "inserted": 0, "updated": 0, "skipped": 0,
              "disabled_orphans": 0, "dry_run": dry_run}
    plans = []
    with target.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('account-writers'))")
        for row in rows:
            cursor.execute(
                "SELECT user_id,user_email,source_metadata,password_hash,token_version,delete_flag,user_role "
                "FROM nexent.user_account_t WHERE user_id=%s OR (user_email=%s AND delete_flag='N' AND %s='N') FOR UPDATE",
                (row["user_id"], row["email"], row["delete_flag"]),
            )
            existing = cursor.fetchall()
            pending = False
            if existing:
                account = existing[0]
                profile_pending = (len(existing) == 1 and (account["source_metadata"] or {}).get("credential_migration_pending") is True
                           and account["password_hash"] is None and account["token_version"] == 0)
                pending = profile_pending and account["delete_flag"] == "N"
                if (len(existing) != 1 or account["user_id"] != row["user_id"]
                        or (account["user_email"] != row["email"] and not (profile_pending and account["user_email"] is None))):
                    raise MigrationConflict("Target account conflicts with a source identity")
                if not pending:
                    result["skipped"] += 1
                    continue
            cursor.execute("SELECT delete_flag FROM nexent.user_tenant_t WHERE user_id=%s", (row["user_id"],))
            active = [member for member in cursor.fetchall() if member["delete_flag"] == "N"]
            if active and not existing:
                raise MigrationConflict("Membership account profile is missing; apply the account SQL migration first")
            if not active or (pending and not account["user_role"]):
                row["account_status"] = "disabled"
                result["disabled_orphans"] += 1
            values = dict(row)
            values["user_email"] = values.pop("email")
            if not pending:
                values["user_role"] = None
            plans.append((pending, values))
            result["updated" if pending else "inserted"] += 1
        if dry_run:
            return result
        for pending, row in plans:
            values = dict(row, source_metadata=Json(row["source_metadata"]))
            if pending:
                user_id = values.pop("user_id")
                cursor.execute(
                    "UPDATE nexent.user_account_t SET " + ",".join(name + "=%s" for name in values)
                    + ",updated_by='auth-migration' WHERE user_id=%s AND password_hash IS NULL AND token_version=0 "
                    "AND delete_flag='N' AND source_metadata->>'credential_migration_pending'='true'",
                    [*values.values(), user_id],
                )
                if cursor.rowcount != 1:
                    raise MigrationConflict("Pending account changed concurrently; retry preflight")
            else:
                names = list(values)
                cursor.execute(
                    "INSERT INTO nexent.user_account_t (" + ",".join(names) + ",created_by,updated_by) VALUES ("
                    + ",".join(["%s"] * len(names)) + ",%s,%s)",
                    [*values.values(), "auth-migration", "auth-migration"],
                )
    return result
