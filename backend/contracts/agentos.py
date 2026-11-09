# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral AgentOS v1 transport and transitional Agent request shapes."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, JsonValue, PositiveInt

NAMESPACE = "/internal/agentos/"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
PRINCIPAL_KEY = "nexent.agentos.principal"
BODY_KEY = "nexent.agentos.body"


class CompatibilityOperation(str, Enum):
    RUN = NAMESPACE + "v1/compat/agent/run"
    STOP = NAMESPACE + "v1/compat/agent/stop"


class CompatibilityRun(BaseModel):
    """Carry the current AgentRequest until Runtime accepts resolved resources."""

    model_config = ConfigDict(extra="forbid")
    request: dict[str, JsonValue]


class CompatibilityStop(BaseModel):
    """Keep the existing conversation-scoped cancellation contract."""

    model_config = ConfigDict(extra="forbid", strict=True)
    conversation_id: PositiveInt
