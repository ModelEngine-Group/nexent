from __future__ import annotations

from threading import Event
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from ..utils.observer import MessageObserver
from .context.models import ContextItemInput


if TYPE_CHECKING:
    from .a2a_agent_proxy import A2AAgentInfo

# Protocol type constants (must match backend/database/a2a_agent_db.py definitions)
PROTOCOL_JSONRPC = "JSONRPC"
PROTOCOL_HTTP_JSON = "HTTP+JSON"
PROTOCOL_GRPC = "GRPC"


class ModelConfig(BaseModel):
    cite_name: str = Field(description="Model alias")
    api_key: str = Field(description="API key", default="")
    model_name: str = Field(description="Model call name")
    url: str = Field(description="Model endpoint URL")
    temperature: Optional[float] = Field(description="Temperature", default=0.1)
    top_p: Optional[float] = Field(description="Top P", default=0.95)
    ssl_verify: Optional[bool] = Field(description="Whether to verify SSL certificates", default=True)
    model_factory: Optional[str] = Field(
        description="Model provider identifier (e.g., openai, modelengine)",
        default=None
    )
    extra_body: Optional[Dict[str, Any]] = Field(
        description=(
            "Optional dict merged into every OpenAI-compatible "
            "chat.completions.create request body. Used for provider-specific "
            'switches such as Qwen3 chat_template_kwargs={"enable_thinking": false}. '
            "Defaults to None so production behaviour is unchanged."
        ),
        default=None,
    )
    max_output_tokens: Optional[int] = Field(
        description=(
            "Per-call completion output cap forwarded to chat.completions.create. "
            "Preferred name over the deprecated max_tokens. Defaults to None so "
            "production keeps the provider's own default (typically the model's "
            "max output). Benchmarks set this explicitly (e.g. 4096) to bound "
            "pathological generation loops where a model regurgitates context."
        ),
        default=None,
    )
    max_tokens: Optional[int] = Field(
        description=(
            "DEPRECATED W1 alias for max_output_tokens. Retained so existing "
            "callers and persisted ModelRecord rows keep working during the "
            "migration window. If only max_tokens is set, the validator copies "
            "it into max_output_tokens; if both are set, max_output_tokens wins."
        ),
        default=None,
    )
    context_window_tokens: Optional[int] = Field(
        description="Total combined input/output context window in tokens, when the provider uses a combined window. Resolved by ModelCapacityResolver per W1 ADR.",
        default=None,
    )
    max_input_tokens: Optional[int] = Field(
        description="Provider hard input-token limit when distinct from the combined window. Resolved by ModelCapacityResolver per W1 ADR.",
        default=None,
    )
    default_output_reserve_tokens: Optional[int] = Field(
        description="Default output allowance reserved per request before constructing input context. Resolved by ModelCapacityResolver per W1 ADR.",
        default=None,
    )
    tokenizer_family: Optional[str] = Field(
        description="Tokenizer-family identifier resolved via tokenizer_registry. None forces estimated counting mode.",
        default=None,
    )
    capacity_source: Optional[str] = Field(
        description="Source of the persisted capacity value: operator | profile | provider_candidate | legacy | default | unknown.",
        default=None,
    )
    capability_profile_version: Optional[str] = Field(
        description="Version of the approved provider/model capability profile selected by the resolver, e.g. 'openai/gpt-4o@1'.",
        default=None,
    )
    timeout_seconds: Optional[float] = Field(
        description="Request timeout in seconds. If None, uses provider default.",
        default=None
    )
    concurrency_limit: Optional[int] = Field(
        description="Maximum concurrent requests for this model. If None, no limit.",
        default=None,
    )
    prompt_cache: Optional[Dict[str, Any]] = Field(
        description=(
            "Selected prompt-cache capability profile. Unknown or absent "
            "capability disables provider cache directives while still allowing "
            "deterministic prefix proxy metrics."
        ),
        default=None,
    )

    @model_validator(mode="after")
    def _backfill_max_output_from_legacy_max_tokens(self) -> "ModelConfig":
        if self.max_output_tokens is None and self.max_tokens is not None:
            # Heuristic: if max_tokens >= 32768, it's likely the old
            # "total context window" semantics (pre-W1), not an output limit.
            # Don't copy it directly; use a conservative default instead.
            if self.max_tokens >= 32768:
                self.max_output_tokens = 4096
            else:
                fallback = self.max_tokens
                if (
                    self.context_window_tokens is not None
                    and fallback > self.context_window_tokens
                ):
                    fallback = self.context_window_tokens - 1
                self.max_output_tokens = max(fallback, 1)
        return self


class ToolConfig(BaseModel):
    class_name: str = Field(description="Tool class name")
    name: Optional[str] = Field(description="Tool name")
    description: Optional[str] = Field(description="Tool description", default=None)
    inputs: Optional[str] = Field(description="Tool inputs", default=None)
    output_type: Optional[str] = Field(description="Tool output type", default=None)
    params: Dict[str, Any] = Field(description="Initialization parameters", default=None)
    source: str = Field(description="Tool source, can be local or mcp", default="local")
    usage: Optional[str] = Field(description="MCP server name", default=None)
    metadata: Optional[Dict[str, Any]] = Field(description="Metadata", default=None)
    labels: Optional[List[str]] = Field(description="Tool labels for filtering", default=None)


VerificationEvent = Literal[
    "tool_precheck",
    "tool_result",
    "retrieval",
    "code_execution",
    "handoff",
    "final_answer",
]
VerificationStrictness = Literal["lenient", "balanced", "strict"]
VerificationFailPolicy = Literal["repair_then_controlled_summary", "warn"]

GuardrailSeverity = Literal["block", "mask", "pass"]


class GuardrailRule(BaseModel):
    """A single pattern-matching rule for the guardrail engine.

    Each rule compiles to a regex and is matched at every guardrail checkpoint.

    Attributes:
        name: Human-readable rule identifier, e.g. "cn_id_number".
        pattern: Regular expression string (Python ``re`` syntax).
        severity: What to do when the pattern matches.
        description: Optional free-text explanation shown in the UI.
    """

    name: str = Field(description="Human-readable rule identifier")
    pattern: str = Field(description="Regular expression in Python re syntax")
    severity: GuardrailSeverity = Field(
        description="Action when pattern matches: block, mask, or pass",
        default="block",
    )
    description: Optional[str] = Field(
        description="Optional explanation shown in configuration UI",
        default=None,
    )


class GuardrailConfig(BaseModel):
    """Configuration container for the guardrail subsystem.

    Stored as a nested object inside ``AgentVerificationConfig.guardrail_config``
    and persisted to the database as part of the ``verification_config`` JSONB
    column — no separate database migration is needed.

    Attributes:
        enabled: Master switch. When False, GuardrailEngine is not created.
        rules: Ordered list of pattern rules. Evaluated in order; first
               match wins (later rules for the same text are skipped).
        default_action: Fallback action when a rule matches but has an
                        unknown severity value (defensive, should not happen).
    """

    enabled: bool = Field(description="Whether guardrail screening is active", default=False)
    rules: List[GuardrailRule] = Field(
        description="Ordered pattern rules; first match wins",
        default_factory=list,
    )
    default_action: GuardrailSeverity = Field(
        description="Fallback severity when a rule matches but severity is unset",
        default="pass",
    )


class AgentVerificationConfig(BaseModel):
    """Configuration for layered ReAct self-verification."""

    enabled: bool = Field(description="Whether self-verification is enabled", default=False)
    step_verification_enabled: bool = Field(
        description="Whether to verify critical ReAct step events",
        default=True,
    )
    final_verification_enabled: bool = Field(
        description="Whether to verify final answer candidates before returning them",
        default=True,
    )
    llm_verification_enabled: bool = Field(
        description="Whether to use the LLM as a final-answer verifier after deterministic checks",
        default=True,
    )
    max_final_rounds: int = Field(
        description="Maximum number of final-answer verification attempts",
        default=2,
        ge=1,
        le=5,
    )
    strictness: VerificationStrictness = Field(
        description="Verification strictness profile",
        default="balanced",
    )
    fail_policy: VerificationFailPolicy = Field(
        description="Policy when final verification still fails after repair attempts",
        default="repair_then_controlled_summary",
    )
    pass_score: float = Field(
        description="Minimum verifier score for final answers",
        default=0.75,
        ge=0.0,
        le=1.0,
    )
    critical_events: List[VerificationEvent] = Field(
        description="Critical ReAct events that should be verified",
        default_factory=lambda: [
            "tool_precheck",
            "tool_result",
            "retrieval",
            "code_execution",
            "handoff",
            "final_answer",
        ],
    )
    guardrail_config: Optional[GuardrailConfig] = Field(
        description="Guardrail screening configuration (blacklist/whitelist patterns)",
        default=None,
    )

class AgentConfig(BaseModel):
    name: str = Field(description="Agent name")
    description: str = Field(description="Agent description")
    prompt_templates: Optional[Dict[str, Any]] = Field(description="Prompt templates", default=None)
    tools: List[ToolConfig] = Field(description="List of tool information")
    max_steps: int = Field(description="Maximum number of steps for current Agent", default=15, ge=1)
    requested_output_tokens: Optional[int] = Field(
        description=(
            "Per-agent W2 output reserve override. None means inherit the "
            "resolved model-level default."
        ),
        default=None,
        ge=1,
    )
    model_name: str = Field(description="Model alias from ModelConfig")
    provide_run_summary: Optional[bool] = Field(description="Whether to provide run summary to upper-level Agent", default=False)
    instructions: Optional[str] = Field(description="Additional instructions to prepend to system prompt", default=None)
    managed_agents: List["AgentConfig"] = Field(
        description="Internal managed sub-agents created locally",
        default=[]
    )
    external_a2a_agents: List["ExternalA2AAgentConfig"] = Field(
        description="External A2A agents called via HTTP requests",
        default=[]
    )
    context_manager_config: Optional[Any] = Field(
        description="Context manager configuration for conversation-level memory compression",
        default=None
    )
    context_items: Optional[List[ContextItemInput]] = Field(
        description="Authorized fine-grained context item inputs for SDK assembly",
        default=None
    )
    capacity_snapshot: Optional[Dict[str, Any]] = Field(
        description="Resolved model capacity snapshot fields for request monitoring",
        default=None,
    )
    safe_input_budget_snapshot: Optional[Dict[str, Any]] = Field(
        description="Resolved W2 safe input budget snapshot for request execution",
        default=None,
    )
    verification_config: AgentVerificationConfig = Field(
        description="Layered ReAct self-verification configuration",
        default_factory=AgentVerificationConfig,
    )
    enable_planning: bool = Field(
        description="Whether to enable the planning phase before execution",
        default=False,
    )
    sandbox_policy: Optional[Dict[str, Any]] = Field(
        description=(
            "Sandbox policy for LLM-generated Python code execution.  Keys: "
            "level (local/docker/wasm), "
            "scope (session/system), "
            "docker_image, memory_limit_mb, cpu_quota, "
            "network_disabled, timeout_seconds, shell_policy, "
            "output_dir, auto_sync_outputs.  "
            'Example: {"level": "docker", "scope": "session", '
            '"docker_image": "nexent/nexent-sandbox:latest"}'
        ),
        default=None,
    )


class AgentHistory(BaseModel):
    role: str = Field(description="Role, can be user or assistant")
    content : str = Field(description="Conversation content")


class PlanStep(BaseModel):
    """Single step within an agent plan."""
    id: str = Field(description="Unique step identifier, e.g. 'step-1'")
    title: str = Field(description="Short step title")
    description: str = Field(description="Detailed step description")
    status: Literal["pending", "in_progress", "completed", "skipped"] = Field(
        description="Current execution status of the step",
        default="pending"
    )


class AgentPlan(BaseModel):
    """Structured task plan generated before agent execution."""
    plan_id: str = Field(description="Unique plan identifier")
    title: str = Field(description="Plan title extracted from the task")
    steps: List[PlanStep] = Field(description="Ordered list of plan steps")
    current_step_index: int = Field(
        description="Index of the currently executing step",
        default=0
    )


class AgentRunInfo(BaseModel):
    query: str = Field(description="User query")
    model_config_list: List[ModelConfig] = Field(description="List of model configurations")
    observer: MessageObserver = Field(description="Return data")
    agent_config: AgentConfig = Field(description="Detailed Agent configuration")
    mcp_host: Optional[List[Union[str, Dict[str, Any]]]] = Field(
        description="MCP server address(es). Can be a string (URL) or dict with 'url', 'transport', "
        "and optionally 'authorization' or 'headers' keys. "
        "Transport can be 'sse' or 'streamable-http'. If string, transport is auto-detected based on URL ending: "
        "URLs ending with '/sse' use 'sse' transport, URLs ending with '/mcp' use 'streamable-http' transport. "
        "Authorization can be provided as 'authorization' (e.g., 'Bearer token') or as 'headers' dict.",
        default=None
    )
    history: Optional[List[AgentHistory]] = Field(description="Historical conversation information", default=None)
    stop_event: Event = Field(description="Stop event control")
    context_input: Optional[Any] = Field(
        description="Immutable run-scoped context snapshot supplied by the application boundary.",
        default=None,
    )
    capacity_snapshot: Optional[Dict[str, Any]] = Field(
        description="Resolved model capacity snapshot fields for request monitoring",
        default=None,
    )
    safe_input_budget_snapshot: Optional[Dict[str, Any]] = Field(
        description="Resolved W2 safe input budget snapshot for request execution",
        default=None,
    )
    enable_planning: bool = Field(
        description="Whether to enable the planning phase before execution",
        default=False
    )
    redis_client: Optional[Any] = Field(
        description="Redis client for plan persistence. "
                    "If provided, plan_repo will use Redis as primary storage with local fallback.",
        default=None
    )
    sandbox_config: Optional[Any] = Field(
        description=(
            "Resolved SandboxConfig for sandbox isolation.  "
            "Populated by the backend service layer from AgentConfig.sandbox_policy "
            "and NEXENT_SANDBOX_* environment variables.  "
            "When None the SDK uses LocalPythonExecutor (backwards-compatible)."
        ),
        default=None,
    )
    minio_client: Optional[Any] = Field(
        description=(
            "MinIO client for syncing sandbox output files to object storage.  "
            "Required when sandbox_config.auto_sync_outputs is True."
        ),
        default=None,
    )

    class Config:
        arbitrary_types_allowed = True

class MemoryContext(BaseModel):
    user_config: MemoryUserConfig = Field(description="Memory user configuration")
    tenant_id: str = Field(description="Tenant id")
    user_id: str = Field(description="User id")
    agent_id: str = Field(description="Agent id")

    def __str__(self) -> str:  # pragma: no cover
        return self.model_dump_json(indent=2, ensure_ascii=False)


class MemoryUserConfig(BaseModel):
    memory_switch: bool = Field(description="Whether to use memory")
    agent_share_option: str = Field(description="Agent share option")
    disable_agent_ids: List[str] = Field(description="Disable agent ids")
    disable_user_agent_ids: List[str] = Field(description="Disable user agent ids")

    def __str__(self) -> str:  # pragma: no cover
        return self.model_dump_json(indent=2, ensure_ascii=False)


class ExternalA2AAgentConfig(BaseModel):
    """Configuration for an external A2A agent that can be called as sub-agent."""
    agent_id: str = Field(description="External agent ID")
    name: str = Field(description="Agent display name")
    description: str = Field(description="Agent description for prompt", default="")
    url: str = Field(description="A2A endpoint URL")
    api_key: Optional[str] = Field(description="API key for authentication", default=None)
    transport_type: str = Field(
        description="Transport type: http-streaming or http-polling",
        default="http-streaming"
    )
    protocol_version: str = Field(description="A2A protocol version", default="1.0")
    protocol_type: str = Field(
        description="Protocol type: JSONRPC, HTTP+JSON, or GRPC",
        default=PROTOCOL_JSONRPC
    )
    timeout: float = Field(description="Request timeout in seconds", default=300.0)
    raw_card: Optional[Dict[str, Any]] = Field(
        description="Raw Agent Card containing skills and capabilities",
        default=None
    )

    def model_post_init(self, __context) -> None:
        """Auto-enhance description with skills info from raw_card."""
        # Only auto-enhance if raw_card is present
        if self.raw_card:
            skills_info = self._build_skills_description()
            if skills_info:
                if self.description:
                    self.description = f"{self.description}\n\n{skills_info}"
                else:
                    self.description = skills_info

    def _build_skills_description(self) -> str:
        """Build detailed skills description from raw_card."""
        if not self.raw_card:
            return ""

        skills = self.raw_card.get("skills", [])
        if not skills:
            return ""

        # Build examples section
        examples_lines = []
        for skill in skills:
            examples = skill.get("examples", [])
            if examples:
                examples_lines.extend(examples[:3])

        examples_section = ""
        if examples_lines:
            # Shuffle and pick some examples
            examples_str = ', '.join(f'"{ex}"' for ex in examples_lines[:8])
            examples_section = f"\n  调用示例: {examples_str}"

        # Build capability description (without explicit skill IDs)
        capability_names = [skill.get("name", "") for skill in skills if skill.get("name")]
        capability_str = "、".join(capability_names) if capability_names else ""

        return f"[此助手可处理: {capability_str}]{examples_section}"

    def to_a2a_agent_info(self) -> "A2AAgentInfo":
        """Convert to A2AAgentInfo for SDK usage."""
        from .a2a_agent_proxy import A2AAgentInfo
        return A2AAgentInfo(
            agent_id=self.agent_id,
            name=self.name,
            url=self.url,
            api_key=self.api_key,
            transport_type=self.transport_type,
            protocol_version=self.protocol_version,
            protocol_type=self.protocol_type,
            timeout=self.timeout,
            raw_card=self.raw_card
        )


AgentConfig.model_rebuild()
