# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from pydantic import BaseModel, ConfigDict, Field


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1200)


class PromotionRequest(ReleaseRequest):
    candidate_digest: str = Field(pattern="^[0-9a-f]{64}$")


class RollbackRequest(ReleaseRequest):
    emergency: bool = False
