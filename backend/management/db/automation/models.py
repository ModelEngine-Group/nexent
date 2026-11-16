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


from management.db.base import SCHEMA, TableBase


class AgentAutomationTask(TableBase):
    """User-managed scheduled automation task bound to one conversation."""

    __tablename__ = "agent_automation_task_t"
    __table_args__ = (
        Index(
            "idx_agent_automation_due",
            "status",
            "next_fire_at",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "idx_agent_automation_owner",
            "tenant_id",
            "user_id",
            "status",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "uq_agent_automation_conversation_active",
            "conversation_id",
            unique=True,
            postgresql_where=text("delete_flag = 'N' AND status <> 'DELETED'"),
        ),
        {"schema": SCHEMA},
    )

    task_id = Column(BigInteger, Sequence(
        "agent_automation_task_t_task_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    user_id = Column(String(100), nullable=False, doc="Owner user ID")
    conversation_id = Column(BigInteger, nullable=False, doc="Bound conversation ID")
    agent_id = Column(BigInteger, nullable=False, doc="Bound agent ID")
    agent_version_no = Column(Integer, nullable=True, doc="Pinned agent version")
    title = Column(String(255), nullable=False, doc="Task title")
    instruction = Column(Text, nullable=False, doc="Base instruction for every automation run")
    status = Column(String(32), nullable=False, doc="Task lifecycle status")
    source = Column(String(32), nullable=False, doc="Creation source")
    schedule_mode = Column(String(16), nullable=False, doc="ONCE or RECURRING")
    schedule_rule_type = Column(String(16), nullable=False, doc="AT, INTERVAL, or CRON")
    schedule_expr = Column(Text, nullable=True, doc="Display schedule expression")
    schedule_config = Column(JSONB, nullable=False, doc="Normalized ScheduleTrigger payload")
    capability_requirements = Column(JSONB, doc="Capability requirements parsed from user intent")
    capability_bindings = Column(JSONB, doc="Confirmed matched capabilities")
    runtime_snapshot = Column(JSONB, doc="Agent/runtime capability snapshot at creation time")
    timezone = Column(String(64), nullable=False, doc="IANA timezone")
    next_fire_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Next scheduled fire time")
    last_fire_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Last scheduled fire time")
    fire_count = Column(Integer, default=0, nullable=False, doc="Number of scheduled fires")
    last_run_status = Column(String(32), nullable=True, doc="Latest run status")
    last_error = Column(Text, nullable=True, doc="Latest run error")
    consecutive_failures = Column(Integer, default=0, nullable=False, doc="Consecutive failure count")
    timeout_seconds = Column(Integer, nullable=False, doc="Single-run timeout")
    overlap_policy = Column(String(16), nullable=False, doc="Overlap policy")
    misfire_policy = Column(String(16), nullable=False, doc="Misfire policy")
    lock_owner = Column(String(128), nullable=True, doc="Scheduler lease owner")
    lock_until = Column(TIMESTAMP(timezone=True), nullable=True, doc="Scheduler lease expiry")


class AgentAutomationRun(TableBase):
    """Execution history for an automation task fire."""

    __tablename__ = "agent_automation_run_t"
    __table_args__ = (
        Index(
            "idx_agent_automation_run_task",
            "task_id",
            "scheduled_fire_at",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "idx_agent_automation_run_conversation",
            "conversation_id",
            "status",
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "uq_agent_automation_active_occurrence",
            "task_id",
            "scheduled_fire_at",
            unique=True,
            postgresql_where=text(
                "delete_flag = 'N' AND trigger_type = 'SCHEDULED' "
                "AND status IN ('QUEUED', 'RUNNING')"
            ),
        ),
        {"schema": SCHEMA},
    )

    run_id = Column(BigInteger, Sequence(
        "agent_automation_run_t_run_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    task_id = Column(BigInteger, nullable=False, doc="Automation task ID")
    tenant_id = Column(String(100), nullable=False, doc="Tenant ID")
    user_id = Column(String(100), nullable=False, doc="Owner user ID")
    conversation_id = Column(BigInteger, nullable=False, doc="Bound conversation ID")
    scheduled_fire_at = Column(TIMESTAMP(timezone=True), nullable=False, doc="Scheduled fire time")
    actual_fire_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Actual fire time")
    trigger_type = Column(String(32), nullable=False, doc="SCHEDULED or MANUAL")
    status = Column(String(32), nullable=False, doc="Run lifecycle status")
    generated_prompt = Column(Text, nullable=True, doc="Prompt appended to the conversation")
    user_message_id = Column(BigInteger, nullable=True, doc="Automation user message ID")
    assistant_message_id = Column(BigInteger, nullable=True, doc="Assistant message ID")
    started_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Run start time")
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True, doc="Run finish time")
    duration_ms = Column(BigInteger, nullable=True, doc="Run duration in milliseconds")
    error_code = Column(String(64), nullable=True, doc="Automation error code")
    error_message = Column(Text, nullable=True, doc="Automation error message")


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
