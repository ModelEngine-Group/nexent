# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from pydantic import BaseModel, Field


class EvaluationRunRequest(BaseModel):
    """Payload used by config service to dispatch one evaluation run."""

    agent_evaluation_id: int = Field(gt=0)


class TrialRunRequest(BaseModel):
    """Payload used by Config service for a non-persistent trial evaluation."""

    agent_id: int
    agent_version_no: int = 1
    query: str
    judge_model_id: int
    evaluator_ids: list[int] | None = None
    language: str = "zh"
