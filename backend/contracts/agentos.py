# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral AgentOS v1 transport and transitional Agent request shapes."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, PositiveInt, model_serializer

NAMESPACE = "/internal/agentos/"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
PRINCIPAL_KEY = "nexent.agentos.principal"
BODY_KEY = "nexent.agentos.body"
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class CompatibilityOperation(str, Enum):
    RUN = NAMESPACE + "v1/compat/agent/run"
    CONVERSATION_RUN = NAMESPACE + "v1/compat/agent/conversation-run"
    STOP = NAMESPACE + "v1/compat/agent/stop"
    BACKGROUND = NAMESPACE + "v1/compat/agent/background"
    INSPECT = NAMESPACE + "v1/compat/agent/inspect"
    EVALUATION_CASE = NAMESPACE + "v1/compat/agent/evaluation-case"
    DEBUG_STOP = NAMESPACE + "v1/compat/agent/debug-stop"


class CompatibilityRun(BaseModel):
    """Carry the current AgentRequest until Runtime accepts resolved resources."""

    model_config = ConfigDict(extra="forbid")
    request: dict[str, JsonValue]


class CompatibilityConversationRun(CompatibilityRun):
    resume: bool = False
    language: Literal["zh", "en"] = "zh"
    timezone: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, pattern=IDEMPOTENCY_KEY_PATTERN)


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
    RUN = NAMESPACE + "v1/agent/run"
    EVALUATION_CASE = NAMESPACE + "v1/agent/evaluation-case"
    RESUME = NAMESPACE + "v1/agent/resume"
    INSPECT = NAMESPACE + "v1/agent/inspect"
    STOP = NAMESPACE + "v1/agent/stop"
    ACTIVE = NAMESPACE + "v1/agent/active"
    BACKGROUND = NAMESPACE + "v1/agent/background"


class RunSpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


RUN_ID_PATTERN = r"^[0-9a-f]{32}$"
EVENT_ID_PATTERN = r"^[0-9a-f]{32}:[1-9][0-9]{0,18}$"


class AgentRunReference(RunSpecModel):
    conversation_id: PositiveInt
    run_id: str = Field(pattern=RUN_ID_PATTERN)


class AgentResume(AgentRunReference):
    after_event_id: str | None = Field(default=None, pattern=EVENT_ID_PATTERN)


class DebugRunReference(RunSpecModel):
    run_id: str = Field(pattern=r"^debug-[0-9a-f]{32}$")


class AgentRunLookup(RunSpecModel):
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    conversation_id: PositiveInt | None = None


class AgentStop(AgentRunLookup):
    prevent_start: bool = False


class AgentActiveRun(RunSpecModel):
    run_id: str | None = Field(pattern=RUN_ID_PATTERN)


class BackgroundRun(CompatibilityRun):
    run_id: str = Field(pattern=RUN_ID_PATTERN)


class TrackedBackgroundResult(BackgroundAgentResult):
    run_id: str = Field(pattern=RUN_ID_PATTERN)


class AgentVersionReference(RunSpecModel):
    agent_id: PositiveInt
    version_no: int = Field(ge=0)


class AgentResourceVersions(RunSpecModel):
    agent_id: PositiveInt | None = None
    agent_version_no: int | None = Field(default=None, ge=0)
    model_id: PositiveInt | None = None
    model_revision: str | None = None
    mounted_agents: list[AgentVersionReference] = Field(default_factory=list)
    runtime_metadata_version: int | None = Field(default=None, ge=0)
    workbench_config_version: int | None = Field(default=None, ge=0)


class AgentRunState(AgentRunReference):
    status: Literal["starting", "running", "completed", "failed", "stopped"]
    latest_event_id: str | None = Field(pattern=EVENT_ID_PATTERN)
    cancellation_requested: bool
    resource_versions: AgentResourceVersions | None = None
    assistant_message_id: PositiveInt | None = None


class ToolBinding(RunSpecModel):
    tool_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    credential_ref: str | None = None


class ParallelExecutorBinding(RunSpecModel):
    default_timeout_seconds: Annotated[int, Field(strict=True, gt=0)]


class RunModelOverrides(RunSpecModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    enable_thinking: bool = False
    reasoning_effort: Literal["auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    reasoning_budget_tokens: PositiveInt | None = None
    context_window_tokens: PositiveInt | None = None
    max_input_tokens: PositiveInt | None = None
    max_output_tokens: PositiveInt | None = None
    default_output_reserve_tokens: PositiveInt | None = None
    tokenizer_family: str | None = Field(default=None, min_length=1, max_length=128)

    @model_serializer(mode="wrap")
    def serialize_explicit_fields(self, handler):
        return {name: value for name, value in handler(self).items() if name in self.model_fields_set}


class RunModelBinding(RunSpecModel):
    model_id: PositiveInt
    alias: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    overrides: RunModelOverrides | None = None
    provider_body_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_serializer(mode="wrap")
    def serialize_optional_body_revision(self, handler):
        data = handler(self)
        if data.get("provider_body_revision") is None:
            data.pop("provider_body_revision", None)
        return data


class ModelBindings(RunSpecModel):
    llm: RunModelBinding
    summary: RunModelBinding | None = None
    verifier: RunModelBinding | None = None
    embedding: RunModelBinding | None = None
    rerank: RunModelBinding | None = None
    additional_llms: list[RunModelBinding] = Field(default_factory=list)


class RunAttachment(RunSpecModel):
    name: str = Field(min_length=1)
    url: str = Field(pattern=r"^s3://[^/]+/.+$")
    presign: bool = False


class RunHistoryMessage(RunSpecModel):
    role: Literal["user", "assistant"]
    content: str
    attachment_refs: list[RunAttachment] = Field(default_factory=list)


class RunInput(RunSpecModel):
    query: str
    history: list[RunHistoryMessage] = Field(default_factory=list)
    attachment_refs: list[RunAttachment] = Field(default_factory=list)


class EvaluationFileTool(str, Enum):
    DOWNLOAD = "download_from_s3"
    UPLOAD = "upload_to_s3"

    @property
    def class_name(self) -> str:
        return {
            EvaluationFileTool.DOWNLOAD: "DownloadFromS3Tool",
            EvaluationFileTool.UPLOAD: "UploadToS3Tool",
        }[self]


class EvaluationSkillTool(str, Enum):
    SCRIPT = "run_skill_script"
    GUIDE = "read_skill_md"
    CONFIG = "read_skill_config"

    @property
    def class_name(self) -> str:
        return {
            EvaluationSkillTool.SCRIPT: "RunSkillScriptTool",
            EvaluationSkillTool.GUIDE: "ReadSkillMdTool",
            EvaluationSkillTool.CONFIG: "ReadSkillConfigTool",
        }[self]


class SkillExecutionBinding(RunSpecModel):
    instance_id: PositiveInt
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class FileToolDescription(RunSpecModel):
    description: str | None = None
    description_zh: str | None = None
    inputs: str | None = None
    output_type: str | None = None


class EvaluationAnalysisTool(str, Enum):
    TEXT = "analyze_text_file"
    IMAGE = "analyze_image"
    AUDIO = "analyze_audio"
    VIDEO = "analyze_video"

    @property
    def class_name(self) -> str:
        return {
            EvaluationAnalysisTool.TEXT: "AnalyzeTextFileTool",
            EvaluationAnalysisTool.IMAGE: "AnalyzeImageTool",
            EvaluationAnalysisTool.AUDIO: "AnalyzeAudioTool",
            EvaluationAnalysisTool.VIDEO: "AnalyzeVideoTool",
        }[self]

    @property
    def slot(self) -> str:
        return {
            EvaluationAnalysisTool.TEXT: "llm",
            EvaluationAnalysisTool.IMAGE: "vlm",
            EvaluationAnalysisTool.AUDIO: "vlm4",
            EvaluationAnalysisTool.VIDEO: "vlm3",
        }[self]


class KnowledgeSearchIndexBinding(RunSpecModel):
    knowledge_id: PositiveInt
    index_name: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class RevisionedModelBinding(RunSpecModel):
    model_id: PositiveInt
    revision: str = Field(min_length=1)


class AnalysisToolBinding(RunSpecModel):
    description: FileToolDescription
    selected_model_id: int | None = None
    model: RevisionedModelBinding | None = None
    usage: str | None = None


class LocalToolBinding(RunSpecModel):
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    description_zh: str | None = None
    inputs: str | None = None
    reranker: RevisionedModelBinding | None = None
    default_reranker: RevisionedModelBinding | None = None


class StoredLocalToolBinding(LocalToolBinding):
    instance_id: PositiveInt


class SkillDerivedLocalToolBinding(LocalToolBinding):
    tool_id: PositiveInt


class LangChainToolBinding(RunSpecModel):
    tool_name: str = Field(min_length=1)
    binding_id: PositiveInt
    module_file: str = Field(pattern=r"^[^/\\:]+\.py$")
    module_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeSearchBinding(RunSpecModel):
    description: FileToolDescription
    index_names: list[str]
    allowed: list[KnowledgeSearchIndexBinding]
    display_name_to_index: dict[str, str]
    document_paths: list[str] | None = None
    top_k: int = 3
    search_mode: Literal["accurate", "hybrid", "semantic"] = "hybrid"
    rerank: bool = False
    rerank_model_name: str = ""
    embedding: RevisionedModelBinding | None = None
    reranker: RevisionedModelBinding | None = None
    default_reranker: RevisionedModelBinding | None = None
    usage: str | None = None


class EvaluationAgentOptions(RunSpecModel):
    render_executor_context: bool = False
    display_name: str | None = None
    output_protocol: Literal["code_action", "final_envelope"] = "code_action"
    enable_protocol_repair_retry: bool = False
    provide_run_summary: bool | None = None
    allow_chat_metadata: bool = False
    requested_output_tokens: PositiveInt | None = None
    instructions: str | None = None
    context_items: list[dict[str, JsonValue]] | None = None
    context_manager_config: dict[str, JsonValue] | None = None
    prompt_tool_policy_snapshot: dict[str, JsonValue] | None = None
    capacity_snapshot: dict[str, JsonValue] | None = None
    context_budget_snapshot: dict[str, JsonValue] | None = None
    verification_config: dict[str, JsonValue] | None = None


class MCPBindingReference(RunSpecModel):
    tool_name: str = Field(min_length=1)
    server_id: PositiveInt | None = None
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class MCPExecutionBinding(MCPBindingReference):
    instance_id: PositiveInt


class SkillDerivedMCPBinding(MCPBindingReference):
    tool_id: PositiveInt


class ToolCallerContext(RunSpecModel):
    tenant_name: str = ""
    user_name: str = ""
    user_account: str = ""
    user_groups: list[str] = Field(default_factory=list)


class ExternalA2AExecutionBinding(RunSpecModel):
    agent_id: PositiveInt
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    invocation_name: str | None = Field(default=None, min_length=1)


class AgentResource(RunSpecModel):
    agent_id: PositiveInt
    version_no: Annotated[int, Field(ge=0)]
    name: str = Field(min_length=1)
    description: str
    prompt_templates: dict[str, JsonValue]
    max_steps: PositiveInt = 15
    model_alias: str | None = Field(default=None, min_length=1)
    invocation_name: str | None = Field(default=None, min_length=1)
    runtime_ref: str | None = Field(default=None, min_length=1)
    origin: Literal["SYSTEM", "PERSISTED", "BUILTIN_RUNTIME"] = "PERSISTED"
    tools: list[ToolBinding] = Field(default_factory=list)
    skill_refs: list[SkillExecutionBinding] = Field(default_factory=list)
    mcp_server_refs: list[str] = Field(default_factory=list)
    knowledge_base_refs: list[str] = Field(default_factory=list)
    memory_ref: str | None = None
    subagents: list["AgentResource"] = Field(default_factory=list)
    external_a2a: list[ExternalA2AExecutionBinding] = Field(default_factory=list)
    sandbox_policy: dict[str, JsonValue] | None = None
    evaluation_options: EvaluationAgentOptions | None = None


class AgentRunSpec(RunSpecModel):
    mode: Literal["nexent"]
    resource: AgentResource
    models: ModelBindings
    input: RunInput
    language: Literal["zh", "en"] = "zh"
    tool_caller: ToolCallerContext | None = None


class PreparedAgentRun(AgentRunSpec, AgentRunReference):
    """Execute an authorized snapshot for an existing conversation."""


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
