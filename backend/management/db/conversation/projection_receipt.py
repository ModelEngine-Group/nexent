# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Replay records committed atomically with assistant message projections."""

import hashlib
import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Column, Integer, String, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.rdb.base import SCHEMA, TableBase


class ConversationProjectionReceipt(TableBase):
    __tablename__ = "conversation_projection_receipt_t"
    __table_args__ = {"schema": SCHEMA}

    run_id = Column(String(32), primary_key=True, doc="Server-issued AgentOS run identifier.")
    message_id = Column(Integer, nullable=False, doc="Assistant message finalized by the run.")
    tenant_id = Column(String(100), nullable=False, doc="Tenant of the authorized projection actor.")
    payload_sha256 = Column(String(64), nullable=False, doc="Versioned digest of the submitted projection.")
    unit_ids = Column(JSONB, nullable=False, doc="Mapping of unit indexes to persisted unit identifiers.")


def find_projection_receipts(session, run_id: str, message_id: int):
    receipt = ConversationProjectionReceipt
    return session.scalars(
        select(receipt).where(
            or_(receipt.run_id == run_id, receipt.message_id == message_id),
            receipt.delete_flag == "N",
        )
    ).all()



def _json_value(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    raise TypeError(f"Unsupported assistant projection value: {type(value).__name__}")


def projection_payload_digest(payload: dict) -> str:
    """Hash a canonical representation without storing the message twice."""
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_value,
    ).encode("utf-8")
    return hashlib.sha256(b"assistant-projection-v1\0" + encoded).hexdigest()
