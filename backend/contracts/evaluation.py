# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any

from pydantic import BaseModel, Field, model_validator
from contracts.constants.constants import _REPORT_LABELS


class CreateEvaluationRequest(BaseModel):
    agent_id: int
    judge_model_id: int
    evaluator_ids: list | None = None
    field_mappings: dict | None = None
    # With-set mode
    evaluation_set_id: int | None = None
    # No-set mode (AI generates test queries)
    agent_version_no: int | None = None
    query_count: int = 10


class AgentEvaluationTrialRunRequest(BaseModel):
    agent_id: int
    agent_version_no: int = 1
    query: str
    judge_model_id: int
    evaluator_ids: list[int] | None = None
    field_mappings: dict[str, Any] | None = None
    language: str = Field(
        default="zh", description="Language of the trial run: zh / en"
    )


class CreateSchemaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    annotation_type: str = Field(default="classification")
    options: list[dict[str, Any]] | None = None


class BatchUpsertRequest(BaseModel):
    annotations: list[dict[str, Any]] = Field(default=[])


class UpdateCaseRequest(BaseModel):
    inputs: dict | None = None
    label: dict | None = None
    session_id: str | None = None
    turn_order: int | None = None


class BatchDeleteRequest(BaseModel):
    case_ids: list[int]


class GenerateCasesRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=1000)
    count: int = Field(default=20, ge=1, le=200)
    model_id: int = Field(...)
    # ES mode: knowledge-base display names. With ENABLE_AIDP_KNOWLEDGE=true:
    # AIDP kds_ids. The backend interprets the values by that env switch.
    knowledge_base_names: list[str] | None = None
    agent_id: int | None = None
    agent_version_no: int | None = None
    set_name: str | None = None
    set_description: str | None = None
    target_set_id: int | None = None


class GenerateEvaluatorRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    model_id: int = Field(..., description="LLM model ID to use for generation")
    agent_id: int | None = Field(
        default=None, description="Optional agent ID for context-aware generation"
    )
    language: str = Field(
        default="zh", description="Language of the generation prompt: zh / en"
    )


class ExportEvaluatorsRequest(BaseModel):
    evaluator_ids: list[int] = Field(..., min_length=1, max_length=100)


class EvaluatorFields(BaseModel):
    """Shared fields for create/update evaluator requests."""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)
    prompt: str | None = Field(default=None, max_length=5_000)
    code: str | None = Field(default=None, max_length=20_000)
    score_range_min: float | None = None
    score_range_max: float | None = None
    pass_threshold: float | None = None
    input_fields: list[dict] | None = None
    model_id: int | None = None

    @model_validator(mode="after")
    def validate_score_range(self):
        import math

        lo, hi, th = self.score_range_min, self.score_range_max, self.pass_threshold
        if lo is not None and hi is not None:
            if any(math.isnan(v) or math.isinf(v) for v in (lo, hi) if v is not None):
                raise ValueError("Score range parameters must not be NaN or Infinity")
            if lo >= hi:
                raise ValueError(
                    f"score_range_min ({lo}) must be less than score_range_max ({hi})"
                )
            if th is not None and (th < lo or th > hi):
                raise ValueError(
                    f"pass_threshold ({th}) must be between score_range_min ({lo}) and score_range_max ({hi})"
                )
        if hi is not None and hi > 100.0:
            raise ValueError(f"score_range_max must not exceed 100, got {hi}")
        return self


class CreateEvaluatorRequest(EvaluatorFields):
    name: str = Field(..., min_length=1, max_length=50)  # type: ignore[assignment]
    evaluator_type: str = Field(default="llm")


class UpdateEvaluatorRequest(EvaluatorFields):
    """All fields optional — only supplied fields are updated."""


class EvaluationRunRequest(BaseModel):
    """Payload used by config service to dispatch one evaluation run."""

    agent_evaluation_id: int = Field(gt=0)


class RuntimeEvaluationTrialRunRequest(BaseModel):
    """Payload used by Config service for a non-persistent trial evaluation."""

    agent_id: int
    agent_version_no: int = 1
    query: str
    judge_model_id: int
    evaluator_ids: list[int] | None = None
    language: str = "zh"


def get_report_labels(language: str = "zh") -> dict:
    """Return the label dict for the given language. Falls back to 'zh'."""
    return _REPORT_LABELS.get(language, _REPORT_LABELS["zh"])


# Evaluation status constants.
class EvalRunStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvalCaseStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvalPassStatus:
    PASS = "pass"
    FAIL = "fail"
