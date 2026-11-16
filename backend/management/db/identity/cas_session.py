# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Database operations for CAS-backed web sessions.
"""

from contracts.constants.constants import CAS_SESSION_ACTIVE, CAS_SESSION_REVOKED
from datetime import datetime
from typing import Any, Dict, Optional

from management.utils.orm import as_dict
from management.db.client import get_db_session
from management.db.models import UserCasSession


def create_cas_session(
    *,
    session_id: str,
    user_id: str,
    cas_user_id: str,
    expires_at: datetime,
    cas_session_index: Optional[str] = None,
) -> Dict[str, Any]:
    with get_db_session() as session:
        record = UserCasSession(
            session_id=session_id,
            user_id=user_id,
            cas_user_id=cas_user_id,
            cas_session_index=cas_session_index,
            status=CAS_SESSION_ACTIVE,
            expires_at=expires_at,
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(record)
        session.flush()
        return as_dict(record)


def get_cas_session_by_session_id(session_id: str) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    with get_db_session() as session:
        result = (
            session.query(UserCasSession)
            .filter(
                UserCasSession.session_id == session_id,
                UserCasSession.delete_flag == "N",
            )
            .first()
        )
        return as_dict(result) if result else None


def is_cas_session_active(session_id: str) -> bool:
    if not session_id:
        return False
    with get_db_session() as session:
        result = (
            session.query(UserCasSession)
            .filter(
                UserCasSession.session_id == session_id,
                UserCasSession.status == CAS_SESSION_ACTIVE,
                UserCasSession.expires_at > datetime.now(),
                UserCasSession.delete_flag == "N",
            )
            .first()
        )
        return result is not None


def revoke_cas_session_by_session_id(session_id: str, actor: str = "cas") -> int:
    if not session_id:
        return 0
    with get_db_session() as session:
        result = (
            session.query(UserCasSession)
            .filter(
                UserCasSession.session_id == session_id,
                UserCasSession.status == CAS_SESSION_ACTIVE,
                UserCasSession.delete_flag == "N",
            )
            .update(
                {
                    "status": CAS_SESSION_REVOKED,
                    "revoked_at": datetime.now(),
                    "updated_by": actor,
                }
            )
        )
        return result


def revoke_cas_sessions_by_user_id(cas_user_id: str, actor: str = "cas") -> int:
    if not cas_user_id:
        return 0
    with get_db_session() as session:
        result = (
            session.query(UserCasSession)
            .filter(
                UserCasSession.cas_user_id == cas_user_id,
                UserCasSession.status == CAS_SESSION_ACTIVE,
                UserCasSession.delete_flag == "N",
            )
            .update(
                {
                    "status": CAS_SESSION_REVOKED,
                    "revoked_at": datetime.now(),
                    "updated_by": actor,
                }
            )
        )
        return result


def revoke_cas_session_by_index(cas_session_index: str, actor: str = "cas") -> int:
    if not cas_session_index:
        return 0
    with get_db_session() as session:
        result = (
            session.query(UserCasSession)
            .filter(
                UserCasSession.cas_session_index == cas_session_index,
                UserCasSession.status == CAS_SESSION_ACTIVE,
                UserCasSession.delete_flag == "N",
            )
            .update(
                {
                    "status": CAS_SESSION_REVOKED,
                    "revoked_at": datetime.now(),
                    "updated_by": actor,
                }
            )
        )
        return result
