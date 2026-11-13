# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Small execution projections and independently refreshed statistics."""

from typing import ClassVar

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    Column,
    Double,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID

# isort: split
from management.db.base import SCHEMA, TableBase


class TrajectoryExecution(TableBase):
    __tablename__ = "trajectory_execution_t"
    __table_args__ = (
        Index(
            "idx_trajectory_conversation_turn",
            "conversation_id",
            text("turn_no DESC"),
            postgresql_where=text("delete_flag = 'N'"),
        ),
        Index(
            "idx_trajectory_agent_started",
            "agent_id",
            text("started_at DESC"),
            "trajectory_id",
        ),
        Index("idx_trajectory_started", text("started_at DESC"), "trajectory_id"),
        Index("idx_trajectory_models", "models", postgresql_using="gin"),
        {"schema": SCHEMA},
    )
    trajectory_id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        comment="Stable root execution UUID shared with OTLP",
    )
    conversation_id = Column(
        Integer, nullable=False, comment="Existing conversation business identifier"
    )
    turn_no = Column(
        Integer,
        nullable=False,
        comment="Serialized execution order; zero denotes a historical placeholder",
    )
    agent_id = Column(Integer, comment="Actual root Agent for this execution")
    agent_version_no = Column(
        Integer, comment="Captured root Agent version; zero is a draft"
    )
    models = Column(
        ARRAY(String(100)),
        nullable=False,
        server_default=text("'{}'"),
        comment="Distinct physical model names, at most 1000 values",
    )
    status = Column(
        String(30),
        nullable=False,
        comment="Capture availability or terminal business result",
    )
    started_at = Column(
        TIMESTAMP(timezone=True), comment="Observed execution start in UTC"
    )
    finished_at = Column(
        TIMESTAMP(timezone=True), comment="Observed execution finish in UTC"
    )
    duration_ms = Column(
        Double, comment="Root elapsed milliseconds, never a sum of child spans"
    )
    input_tokens = Column(
        BigInteger,
        comment="Input tokens; NULL if any model call has unknown input usage",
    )
    output_tokens = Column(
        BigInteger,
        comment="Output tokens; NULL if any model call has unknown output usage",
    )
    total_tokens = Column(
        BigInteger,
        comment="Total tokens; NULL if any model call has unknown total usage",
    )


class TrajectoryStatistics(TableBase):
    __tablename__ = "trajectory_statistics_t"
    __table_args__: ClassVar[dict] = {"schema": SCHEMA}
    statistics_id = Column(
        UUID(as_uuid=False),
        primary_key=True,
        comment="UUID deterministically derived from scope",
    )
    scope_type = Column(
        String(30), nullable=False, comment="Statistics scope: tenant or global"
    )
    scope_id = Column(
        String(100),
        nullable=False,
        comment="Tenant identifier or global scope identifier",
    )
    conversation_count = Column(
        BigInteger,
        comment="All active conversations including uncaptured conversations",
    )
    execution_count = Column(
        BigInteger, comment="Actual executions excluding turn-zero placeholders"
    )
    duration_sum_ms = Column(
        Double, comment="Sum of known readable root execution durations"
    )
    duration_mean_ms = Column(Double, comment="Mean over known execution durations")
    duration_sample_count = Column(
        BigInteger, comment="Number of valid execution duration samples"
    )
    duration_p50_ms = Column(
        Double, comment="Execution duration percentile 50 with linear interpolation"
    )
    duration_p90_ms = Column(
        Double, comment="Execution duration percentile 90 with linear interpolation"
    )
    duration_p99_ms = Column(
        Double, comment="Execution duration percentile 99 with linear interpolation"
    )
    conversation_duration_p50_ms = Column(
        Double, comment="Percentile 50 of complete per-conversation duration sums"
    )
    conversation_duration_p90_ms = Column(
        Double, comment="Percentile 90 of complete per-conversation duration sums"
    )
    conversation_duration_p99_ms = Column(
        Double, comment="Percentile 99 of complete per-conversation duration sums"
    )
    conversation_duration_sample_count = Column(
        BigInteger, comment="Number of valid conversation duration sums"
    )
    ttft_p50_ms = Column(
        Double, comment="Model first-token percentile 50 from verified OTLP files"
    )
    ttft_p90_ms = Column(
        Double, comment="Model first-token percentile 90 from verified OTLP files"
    )
    ttft_p99_ms = Column(
        Double, comment="Model first-token percentile 99 from verified OTLP files"
    )
    ttft_sample_count = Column(
        BigInteger, comment="Number of valid model TTFT samples including zero"
    )
    computed_at = Column(
        TIMESTAMP(timezone=True),
        comment="Publication time of the last complete snapshot",
    )
    next_refresh_at = Column(
        TIMESTAMP(timezone=True), comment="Next background refresh deadline"
    )
    source_revision = Column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
        comment="Monotonic source change counter",
    )
    computed_revision = Column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
        comment="Source counter used by the published result",
    )
    complete = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="A complete snapshot has been published",
    )
    definition_version = Column(
        Integer,
        nullable=False,
        server_default=text("1"),
        comment="Metric definition revision",
    )
