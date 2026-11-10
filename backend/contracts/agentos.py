# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral AgentOS v1 transport and transitional Agent request shapes."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, PositiveInt

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


class ModelOperation(str, Enum):
    GET = NAMESPACE + "v1/model/get"
    INVOKE = NAMESPACE + "v1/model/invoke"


class ModelAdministrationOperation(str, Enum):
    REGISTER = NAMESPACE + "v1/model/register"
    UPDATE = NAMESPACE + "v1/model/update"
    DEACTIVATE = NAMESPACE + "v1/model/deactivate"
    DEACTIVATE_TENANT = NAMESPACE + "v1/model/deactivate-tenant"
    IMPORT = NAMESPACE + "v1/model/provider-import"
    BATCH_UPDATE = NAMESPACE + "v1/model/batch-update"
    DISCOVER = NAMESPACE + "v1/model/provider-discover"
    LIST_PROVIDER = NAMESPACE + "v1/model/provider-list"
    HEALTHCHECK = NAMESPACE + "v1/model/healthcheck"
    PROBE = NAMESPACE + "v1/model/probe"


AgentOSOperation = CompatibilityOperation | ModelOperation | ModelAdministrationOperation
OPERATIONS_BY_PATH: dict[str, AgentOSOperation] = {
    operation.value: operation
    for operations in (CompatibilityOperation, ModelOperation, ModelAdministrationOperation)
    for operation in operations
}


class ModelReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_id: PositiveInt


class ModelInvokeBase(ModelReference):
    expected_revision: str | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["system", "user", "assistant"]
    content: str


class ChatOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    top_p: Annotated[float, Field(ge=0, le=1)] | None = None


class ChatInvocation(ModelInvokeBase):
    operation: Literal["chat"] = "chat"
    input: Annotated[list[ChatMessage], Field(min_length=1)]
    options: ChatOptions | None = None


class EmbeddingInvocation(ModelInvokeBase):
    operation: Literal["embedding"] = "embedding"
    input: Annotated[list[str], Field(min_length=1)]


class RerankInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str
    documents: Annotated[list[str], Field(min_length=1)]


class RerankOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    top_n: PositiveInt | None = None


class RerankInvocation(ModelInvokeBase):
    operation: Literal["rerank"] = "rerank"
    input: RerankInput
    options: RerankOptions | None = None


ModelInvocation = Annotated[
    ChatInvocation | EmbeddingInvocation | RerankInvocation,
    Field(discriminator="operation"),
]


class ModelMetadata(ModelReference):
    model_type: str
    display_name: str | None
    revision: str
    profile_version: str | None = None


class ModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: str
    output: JsonValue
