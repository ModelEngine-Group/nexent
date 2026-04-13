from __future__ import annotations

from threading import Event
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from ..utils.observer import MessageObserver


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
    max_steps: int = Field(description="Maximum number of steps for current Agent", default=5)
    model_name: str = Field(description="Model alias from ModelConfig")
    provide_run_summary: Optional[bool] = Field(description="Whether to provide run summary to upper-level Agent", default=False)
    instructions: Optional[str] = Field(description="Additional instructions to prepend to system prompt", default=None)
    managed_agents: List["AgentConfig"] = Field(
        description="Internal managed sub-agents created locally",
        default=[]
    )
    external_a2a_agents: List[ExternalA2AAgentConfig] = Field(
        description="External A2A agents called via HTTP requests",
        default=[]
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
        default="JSONRPC"
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
