# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from pydantic import BaseModel, Field, model_validator

_UNAUTHORIZED_MESSAGE = "Authentication required"


class GenerateEvaluatorRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    model_id: int = Field(..., description="LLM model ID to use for generation")
    agent_id: int | None = Field(default=None, description="Optional agent ID for context-aware generation")
    language: str = Field(default="zh", description="Language of the generation prompt: zh / en")


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
                raise ValueError(f"score_range_min ({lo}) must be less than score_range_max ({hi})")
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
