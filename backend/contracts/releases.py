# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from pydantic import BaseModel, ConfigDict, Field


def supports_release(candidate_type, components=None):
    single = {"prompt", "tool_set", "tool_mapping", "skill_step", "skill_discovery", "skill_new", "skill_script"}
    if candidate_type == "combination":
        return len(components or []) == 2 and all(
            part["candidate_type"] in {"prompt", "tool_set", "skill_step", "skill_discovery"} for part in components
        )
    return candidate_type in single


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1200)


class PromotionRequest(ReleaseRequest):
    candidate_digest: str = Field(pattern="^[0-9a-f]{64}$")


class RollbackRequest(ReleaseRequest):
    emergency: bool = False
