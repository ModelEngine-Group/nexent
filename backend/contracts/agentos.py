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
    BACKGROUND = NAMESPACE + "v1/compat/agent/background"
    INSPECT = NAMESPACE + "v1/compat/agent/inspect"
    EVALUATION_CASE = NAMESPACE + "v1/compat/agent/evaluation-case"


class CompatibilityRun(BaseModel):
    """Carry the current AgentRequest until Runtime accepts resolved resources."""

    model_config = ConfigDict(extra="forbid")
    request: dict[str, JsonValue]


class CompatibilityStop(BaseModel):
    """Keep the existing conversation-scoped cancellation contract."""

    model_config = ConfigDict(extra="forbid", strict=True)
    conversation_id: PositiveInt


class BackgroundAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    conversation_id: PositiveInt
    assistant_message_id: PositiveInt | None
    chunks: int = Field(ge=0)


class AgentRunningState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    running: bool


class EvaluationAgentRun(BaseModel):
    """Execute one synthetic evaluation case without a persisted conversation."""

    model_config = ConfigDict(extra="forbid", strict=True)
    agent_id: PositiveInt
    version_no: Annotated[int, Field(ge=0)]
    query: str
    history: list[dict[str, JsonValue]] | None = None
    conversation_id: Annotated[int, Field(le=0)] = 0


class AgentOperation(str, Enum):
    EVALUATION_CASE = NAMESPACE + "v1/agent/evaluation-case"


class RunSpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ToolBinding(RunSpecModel):
    tool_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    credential_ref: str | None = None


class RunModelBinding(RunSpecModel):
    model_id: PositiveInt
    alias: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class ModelBindings(RunSpecModel):
    llm: RunModelBinding
    summary: RunModelBinding | None = None
    verifier: RunModelBinding | None = None
    embedding: RunModelBinding | None = None
    rerank: RunModelBinding | None = None


class RunHistoryMessage(RunSpecModel):
    role: Literal["user", "assistant"]
    content: str


class RunInput(RunSpecModel):
    query: str
    history: list[RunHistoryMessage] = Field(default_factory=list)
    attachment_refs: list[str] = Field(default_factory=list)


class AgentResource(RunSpecModel):
    agent_id: PositiveInt
    version_no: Annotated[int, Field(ge=0)]
    name: str = Field(min_length=1)
    description: str
    prompt_templates: dict[str, JsonValue]
    max_steps: PositiveInt = 15
    tools: list[ToolBinding] = Field(default_factory=list)
    skill_refs: list[str] = Field(default_factory=list)
    mcp_server_refs: list[str] = Field(default_factory=list)
    knowledge_base_refs: list[str] = Field(default_factory=list)
    memory_ref: str | None = None
    subagents: list["AgentResource"] = Field(default_factory=list)
    sandbox_policy: dict[str, JsonValue] | None = None


class AgentRunSpec(RunSpecModel):
    mode: Literal["nexent"]
    resource: AgentResource
    models: ModelBindings
    input: RunInput
    language: Literal["zh", "en"] = "zh"


class PreparedEvaluationRun(AgentRunSpec):
    """Execute an authorized resource snapshot under a synthetic evaluation key."""

    conversation_id: Annotated[int, Field(le=0)] = 0


class EvaluationAgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str
    events: list[dict[str, JsonValue]]


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


AgentOSOperation = CompatibilityOperation | AgentOperation | ModelOperation | ModelAdministrationOperation
OPERATIONS_BY_PATH: dict[str, AgentOSOperation] = {
    operation.value: operation
    for operations in (CompatibilityOperation, AgentOperation, ModelOperation, ModelAdministrationOperation)
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
    max_output_tokens: PositiveInt | None = None


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
