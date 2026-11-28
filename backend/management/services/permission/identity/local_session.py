# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import hashlib
import hmac
import re
import secrets
import time
from uuid import uuid4

import jwt
from sqlalchemy import select, text

from contracts.constants.environment import JWT_EXPIRY_SECONDS, JWT_ISSUER, JWT_SECRET
from contracts.errors.exceptions import UnauthorizedError
from gateway.identity.token_codec import LOCAL_SESSION_PREFIX, decode_session, is_local_session_id
from infrastructure.rdb.client import get_db_session
from management.db.identity.models import UserAccount, UserTenant
from management.services.permission.identity.session import generate_session_jwt, get_jwt_expiry_seconds, require_active_account

IDLE_SECONDS = 8 * 60 * 60
ABSOLUTE_SECONDS = 7 * 24 * 60 * 60
RETRY_SECONDS = 60


class InvalidRefreshRequestId(ValueError):
    """The optional renewal request identifier does not match the wire contract."""


class RefreshConflict(Exception):
    """The preceding generation has already been rotated."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _successor(previous: str, sid: str, nonce: str) -> str:
    key = hmac.digest(JWT_SECRET.encode(), b"nexent-local-session-refresh-rotation-v1", "sha256")
    return hmac.new(key, f"{sid}:{nonce}:{previous}".encode(), "sha256").hexdigest()


def _response(user_id, version, sid, refresh, issued_at, access_exp, refresh_exp):
    access = generate_session_jwt(
        user_id, access_exp - issued_at, sid, issued_at=issued_at, token_version=version,
    )
    display_lifetime = get_jwt_expiry_seconds(access)
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": min(access_exp, issued_at + display_lifetime),
        "expires_in_seconds": min(access_exp - issued_at, display_lifetime),
        "refresh_expires_at": refresh_exp,
    }


def issue_local_session(user_id: str, token_version: int | None = None) -> dict:
    if token_version is None:
        token_version = require_active_account(user_id)["token_version"]
    sid = LOCAL_SESSION_PREFIX + uuid4().hex
    refresh = secrets.token_urlsafe(32)
    now = int(time.time())
    idle = now + min(IDLE_SECONDS, ABSOLUTE_SECONDS)
    with get_db_session() as db:
        db.execute(text("""
            DELETE FROM nexent.user_local_session_t WHERE session_id IN (
                SELECT session_id FROM nexent.user_local_session_t
                WHERE idle_expires_at <= :now ORDER BY idle_expires_at
                LIMIT 32 FOR UPDATE SKIP LOCKED
            )
        """), {"now": now})
        db.execute(text("""
            INSERT INTO nexent.user_local_session_t
                (session_id, user_id, refresh_digest, created_at, last_refreshed_at,
                 idle_expires_at, absolute_expires_at, created_by, updated_by)
            VALUES (:sid, :uid, :digest, :now, :now, :idle, :absolute, :uid, :uid)
        """), {"sid": sid, "uid": user_id, "digest": _digest(refresh), "now": now,
               "idle": idle, "absolute": now + ABSOLUTE_SECONDS})
        return _response(user_id, token_version, sid, refresh, now, min(now + JWT_EXPIRY_SECONDS, idle), idle)


def _verified_claims(access_token: str) -> dict:
    if not JWT_SECRET:
        raise RuntimeError("JWT verification is not configured")
    try:
        claims = decode_session(access_token, key=JWT_SECRET, issuer=JWT_ISSUER)
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Invalid or expired access token") from None
    if (not is_local_session_id(claims.get("sid")) or not isinstance(claims.get("sub"), str)
            or not claims["sub"] or type(claims.get("ver")) is not int
            or type(claims.get("exp")) is not int or claims.get("purpose") or claims.get("scope")):
        raise UnauthorizedError("Invalid local session")
    return claims


def rotate_local_session(access_token: str, refresh_token: str, request_id: str | None) -> dict | None:
    """Rotate or replay credentials, or return None when the session cannot be extended."""
    if not isinstance(refresh_token, str) or not 32 <= len(refresh_token) <= 128:
        raise UnauthorizedError("Invalid refresh token")
    if request_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", request_id):
        raise InvalidRefreshRequestId("Invalid refresh request identifier")

    claims = _verified_claims(access_token)
    sid, uid = claims["sid"], claims["sub"]
    refresh_digest, access_digest = _digest(refresh_token), _digest(access_token)

    with get_db_session() as db:
        version = db.execute(
            select(UserAccount.token_version).where(UserAccount.user_id == uid, UserAccount.delete_flag == "N")
            .with_for_update()
        ).scalar_one_or_none()
        membership = db.execute(select(UserTenant.user_id).where(
            UserTenant.user_id == uid, UserTenant.delete_flag == "N",
        ).limit(1)).scalar()
        if version != claims["ver"] or not membership:
            raise UnauthorizedError("Account or membership is no longer active")

        row = db.execute(text("""
            SELECT * FROM nexent.user_local_session_t
            WHERE session_id = :sid AND user_id = :uid AND delete_flag = 'N' FOR UPDATE
        """), {"sid": sid, "uid": uid}).mappings().one_or_none()
        now = int(time.time())
        if (claims["exp"] <= now or row is None or row["revoked_at"] is not None
                or min(row["idle_expires_at"], row["absolute_expires_at"]) <= now):
            raise UnauthorizedError("Local session has expired or been revoked")

        if not hmac.compare_digest(row["refresh_digest"], refresh_digest):
            if row["retry_until"] and row["retry_until"] > now and hmac.compare_digest(
                row["previous_refresh_digest"], refresh_digest,
            ):
                if (request_id and request_id == row["request_id"]
                        and hmac.compare_digest(row["previous_access_digest"], access_digest)
                        and row["access_expires_at"] > now):
                    refresh = _successor(refresh_token, sid, row["rotation_nonce"])
                    if hmac.compare_digest(_digest(refresh), row["refresh_digest"]):
                        return _response(uid, version, sid, refresh, row["access_issued_at"],
                                         row["access_expires_at"], row["idle_expires_at"])
                raise RefreshConflict("Session refresh was already processed")
            raise UnauthorizedError("Invalid refresh token")

        if claims["exp"] >= row["absolute_expires_at"]:
            return None

        nonce = secrets.token_hex(16)
        replacement = _successor(refresh_token, sid, nonce)
        idle = min(now + IDLE_SECONDS, row["absolute_expires_at"])
        access_exp = min(now + JWT_EXPIRY_SECONDS, idle)
        db.execute(text("""
            UPDATE nexent.user_local_session_t
            SET refresh_digest = :replacement, previous_refresh_digest = :previous_refresh,
                previous_access_digest = :previous_access, request_id = :request_id,
                retry_until = :retry_until, rotation_nonce = :nonce, last_refreshed_at = :now,
                idle_expires_at = :idle, access_issued_at = :now, access_expires_at = :access_exp,
                updated_by = :uid, update_time = timezone('UTC', CURRENT_TIMESTAMP)
            WHERE session_id = :sid
        """), {"replacement": _digest(replacement), "previous_refresh": refresh_digest,
               "previous_access": access_digest, "request_id": request_id, "retry_until": now + RETRY_SECONDS,
               "nonce": nonce, "now": now, "idle": idle, "access_exp": access_exp, "sid": sid, "uid": uid})
        return _response(uid, version, sid, replacement, now, access_exp, idle)
