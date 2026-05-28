from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from threading import Event
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

logger = logging.getLogger("context_strategy")

# Protocol type constants (must match backend/database/a2a_agent_db.py definitions)
PROTOCOL_JSONRPC = "JSONRPC"
PROTOCOL_HTTP_JSON = "HTTP+JSON"
PROTOCOL_GRPC = "GRPC"

from pydantic import BaseModel, Field

from ..utils.observer import MessageObserver

# TYPE_CHECKING to avoid circular import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .agent_context import ContextManagerConfig
    from .summary_config import ContextManagerConfig as SummaryConfig


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
    max_tokens: Optional[int] = Field(
        description=(
            "Per-call completion output cap forwarded to chat.completions.create. "
            "Defaults to None so production keeps the provider's own default "
            "(typically the model's max output). Benchmarks set this explicitly "
            "(e.g. 4096) to bound pathological generation loops where a model "
            "regurgitates context."
        ),
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


class ToolConfig(BaseModel):
    class_name: str = Field(description="Tool class name")
    name: Optional[str] = Field(description="Tool name")
    description: Optional[str] = Field(description="Tool description")
    inputs: Optional[str] = Field(description="Tool inputs")
    output_type: Optional[str] = Field(description="Tool output type")
    params: Dict[str, Any] = Field(description="Initialization parameters")
    source: str = Field(description="Tool source, can be local or mcp")
    usage: Optional[str] = Field(description="MCP server name", default=None)
    metadata: Optional[Dict[str, Any]] = Field(description="Metadata", default=None)

class AgentConfig(BaseModel):
    name: str = Field(description="Agent name")
    description: str = Field(description="Agent description")
    prompt_templates: Optional[Dict[str, Any]] = Field(description="Prompt templates", default=None)
    tools: List[ToolConfig] = Field(description="List of tool information")
    max_steps: int = Field(description="Maximum number of steps for current Agent", default=15, ge=1, le=30)
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
    context_components: Optional[List[Any]] = Field(
        description="Pre-built context components for system prompt assembly",
        default=None
    )


class AgentHistory(BaseModel):
    role: str = Field(description="Role, can be user or assistant")
    content : str = Field(description="Conversation content")


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
    context_manager: Optional[Any] = Field(
        description="Conversation-level reusable ContextManager instance. "
                    "If provided, it will be attached to the CoreAgent instead of creating a new one.",
        default=None
    )

    class Config:
        arbitrary_types_allowed = True

class MemoryContext(BaseModel):
    user_config: MemoryUserConfig = Field(description="Memory user configuration")
    memory_config: Dict[str, Any] = Field(description="Memory llm/embedder/vectorstore configuration")
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


# =============================================================================
# Context Component System - Building blocks for system prompt assembly
# =============================================================================

ComponentType = Literal["system_prompt", "tools", "skills", "memory", "knowledge_base", "managed_agents", "external_a2a_agents"]


class ContextComponent(BaseModel, ABC):
    """Abstract base for all context components.
    
    Each component knows how to convert itself to LLM message format via to_messages().
    Follows smolagents MemoryStep.to_messages() pattern.
    """
    component_type: ComponentType = Field(description="Type identifier for this component")
    priority: int = Field(description="Selection priority (higher = more important)", default=10)
    token_estimate: int = Field(description="Estimated token count", default=0)
    metadata: Dict[str, Any] = Field(description="Additional metadata", default_factory=dict)

    @abstractmethod
    def to_messages(self) -> List[Dict[str, str]]:
        """Convert component content to message format for LLM.
        
        Returns:
            List of message dicts with 'role' and 'content' keys.
        """
        pass

    def estimate_tokens(self, chars_per_token: float = 1.5) -> int:
        """Estimate token count from content length.
        
        Args:
            chars_per_token: Average characters per token ratio.
            
        Returns:
            Estimated token count.
        """
        total_chars = sum(len(m.get("content", "")) for m in self.to_messages())
        return int(total_chars / chars_per_token)


class SystemPromptComponent(ContextComponent):
    """System prompt component - base instructions for the agent."""
    component_type: ComponentType = Field(default="system_prompt")
    content: str = Field(description="Rendered system prompt content")
    template_name: Optional[str] = Field(description="Source template name", default=None)

    def to_messages(self) -> List[Dict[str, str]]:
        return [{"role": "system", "content": self.content}]


class ToolsComponent(ContextComponent):
    """Tool descriptions component - available tools for the agent."""
    component_type: ComponentType = Field(default="tools")
    tools: List[Dict[str, Any]] = Field(description="List of tool definitions", default_factory=list)
    formatted_description: str = Field(description="Pre-formatted tool descriptions text", default="")

    def to_messages(self) -> List[Dict[str, str]]:
        if self.formatted_description:
            return [{"role": "system", "content": self.formatted_description}]
        return []

    def add_tool(self, name: str, description: str, inputs: str, output_type: str) -> None:
        """Add a tool definition."""
        self.tools.append({
            "name": name,
            "description": description,
            "inputs": inputs,
            "output_type": output_type
        })


class SkillsComponent(ContextComponent):
    """Skill summaries component - available skills for the agent."""
    component_type: ComponentType = Field(default="skills")
    skills: List[Dict[str, Any]] = Field(description="List of skill definitions", default_factory=list)
    formatted_description: str = Field(description="Pre-formatted skill summaries text", default="")

    def to_messages(self) -> List[Dict[str, str]]:
        if self.formatted_description:
            return [{"role": "system", "content": self.formatted_description}]
        return []

    def add_skill(self, name: str, description: str, examples: List[str] = None) -> None:
        """Add a skill definition."""
        self.skills.append({
            "name": name,
            "description": description,
            "examples": examples or []
        })


class MemoryComponent(ContextComponent):
    """Memory context component - long-term memory (mem0) search results."""
    component_type: ComponentType = Field(default="memory")
    memories: List[Dict[str, Any]] = Field(description="Memory search results", default_factory=list)
    formatted_content: str = Field(description="Pre-formatted memory context text", default="")
    search_query: Optional[str] = Field(description="Query used to search memory", default=None)

    def to_messages(self) -> List[Dict[str, str]]:
        if self.formatted_content:
            return [{"role": "system", "content": self.formatted_content}]
        return []

    def add_memory(self, content: str, memory_type: str = "user", metadata: Dict[str, Any] = None) -> None:
        """Add a memory entry."""
        self.memories.append({
            "content": content,
            "memory_type": memory_type,
            "metadata": metadata or {}
        })


class KnowledgeBaseComponent(ContextComponent):
    """Knowledge base component - KB summary context."""
    component_type: ComponentType = Field(default="knowledge_base")
    summary: str = Field(description="Knowledge base summary text", default="")
    kb_ids: List[str] = Field(description="Knowledge base IDs used", default_factory=list)

    def to_messages(self) -> List[Dict[str, str]]:
        if self.summary:
            return [{"role": "system", "content": self.summary}]
        return []


class ManagedAgentsComponent(ContextComponent):
    """Managed agents component - internal sub-agent definitions."""
    component_type: ComponentType = Field(default="managed_agents")
    agents: List[Dict[str, Any]] = Field(description="Managed agent definitions", default_factory=list)
    formatted_description: str = Field(description="Pre-formatted agent descriptions", default="")

    def to_messages(self) -> List[Dict[str, str]]:
        if self.formatted_description:
            return [{"role": "system", "content": self.formatted_description}]
        return []

    def add_agent(self, name: str, description: str, tools: List[str] = None) -> None:
        """Add a managed agent definition."""
        self.agents.append({
            "name": name,
            "description": description,
            "tools": tools or []
        })


class ExternalAgentsComponent(ContextComponent):
    """External A2A agents component - external agent definitions."""
    component_type: ComponentType = Field(default="external_a2a_agents")
    agents: List[Dict[str, Any]] = Field(description="External A2A agent definitions", default_factory=list)
    formatted_description: str = Field(description="Pre-formatted agent descriptions", default="")

    def to_messages(self) -> List[Dict[str, str]]:
        if self.formatted_description:
            return [{"role": "system", "content": self.formatted_description}]
        return []

    def add_agent(self, agent_id: str, name: str, description: str, url: str) -> None:
        """Add an external A2A agent definition."""
        self.agents.append({
            "agent_id": agent_id,
            "name": name,
            "description": description,
            "url": url
        })


# =============================================================================
# Context Strategy System - Pluggable component selection algorithms
# =============================================================================

class ContextStrategy(ABC):
    """Abstract base for context component selection strategies."""
    
    @abstractmethod
    def select_components(
        self,
        components: List[ContextComponent],
        token_budget: int,
        component_budgets: Dict[str, int]
    ) -> List[ContextComponent]:
        """Select components to include within constraints.
        
        Args:
            components: All available context components.
            token_budget: Maximum total tokens allowed.
            component_budgets: Per-type token limits.
            
        Returns:
            Selected components in priority order.
        """
        pass

    @abstractmethod
    def get_strategy_name(self) -> str:
        """Return strategy identifier."""
        pass


class FullStrategy(ContextStrategy):
    """Keep all components - for unlimited context models."""
    
    def select_components(
        self,
        components: List[ContextComponent],
        token_budget: int,
        component_budgets: Dict[str, int]
    ) -> List[ContextComponent]:
        return sorted(components, key=lambda c: c.priority, reverse=True)

    def get_strategy_name(self) -> str:
        return "full"


class TokenBudgetStrategy(ContextStrategy):
    """Select components within total token budget by priority."""
    
    def select_components(
        self,
        components: List[ContextComponent],
        token_budget: int,
        component_budgets: Dict[str, int]
    ) -> List[ContextComponent]:
        sorted_components = sorted(components, key=lambda c: c.priority, reverse=True)
        selected: List[ContextComponent] = []
        total_tokens = 0
        type_totals: Dict[str, int] = {}
        
        for comp in sorted_components:
            comp_tokens = comp.token_estimate or comp.estimate_tokens()
            comp_budget = component_budgets.get(comp.component_type, token_budget)
            current_type_total = type_totals.get(comp.component_type, 0)

            fits_total = total_tokens + comp_tokens <= token_budget
            fits_type = current_type_total + comp_tokens <= comp_budget

            if fits_total and fits_type:
                selected.append(comp)
                total_tokens += comp_tokens
                type_totals[comp.component_type] = current_type_total + comp_tokens
            else:
                # Surface the drop so operators can see when the prompt is
                # being silently truncated by budget pressure. Identifying
                # which constraint tripped (global vs per-type) is the most
                # useful detail when tuning component_budgets.
                reason = (
                    "total_budget"
                    if not fits_total else "type_budget"
                )
                logger.warning(
                    "TokenBudgetStrategy dropped component type=%s priority=%d "
                    "tokens=%d reason=%s (total %d/%d, type %d/%d)",
                    comp.component_type, comp.priority, comp_tokens, reason,
                    total_tokens, token_budget,
                    current_type_total, comp_budget,
                )

        return selected

    def get_strategy_name(self) -> str:
        return "token_budget"


class BufferedStrategy(ContextStrategy):
    """Keep last N components per type."""
    
    def __init__(self, buffer_size: int = 10):
        self.buffer_size = buffer_size
    
    def select_components(
        self,
        components: List[ContextComponent],
        token_budget: int,
        component_budgets: Dict[str, int]
    ) -> List[ContextComponent]:
        type_buckets: Dict[str, List[ContextComponent]] = {}
        
        for comp in components:
            type_buckets.setdefault(comp.component_type, []).append(comp)
        
        selected: List[ContextComponent] = []
        for comp_type, bucket in type_buckets.items():
            recent = bucket[-self.buffer_size:]
            dropped = len(bucket) - len(recent)
            if dropped > 0:
                logger.warning(
                    "BufferedStrategy dropped %d component(s) of type=%s "
                    "(buffer_size=%d, total=%d)",
                    dropped, comp_type, self.buffer_size, len(bucket),
                )
            selected.extend(recent)

        return sorted(selected, key=lambda c: c.priority, reverse=True)

    def get_strategy_name(self) -> str:
        return "buffered"


class PriorityWeightedStrategy(ContextStrategy):
    """Select by weighted importance + relevance scores."""
    
    def __init__(self, relevance_threshold: float = 0.5):
        self.relevance_threshold = relevance_threshold
    
    def select_components(
        self,
        components: List[ContextComponent],
        token_budget: int,
        component_budgets: Dict[str, int]
    ) -> List[ContextComponent]:
        scored_components: List[Tuple[ContextComponent, float]] = []

        for comp in components:
            relevance = comp.metadata.get("relevance_score", 1.0)
            score = comp.priority * 0.7 + relevance * 0.3 * 100
            if relevance >= self.relevance_threshold:
                scored_components.append((comp, score))
            else:
                logger.warning(
                    "PriorityWeightedStrategy dropped component type=%s "
                    "priority=%d relevance=%.3f<threshold=%.3f",
                    comp.component_type, comp.priority,
                    relevance, self.relevance_threshold,
                )

        sorted_components = sorted(scored_components, key=lambda x: x[1], reverse=True)
        selected: List[ContextComponent] = []
        total_tokens = 0

        for comp, score in sorted_components:
            comp_tokens = comp.token_estimate or comp.estimate_tokens()
            if total_tokens + comp_tokens <= token_budget:
                selected.append(comp)
                total_tokens += comp_tokens
            else:
                logger.warning(
                    "PriorityWeightedStrategy dropped component type=%s "
                    "priority=%d score=%.2f tokens=%d (total %d/%d)",
                    comp.component_type, comp.priority, score, comp_tokens,
                    total_tokens, token_budget,
                )

        return selected

    def get_strategy_name(self) -> str:
        return "priority"





AgentConfig.model_rebuild()
