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
    managed_agents: List[AgentConfig] = Field(description="Managed Agents", default=[])


class AgentHistory(BaseModel):
    role: str = Field(description="Role, can be user or assistant")
    content : str = Field(description="Conversation content")


class AgentRunInfo(BaseModel):
    query: str = Field(description="User query")
    model_config_list: List[ModelConfig] = Field(description="List of model configurations")
    observer: MessageObserver = Field(description="Return data")
    agent_config: AgentConfig = Field(description="Detailed Agent configuration")
    mcp_host: Optional[List[Union[str, Dict[str, Any]]]] = Field(
        description="MCP server address(es). Can be a string (URL) or dict with 'url' and 'transport' keys. "
        "Transport can be 'sse' or 'streamable-http'. If string, transport is auto-detected based on URL ending: "
        "URLs ending with '/sse' use 'sse' transport, URLs ending with '/mcp' use 'streamable-http' transport.",
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
