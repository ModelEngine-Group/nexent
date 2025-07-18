from __future__ import annotations
from threading import Event
from typing import Optional, List, Dict, Any
from pydantic import Field, BaseModel
from ..utils.observer import MessageObserver


class ModelConfig(BaseModel):
    cite_name: str = Field(description="Model alias")
    api_key: str = Field(description="API key", default="")
    model_name: str = Field(description="Model call name")
    url: str = Field(description="Model endpoint URL")
    temperature: Optional[float] = Field(description="Temperature", default=0.1)
    top_p: Optional[float] = Field(description="Top P", default=0.95)


class ToolConfig(BaseModel):
    class_name: str = Field(description="Tool class name")
    params: Dict[str, Any] = Field(description="Initialization parameters")
    source: str = Field(description="Tool source, can be local or mcp")
    metadata: Optional[Dict[str, Any]] = Field(description="Metadata", default=None)

class AgentConfig(BaseModel):
    name: str = Field(description="Agent name")
    description: str = Field(description="Agent description")
    prompt_templates: Dict[str, Any] = Field(description="Prompt templates")
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
    mcp_host: Optional[List[str]] = Field(description="MCP server address", default=None)
    history: Optional[List[AgentHistory]] = Field(description="Historical conversation information", default=None)
    stop_event: Event = Field(description="Stop event control")

    class Config:
        arbitrary_types_allowed = True
