# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ProviderConfigCreate(BaseModel):
    provider_name: str
    connection_type: Literal["plugin"] = "plugin"
    enabled: bool = False
    timeout_seconds: int = 30
    params: Dict[str, str] = Field(
        ..., description="EAV params, e.g. {'plugin.name': 'mem0', 'plugin.api_key': '...'}"
    )


class ProviderConfigUpdate(BaseModel):
    provider_name: Optional[str] = None
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = None
    params: Optional[Dict[str, str]] = None


class TestSearchRequest(BaseModel):
    query: str
    top_k: int = 5


class TestIngestRequest(BaseModel):
    units: List[Dict[str, Any]] = Field(..., description="List of MemoryIngestUnit dicts")
