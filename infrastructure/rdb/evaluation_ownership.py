# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Table mappings used for exact Runtime ownership recovery."""

from sqlalchemy import BigInteger, Column, Float, Index, Integer, Sequence, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.rdb.base import SCHEMA, TableBase

_PRIMARY_KEY_DOC = "Primary key, auto-increment"
_TENANT_ID_DOC = "Tenant ID for multi-tenancy isolation"


class AgentEvaluation(TableBase):
    """An evaluation run for a specific agent and evaluation set."""

    __tablename__ = "agent_evaluation_t"
    __table_args__ = {"schema": SCHEMA}

    agent_evaluation_id = Column(
        BigInteger,
        Sequence("agent_evaluation_t_agent_evaluation_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc=_PRIMARY_KEY_DOC,
    )

    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    agent_id = Column(Integer, nullable=False, doc="Agent id")
    agent_version_no = Column(Integer, nullable=False, doc="Published agent version_no used for evaluation")

    evaluation_set_id = Column(BigInteger, nullable=False, doc="Evaluation set id")

    status = Column(
        String(30),
        nullable=False,
        default="PENDING",
        doc="Run status: PENDING/RUNNING/COMPLETED/FAILED",
    )

    progress_total = Column(Integer, default=0, doc="Total cases")
    progress_done = Column(Integer, default=0, doc="Completed cases")

    judge_model_id = Column(
        Integer,
        doc=(
            "Model id used by the judge. Persisted so the background worker can "
            "recover it after restart and the frontend can resolve judge_model_name."
        ),
    )

    score_overall = Column(Float, doc="Overall score (0-1)")

    error_message = Column(Text, doc="Failure reason")
    pass_count = Column(Integer, default=0, doc="Number of passed cases")
    fail_count = Column(Integer, default=0, doc="Number of failed cases")
    evaluator_config = Column(JSONB, doc="Multi-evaluator config: {evaluator_ids, field_mappings}")
    analysis_report = Column(JSONB, doc="AI-generated analysis report")
    annotation_schema_ids = Column(JSONB, default=[], doc="Enabled annotation schema IDs")

    __table_args__ = (
        Index("ix_agent_eval_tenant_id", "tenant_id"),
        Index("ix_agent_eval_agent_id", "tenant_id", "agent_id"),
        Index("ix_agent_eval_set_id", "tenant_id", "evaluation_set_id"),
        Index("ix_agent_eval_judge_model_id", "tenant_id", "judge_model_id"),
        {"schema": SCHEMA},
    )


class AgentEvaluationCase(TableBase):
    """Per-case evaluation details within an evaluation run."""

    __tablename__ = "agent_evaluation_case_t"
    __table_args__ = {"schema": SCHEMA}

    agent_evaluation_case_id = Column(
        BigInteger,
        Sequence("agent_evaluation_case_t_agent_evaluation_case_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc=_PRIMARY_KEY_DOC,
    )

    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)

    agent_evaluation_id = Column(BigInteger, nullable=False, doc="Evaluation run id")
    evaluation_set_case_id = Column(BigInteger, nullable=False, doc="Evaluation set case id")

    inputs = Column(JSONB, nullable=False, doc="Case inputs snapshot (query only for pass cases)")
    label = Column(JSONB, nullable=False, doc="Case label snapshot (cleared to {answer:''} for pass cases)")
    predict = Column(JSONB, doc="Predict JSON (answer/raw); NULL for pass cases")

    score = Column(JSONB, doc="Case score (float or dict for multi-evaluator)")
    reason = Column(Text, doc="Judge reason; NULL for pass cases")
    pass_status = Column(
        String(16),
        doc="Judge result: pass / fail. Pass cases have predict/reason/label.answer cleared to save space.",
    )

    status = Column(
        String(30),
        nullable=False,
        default="PENDING",
        doc="Case status: PENDING/RUNNING/COMPLETED/FAILED",
    )
    error_message = Column(Text, doc="Per-case failure reason")
    session_id = Column(String(128), nullable=True, doc="Multi-turn session identifier")
    turn_order = Column(Integer, default=0, doc="Turn order within a session (0-indexed)")

    __table_args__ = (
        Index("ix_agent_eval_case_eval_id", "agent_evaluation_id"),
        Index("ix_agent_eval_case_tenant_id", "tenant_id"),
        Index("ix_agent_eval_case_pass_status", "tenant_id", "agent_evaluation_id", "pass_status"),
        {"schema": SCHEMA},
    )
