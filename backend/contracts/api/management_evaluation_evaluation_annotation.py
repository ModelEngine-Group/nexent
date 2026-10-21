# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any
from pydantic import BaseModel, Field


class CreateSchemaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    annotation_type: str = Field(default="classification")
    options: list[dict[str, Any]] | None = None


class BatchUpsertRequest(BaseModel):
    annotations: list[dict[str, Any]] = Field(default=[])
