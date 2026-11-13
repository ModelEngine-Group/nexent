# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Immutable submission snapshots with independent publication results."""

from management.db.base import SCHEMA, TableBase
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB


class ResourceReview(TableBase):
    __tablename__ = "ag_resource_review_t"
    __table_args__ = (
        CheckConstraint("resource_type IN ('agent','skill','mcp')"),
        CheckConstraint("review_status IN ('pending_review','approved','rejected')"),
        CheckConstraint(
            "(resource_type = 'agent' AND version_no IS NOT NULL AND version_no >= 0) OR "
            "(resource_type <> 'agent' AND version_no IS NULL)"
        ),
        {"schema": SCHEMA},
    )

    review_id = Column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Independent submission identifier",
    )
    tenant_id = Column(String(100), nullable=False, comment="Resource owner tenant")
    resource_type = Column(
        String(30), nullable=False, comment="Resource kind: agent, skill or mcp"
    )
    source_resource_id = Column(
        BigInteger, nullable=False, comment="Original local resource identifier"
    )
    version_no = Column(Integer, comment="Agent version; NULL for Skill and MCP")
    repository_id = Column(
        BigInteger,
        comment="Published repository identifier; NULL before first publication",
    )
    submitted_user_id = Column(
        String(100),
        nullable=False,
        comment="Authenticated submitter internal user identifier",
    )
    submitted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Submission instant; legacy submissions use original update time",
    )
    submit_description = Column(
        Text, comment="Description supplied with this submission"
    )
    resource_snapshot = Column(
        JSONB, nullable=False, comment="Versioned validated frozen publication payload"
    )
    review_status = Column(
        String(30),
        nullable=False,
        default="pending_review",
        comment="Independent review status: pending_review, approved or rejected",
    )
    review_comment = Column(Text, comment="Final review opinion")
    reviewed_by = Column(String(100), comment="Decision actor internal user identifier")
    reviewed_at = Column(
        DateTime(timezone=True),
        comment="Decision instant; publication instant for approvals",
    )
