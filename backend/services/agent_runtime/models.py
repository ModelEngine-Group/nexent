"""Runtime capability and framework-neutral run models."""

from __future__ import annotations

from enum import Enum
from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CapabilityName = Literal[
    "streaming",
    "token_streaming",
    "reasoning_streaming",
    "mcp",
    "managed_agents",
    "external_a2a_agents",
    "code_execution",
    "tool_artifacts",
    "context_compression",
    "tool_call_events",
    "token_usage_events",
    "interruptible",
    "resumable_stream",
    "verification",
]


class RuntimeCapabilities(BaseModel):
    """Capability declaration exposed by a runtime adapter."""

    streaming: bool = True
    token_streaming: bool = False
    reasoning_streaming: bool = False
    process_type_compatibility: Literal["complete", "partial"] = "partial"
    mcp: bool = False
    managed_agents: bool = False
    external_a2a_agents: bool = False
    code_execution: bool = False
    tool_artifacts: bool = False
    context_compression: bool = False
    tool_call_events: bool = False
    token_usage_events: bool = False
    interruptible: bool = True
    resumable_stream: bool = False
    verification: bool = False


class RuntimeCapabilityRequirements(BaseModel):
    """Capabilities required or optionally requested by a run plan."""

    required: set[CapabilityName] = Field(default_factory=set)
    optional: set[CapabilityName] = Field(default_factory=set)


class CapabilityNegotiationStatus(str):
    """Negotiation status values."""

    OK = "ok"
    DEGRADED = "degraded"
    BLOCKING_FAILURE = "blocking_failure"


class CapabilityNegotiationResult(BaseModel):
    """Result of matching a run plan's needs against runtime capabilities."""

    status: Literal["ok", "degraded", "blocking_failure"]
    missing_required: list[str] = Field(default_factory=list)
    downgraded_optional: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        """Return whether runtime execution must be blocked."""
        return self.status == CapabilityNegotiationStatus.BLOCKING_FAILURE


def negotiate_runtime_capabilities(
    capabilities: RuntimeCapabilities,
    requirements: RuntimeCapabilityRequirements,
) -> CapabilityNegotiationResult:
    """Compare required and optional plan capabilities with a runtime."""
    missing_required = [
        name
        for name in sorted(requirements.required)
        if not bool(getattr(capabilities, name))
    ]
    downgraded_optional = [
        name
        for name in sorted(requirements.optional)
        if not bool(getattr(capabilities, name))
    ]

    if missing_required:
        return CapabilityNegotiationResult(
            status=CapabilityNegotiationStatus.BLOCKING_FAILURE,
            missing_required=missing_required,
            downgraded_optional=downgraded_optional,
            warnings=[
                f"Runtime does not support required capability: {name}"
                for name in missing_required
            ],
        )

    if downgraded_optional:
        return CapabilityNegotiationResult(
            status=CapabilityNegotiationStatus.DEGRADED,
            downgraded_optional=downgraded_optional,
            warnings=[
                f"Runtime does not support optional capability: {name}"
                for name in downgraded_optional
            ],
        )

    return CapabilityNegotiationResult(status=CapabilityNegotiationStatus.OK)


class ContextMode(str, Enum):
    """Context strategy modes supported by the neutral run plan."""

    LEGACY = "legacy"
    MANAGED = "managed"
    RUNTIME_NATIVE = "runtime_native"


class ToolVisibility(str, Enum):
    """Tool visibility levels."""

    MODEL = "model"
    EXECUTOR = "executor"
    INTERNAL = "internal"


class ToolSource(str, Enum):
    """Supported framework-neutral tool sources."""

    LOCAL = "local"
    MCP = "mcp"
    LANGCHAIN = "langchain"
    BUILTIN = "builtin"
    MEMORY = "memory"
    KNOWLEDGE = "knowledge"
    SKILL = "skill"
    PLUGIN = "plugin"


class RunStatus(str, Enum):
    """Active run lifecycle states."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class PromptBundle(BaseModel):
    """Prompt fragments and context components assembled before runtime mapping."""

    fragments: dict[str, Any] = Field(default_factory=dict)
    context_components: list[Any] = Field(default_factory=list)
    rendered_legacy_system_prompt: str | None = None
    templates: dict[str, Any] = Field(default_factory=dict)


class ContextPolicy(BaseModel):
    """Framework-neutral context policy."""

    mode: ContextMode = ContextMode.LEGACY
    token_threshold: int | None = None
    soft_input_budget_tokens: int | None = None
    hard_input_budget_tokens: int | None = None
    compression: dict[str, Any] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    """Framework-neutral tool declaration."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    raw_inputs: str | None = None
    output_type: str = "any"
    source: ToolSource = ToolSource.LOCAL
    class_name: str | None = None
    usage: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    injected_params: dict[str, Any] = Field(default_factory=dict)
    visibility: ToolVisibility = ToolVisibility.MODEL


class ToolRuntimeContext(BaseModel):
    """System context provided to tool factories and tool wrappers."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    agent_name: str
    user_id: str
    tenant_id: str
    runtime_provider: str
    event_sink: Any | None = None
    run_control: Any | None = None
    resources: dict[str, Any] = Field(default_factory=dict)


class AgentSpec(BaseModel):
    """Framework-neutral agent structure."""

    agent_id: int | str
    name: str
    description: str = ""
    model_name: str
    max_steps: int
    prompt: PromptBundle = Field(default_factory=PromptBundle)
    tools: list[ToolSpec] = Field(default_factory=list)
    managed_agents: list["AgentSpec"] = Field(default_factory=list)
    external_a2a_agents: list[Any] = Field(default_factory=list)
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    verification_config: Any | None = None
    runtime_hints: dict[str, Any] = Field(default_factory=dict)


class OperatorSpec(BaseModel):
    """Declarative operator reference stored in AgentRunPlan."""

    name: str
    stages: set[str] = Field(default_factory=set)
    priority: int = 100
    config: dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class MCPConnectionConfig(BaseModel):
    """Framework-neutral MCP connection configuration."""

    name: str
    url: str
    transport: Literal["sse", "streamable-http"]
    headers: dict[str, str] = Field(default_factory=dict)
    required: bool = True


class RuntimeWarningInfo(BaseModel):
    """Warning emitted during plan assembly or runtime preparation."""

    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityContribution(BaseModel):
    """Declarative capability output produced by an assembly provider."""

    agent_record: dict[str, Any] = Field(default_factory=dict)
    version_no: int | None = None
    model_configs: list[Any] = Field(default_factory=list)
    root_agent: AgentSpec | None = None
    managed_agents: list[AgentSpec] = Field(default_factory=list)
    external_a2a_agents: list[Any] = Field(default_factory=list)
    tools_by_agent: dict[str, list[ToolSpec]] = Field(default_factory=dict)
    prompt_fragments: dict[str, Any] = Field(default_factory=dict)
    context_components: list[Any] = Field(default_factory=list)
    mcp_connections: list[MCPConnectionConfig] = Field(default_factory=list)
    runtime_resources: dict[str, Any] = Field(default_factory=dict)
    operators: list[OperatorSpec] = Field(default_factory=list)
    monitoring_metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[RuntimeWarningInfo] = Field(default_factory=list)


class AgentRunRequestContext(BaseModel):
    """Stable identity and request-scoped overrides for a run."""

    request_id: str
    runtime_provider: str
    agent_id: int
    conversation_id: int | None = None
    query: str
    history: list[Any] | None = None
    minio_files: list[dict[str, Any]] | None = None
    user_id: str
    tenant_id: str
    language: str
    is_debug: bool = False
    version_no: int | None = None
    override_model_id: int | None = None
    requested_output_tokens: int | None = None
    tool_params: Any | None = None


class RunControl(BaseModel):
    """Cancellation boundary shared by runtime adapters."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    user_id: str
    conversation_id: int | str | None = None
    legacy_stop_event: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    cancelled: bool = False

    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self.cancelled or bool(
            self.legacy_stop_event and self.legacy_stop_event.is_set()
        )

    def cancel(self) -> None:
        """Mark the run as cancelled and bridge to the legacy stop event."""
        self.cancelled = True
        if self.legacy_stop_event is not None:
            self.legacy_stop_event.set()


class ActiveRunHandle(BaseModel):
    """Registered active run handle used by Runtime API Layer and stop flow."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    user_id: str
    conversation_id: int | str | None = None
    runtime_provider: str
    run_control: RunControl
    event_sink: Any | None = None
    legacy_agent_run_info: Any | None = None
    status: RunStatus = RunStatus.STARTING


class AssemblyState(BaseModel):
    """Mutable assembly draft used before creating AgentRunPlan."""

    agent_record: dict[str, Any] = Field(default_factory=dict)
    version_no: int | None = None
    model_configs: list[Any] = Field(default_factory=list)
    root_agent: AgentSpec | None = None
    managed_agents: list[AgentSpec] = Field(default_factory=list)
    external_a2a_agents: list[Any] = Field(default_factory=list)
    tools_by_agent: dict[str, list[ToolSpec]] = Field(default_factory=dict)
    prompt_fragments: dict[str, Any] = Field(default_factory=dict)
    context_components: list[Any] = Field(default_factory=list)
    mcp_connections: list[MCPConnectionConfig] = Field(default_factory=list)
    runtime_resources: dict[str, Any] = Field(default_factory=dict)
    operators: list[OperatorSpec] = Field(default_factory=list)
    monitoring_metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[RuntimeWarningInfo] = Field(default_factory=list)


class AgentRunPlan(BaseModel):
    """Immutable framework-neutral run plan passed to runtime adapters."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    request_id: str
    runtime_provider: str
    query: str
    history: list[Any] | None = None
    model_config_list: list[Any] = Field(default_factory=list)
    root_agent: AgentSpec
    mcp_connections: list[MCPConnectionConfig] = Field(default_factory=list)
    runtime_resources: dict[str, Any] = Field(default_factory=dict)
    operators: list[OperatorSpec] = Field(default_factory=list)
    monitoring_metadata: dict[str, Any] = Field(default_factory=dict)
    capability_requirements: RuntimeCapabilityRequirements = Field(
        default_factory=RuntimeCapabilityRequirements
    )
    run_control: RunControl


def derive_runtime_capability_requirements(
    root_agent: AgentSpec,
    mcp_connections: list[MCPConnectionConfig] | None = None,
    runtime_resources: dict[str, Any] | None = None,
) -> RuntimeCapabilityRequirements:
    """Derive runtime requirements from the concrete assembled run plan."""
    resources = runtime_resources or {}
    required: set[CapabilityName] = {"streaming", "interruptible"}
    optional: set[CapabilityName] = {
        "token_streaming",
        "reasoning_streaming",
        "tool_call_events",
        "token_usage_events",
    }

    connections = list(mcp_connections or [])
    if any(connection.required for connection in connections):
        required.add("mcp")
    elif connections:
        optional.add("mcp")
    if root_agent.managed_agents:
        required.add("managed_agents")
    if root_agent.external_a2a_agents:
        required.add("external_a2a_agents")
    if (
        root_agent.context_policy.mode == ContextMode.MANAGED
        or root_agent.context_policy.compression
    ):
        required.add("context_compression")
    if _verification_enabled(root_agent.verification_config):
        required.add("verification")
    if bool(resources.get("runtime.resumable_stream_required")):
        required.add("resumable_stream")
    if bool(resources.get("runtime.tool_artifacts_enabled")) or any(
        tool.source == ToolSource.SKILL
        or (
            tool.source == ToolSource.BUILTIN
            and (
                tool.metadata.get("capability") == "skill"
                or (tool.class_name or tool.name)
                in {
                    "ReadSkillConfigTool",
                    "ReadSkillMdTool",
                    "RunSkillScriptTool",
                    "WriteSkillFileTool",
                }
            )
        )
        for tool in root_agent.tools
    ):
        optional.add("tool_artifacts")

    optional.difference_update(required)
    return RuntimeCapabilityRequirements(required=required, optional=optional)


def _verification_enabled(config: Any) -> bool:
    if config is None:
        return False
    if isinstance(config, dict):
        return bool(config.get("enabled"))
    return bool(getattr(config, "enabled", False))
