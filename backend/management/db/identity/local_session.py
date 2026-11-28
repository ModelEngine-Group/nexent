# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import UTC, datetime

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def is_local_session_active(session_id: str, user_id: str) -> bool:
    with get_db_session() as db:
        return bool(db.execute(text("""
            SELECT 1 FROM nexent.user_local_session_t
            WHERE session_id = :sid AND user_id = :uid AND revoked_at IS NULL AND delete_flag = 'N'
                AND idle_expires_at > :now AND absolute_expires_at > :now
        """), {"sid": session_id, "uid": user_id, "now": datetime.now(UTC).replace(tzinfo=None)}).scalar())


def revoke_local_session(session_id: str, user_id: str) -> None:
    with get_db_session() as db:
        db.execute(text("""
            UPDATE nexent.user_local_session_t SET revoked_at = :now, updated_by = :uid,
                update_time = :now
            WHERE session_id = :sid AND user_id = :uid AND revoked_at IS NULL AND delete_flag = 'N'
        """), {"sid": session_id, "uid": user_id, "now": datetime.now(UTC).replace(tzinfo=None)})
