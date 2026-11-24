# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read the maintenance batch shared by Runtime and Management."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def require_completed_runtime_maintenance(epoch: str) -> datetime:
    """Return the cutoff for a completed batch or reject service startup."""
    try:
        canonical = str(UUID(epoch))
    except ValueError:
        canonical = None
    if canonical != epoch:
        raise ValueError("Runtime maintenance batch must be a canonical UUID")
    with get_db_session() as session:
        completed_at = session.scalar(text("""
            SELECT finished_at
            FROM nexent.execution_reservation_t
            WHERE maintenance_epoch = :epoch
              AND execution_kind = 'maintenance'
              AND service_role = 'runtime'
              AND status = 'COMPLETED'
              AND delete_flag = 'N'
            ORDER BY execution_id DESC
            LIMIT 1
        """), {"epoch": epoch})
    if completed_at is None:
        raise RuntimeError("Runtime does not have a completed maintenance batch")
    return completed_at.replace(tzinfo=timezone.utc)
