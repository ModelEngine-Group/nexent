# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from pydantic import BaseModel, Field


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
