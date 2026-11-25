# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Column,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    text,
)


from sqlalchemy.dialects.postgresql import JSONB


from infrastructure.rdb.automation_ownership import (
    AgentAutomationTask as AgentAutomationTask,
    AgentAutomationRun as AgentAutomationRun,
)
from management.db.base import SCHEMA, TableBase


class AgentAutomationProposal(TableBase):
    """Pending automation task proposal created from chat intent."""

    __tablename__ = "agent_automation_proposal_t"
    __table_args__ = (
        Index(
            "idx_agent_automation_proposal_owner",
            "tenant_id",
            "user_id",
            "status",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "uq_agent_automation_proposal_source_message",
            "tenant_id",
            "user_id",
            "source_message_id",
            unique=True,
            postgresql_where=text("delete_flag = 'N' AND source_message_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    proposal_id = Column(BigInteger, Sequence(
        "agent_automation_proposal_t_proposal_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    user_id = Column(String(100), nullable=False, doc="Owner user ID")
    conversation_id = Column(BigInteger, nullable=False, doc="Source conversation ID")
    agent_id = Column(BigInteger, nullable=False, doc="Bound agent ID")
    source_message_id = Column(BigInteger, nullable=True, doc="User message that requested the proposal")
    proposed_task = Column(JSONB, nullable=False, doc="Proposed automation task payload")
    capability_resolution = Column(JSONB, nullable=False, doc="Capability matching result")
    status = Column(String(32), nullable=False, doc="PENDING, ACCEPTED, REJECTED, or EXPIRED")
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False, doc="Proposal expiry time")
