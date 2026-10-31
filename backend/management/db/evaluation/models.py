# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    Sequence,
    String,
    Text,
)


from sqlalchemy.dialects.postgresql import JSONB


from management.db.base import SCHEMA, TableBase, _PRIMARY_KEY_DOC, _TENANT_ID_DOC


class EvaluationSet(TableBase):
    """Evaluation set metadata."""

    __tablename__ = "evaluation_set_t"
    __table_args__ = {"schema": SCHEMA}

    evaluation_set_id = Column(
        BigInteger,
        Sequence("evaluation_set_t_evaluation_set_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc=_PRIMARY_KEY_DOC,
    )

    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    name = Column(String(255), nullable=False, doc="Evaluation set name")
    description = Column(Text, doc="Evaluation set description")

    source_filename = Column(String(255), doc="Original uploaded filename")
    case_count = Column(Integer, default=0, doc="Total number of cases")
    generation_status = Column(String(20), default="IDLE", doc="IDLE / GENERATING / DONE / FAILED")
    generation_progress = Column(Integer, default=0, doc="Generation progress 0-100")

    __table_args__ = (
        Index("ix_eval_set_tenant_id", "tenant_id"),
        Index("ix_eval_set_name", "tenant_id", "name"),
        {"schema": SCHEMA},
    )


class EvaluationSetCase(TableBase):
    """Evaluation cases belonging to a set."""

    __tablename__ = "evaluation_set_case_t"
    __table_args__ = {"schema": SCHEMA}

    evaluation_set_case_id = Column(
        BigInteger,
        Sequence("evaluation_set_case_t_evaluation_set_case_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
        doc=_PRIMARY_KEY_DOC,
    )

    tenant_id = Column(String(100), nullable=False, doc=_TENANT_ID_DOC)
    evaluation_set_id = Column(BigInteger, nullable=False, doc="Evaluation set id")

    case_id = Column(String(128), doc="External case_id from JSONL (optional)")

    inputs = Column(JSONB, nullable=False, doc="Case inputs JSON")
    label = Column(JSONB, nullable=False, doc="Case label JSON")

    order_no = Column(Integer, default=0, doc="Case order in the set")
    session_id = Column(String(128), nullable=True, doc="Multi-turn session identifier")
    turn_order = Column(Integer, default=0, doc="Turn order within a session (1-based)")

    __table_args__ = (
        Index("ix_eval_set_case_set_id", "evaluation_set_id"),
        Index("ix_eval_set_case_tenant_id", "tenant_id"),
        {"schema": SCHEMA},
    )


class Evaluator(TableBase):
    """Evaluator definition for agent evaluation tasks."""

    __tablename__ = "evaluator_t"
    __table_args__ = (
        Index("ix_evaluator_tenant", "tenant_id", "delete_flag"),
        Index("ix_evaluator_status", "tenant_id", "status", "delete_flag"),
        {"schema": SCHEMA},
    )

    evaluator_id = Column(
        BigInteger,
        Sequence("evaluator_t_evaluator_id_seq", schema=SCHEMA),
        primary_key=True,
        nullable=False,
    )
    tenant_id = Column(String(100), nullable=False, default="", doc="Tenant ID; empty = system builtin")
    name = Column(String(255), nullable=False, doc="Evaluator name (zh)")
    description = Column(Text, doc="Evaluator description (zh)")
    name_en = Column(String(255), doc="Evaluator name (en)")
    description_en = Column(Text, doc="Evaluator description (en)")
    evaluator_type = Column(String(20), nullable=False, default="llm", doc="llm / code")
    source = Column(String(20), nullable=False, default="custom", doc="builtin / custom")
    prompt = Column(Text, doc="LLM evaluator prompt template (zh)")
    code = Column(Text, doc="Code/runtime evaluator Python function")
    score_range_min = Column(Float, default=0.0)
    score_range_max = Column(Float, default=1.0)
    pass_threshold = Column(Float, default=0.5, doc="Score >= threshold = pass")
    input_fields = Column(JSONB, nullable=False, default=[], doc='[{name, type, required}]')
    status = Column(String(20), nullable=False, default="DRAFT", doc="DRAFT / PUBLISHED")
    version_no = Column(Integer, nullable=False, default=1)
    version_group_id = Column(BigInteger, doc="Groups versions of the same evaluator; NULL until first publish")
    is_current = Column(Boolean, default=True, doc="True if this is the current active version")
    model_id = Column(Integer, doc="LLM model ID; NULL = use task-level judge")


class EvaluationAnnotationSchema(TableBase):
    """Label/annotation template for evaluation cases."""

    __tablename__ = "evaluation_annotation_schema_t"
    __table_args__ = {"schema": SCHEMA}

    schema_id = Column(BigInteger, Sequence("evaluation_annotation_schema_t_schema_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, default="")
    name = Column(String(50), nullable=False)
    description = Column(String(200))
    annotation_type = Column(String(20), nullable=False, default="classification", doc="classification/boolean/number/text")
    options = Column(JSONB, doc="For classification: [{\"label\":\"正确\"},...]")


class EvaluationAnnotation(TableBase):
    """Single annotation value for an evaluation case."""

    __tablename__ = "evaluation_annotation_t"
    __table_args__ = {"schema": SCHEMA}

    annotation_id = Column(BigInteger, Sequence("evaluation_annotation_t_annotation_id_seq", schema=SCHEMA), primary_key=True, nullable=False)
    tenant_id = Column(String(100), nullable=False, default="")
    agent_evaluation_id = Column(BigInteger, nullable=True, doc="Denormalized for efficient cascade-delete")
    case_id = Column(BigInteger, nullable=False)
    schema_id = Column(BigInteger, nullable=False)
    value = Column(Text)


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
