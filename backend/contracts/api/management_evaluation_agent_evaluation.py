# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any
from pydantic import BaseModel, Field


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


class TrialRunRequest(BaseModel):
    agent_id: int
    agent_version_no: int = 1
    query: str
    judge_model_id: int
    evaluator_ids: list[int] | None = None
    field_mappings: dict[str, Any] | None = None
    language: str = Field(default="zh", description="Language of the trial run: zh / en")


_AUTH_REQUIRED_MSG = "Authentication required"


_UNKNOWN_ID = "<unknown>"
