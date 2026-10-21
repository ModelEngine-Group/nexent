# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Annotated, Any, Dict
from pydantic import BaseModel, Field


class A2AServerSettings(BaseModel):
    """A2A Server settings for an agent."""

    model_config = {"extra": "forbid"}

    is_enabled: Annotated[bool | None, Field(strict=True)] = False
    card_overrides: Dict[str, Any] | None = None


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request payload."""

    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] | None = {}
    id: Any | None = None
