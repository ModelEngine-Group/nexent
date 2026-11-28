# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""API-key usage ledger: shared table model and writer.

The usage ledger backs the northbound accounting that every service exposing
``/nb`` routes performs, so the model and the writer live in the shared
storage adapter layer (same home as the account records) instead of a single
service's tree. Moved verbatim from ``management/db/identity/models.py`` and
``management/db/identity/token.py``; the old locations re-export these names
so existing management call sites keep working. One definition, one table.
"""

from typing import Any, Dict, Optional

from sqlalchemy import Column, Index, Integer, Sequence, String, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.rdb.base import SCHEMA, TableBase

# Resolved lazily on first write: importing the model registry must not open
# the shared database client (pinned by test_api_db_directory_architecture),
# while the module-level name stays patchable for tests.
get_db_session = None


def _resolve_session_factory():
    global get_db_session
    if get_db_session is None:
        from infrastructure.rdb.client import get_db_session as factory

        get_db_session = factory
    return get_db_session


class UserTokenUsageLog(TableBase):
    """
    User token usage log table
    """
    __tablename__ = "user_token_usage_log_t"
    __table_args__ = (
        Index(
            "ix_user_token_usage_active_token_time",
            "token_id",
            text("create_time DESC"),
            postgresql_include=["token_usage_id"],
            postgresql_where=text("delete_flag = 'N'"),
        ),
        {"schema": SCHEMA},
    )

    token_usage_id = Column(Integer, Sequence("user_token_usage_log_t_token_usage_id_seq", schema=SCHEMA),
                            primary_key=True, nullable=False, doc="Token usage log ID, unique primary key")
    token_id = Column(Integer, nullable=False,
                      doc="Foreign key to user_token_info_t.token_id")
    call_function_name = Column(
        String(100), doc="API function name being called")
    related_id = Column(
        Integer, doc="Related resource ID (e.g., conversation_id)")
    meta_data = Column(
        JSONB, doc="Additional metadata for this usage log entry, stored as JSON")


def log_token_usage(
    token_id: int,
    call_function_name: str,
    related_id: Optional[int],
    created_by: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """Log token usage to the database.

    Args:
        token_id: The token ID used.
        call_function_name: The API function name being called.
        related_id: Related resource ID (e.g., conversation_id).
        created_by: User ID who initiated the call.
        metadata: Optional additional metadata for this usage log entry.

    Returns:
        The created token_usage_id.
    """
    with _resolve_session_factory()() as session:
        usage_log = UserTokenUsageLog(
            token_id=token_id,
            call_function_name=call_function_name,
            related_id=related_id,
            created_by=created_by,
            meta_data=metadata,
        )
        session.add(usage_log)
        session.flush()
        return usage_log.token_usage_id
