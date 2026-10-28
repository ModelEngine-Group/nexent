# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local account persistence; email/ID uniqueness is serialized by transaction locks."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select, text, update

from contracts.errors.exceptions import AccountConflictError
from management.utils.orm import as_dict
from management.db.client import get_db_session
from management.db.models import UserAccount


def lock_account_keys(session, user_id: str, email: str) -> None:
    # Migration holds the exclusive form, avoiding one advisory lock per source
    # row while keeping online creation serialized against the full import.
    session.execute(text("SELECT pg_advisory_xact_lock_shared(hashtext('account-writers'))"))
    # Stable ordering prevents cross-key deadlocks between online writers.
    for key in sorted({f"account-id:{user_id}", f"account-email:{email}"}):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key}
        )


def _one(statement, db_session=None):
    with get_db_session(db_session) as session:
        rows = session.execute(statement).scalars().all()
        if len(rows) > 1:
            raise AccountConflictError("Ambiguous account identity")
        return _account_dict(rows[0]) if rows else None


def get_account(user_id: str, db_session=None):
    return _one(
        select(UserAccount).where(
            UserAccount.user_id == user_id, UserAccount.delete_flag == "N"
        ),
        db_session,
    )


def get_account_by_email(email: str, db_session=None):
    return _one(
        select(UserAccount).where(
            UserAccount.user_email == str(email).strip().lower(),
            UserAccount.delete_flag == "N",
        ),
        db_session,
    )


def create_account(email: str, password_hash=None, *, user_id=None, db_session=None):
    user_id = user_id or str(uuid4())
    email = str(email).strip().lower()
    if (
        not email
        or len(email) > 255
        or email.count("@") != 1
        or any(character.isspace() for character in email)
    ):
        raise ValueError("Invalid account email")
    with get_db_session(db_session) as session:
        lock_account_keys(session, user_id, email)
        if get_account(user_id, session) or get_account_by_email(email, session):
            raise AccountConflictError("Email already exists")
        from infrastructure.security.passwords import password_scheme

        account = UserAccount(
            user_id=user_id,
            user_email=email,
            password_hash=password_hash,
            password_hash_scheme=password_scheme(password_hash)
            if password_hash
            else None,
            password_login_enabled=bool(password_hash),
            account_status="active",
            token_version=0,
            email_confirmed_at=datetime.utcnow(),
            created_by=user_id,
            updated_by=user_id,
            delete_flag="N",
            source_metadata={},
        )
        session.add(account)
        session.flush()
        return _account_dict(account)


def delete_account(user_id: str, db_session=None):
    with get_db_session(db_session) as session:
        session.execute(
            update(UserAccount)
            .where(UserAccount.user_id == user_id, UserAccount.delete_flag == "N")
            .values(
                delete_flag="Y",
                account_status="disabled",
                token_version=UserAccount.token_version + 1,
                password_hash=None,
                password_login_enabled=False,
                updated_by=user_id,
                update_time=datetime.utcnow(),
            )
        )


def change_password(user_id: str, expected_hash: str, password_hash: str):
    """Compare-and-swap prevents overwriting a concurrent password change."""
    from infrastructure.security.passwords import password_scheme

    with get_db_session() as session:
        result = session.execute(
            update(UserAccount)
            .where(
                UserAccount.user_id == user_id,
                UserAccount.password_hash == expected_hash,
                UserAccount.account_status == "active",
                UserAccount.delete_flag == "N",
            )
            .values(
                password_hash=password_hash,
                password_hash_scheme=password_scheme(password_hash),
                password_login_enabled=True,
                token_version=UserAccount.token_version + 1,
                updated_by=user_id,
                update_time=datetime.utcnow(),
            )
        )
        return result.rowcount == 1


def _account_dict(account):
    result = as_dict(account)
    # Existing HTTP/service contracts still expose the established email key.
    result["email"] = result.get("user_email")
    return result


def set_account_profile(user_id, role, email, actor, session):
    account = get_account(user_id, session)
    if not account:
        raise AccountConflictError("Account profile is missing; run the account schema migration first")
    values = {"user_role": role, "updated_by": actor, "update_time": datetime.utcnow()}
    if email is not None:
        email = str(email).strip().lower()
        lock_account_keys(session, user_id, email)
        existing = get_account_by_email(email, session)
        if existing and existing["user_id"] != user_id:
            raise AccountConflictError("Email already exists")
        values["user_email"] = email
    session.execute(update(UserAccount).where(UserAccount.user_id == user_id, UserAccount.delete_flag == "N").values(**values))
