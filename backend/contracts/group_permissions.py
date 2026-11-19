# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GroupPermission(BaseModel):
    """One direct group grant on a resource."""

    model_config = ConfigDict(extra="forbid")

    group_id: int = Field(gt=0, strict=True)
    permission: Literal["READ_ONLY", "EDIT"]
