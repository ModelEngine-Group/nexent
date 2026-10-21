# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from pydantic import BaseModel


class DiscoverFromUrlRequest(BaseModel):
    """Request to discover an external A2A agent from an Agent Card URL."""

    url: str
    name: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None


class DiscoverFromNacosRequest(BaseModel):
    """Request to discover external A2A agents from Nacos."""

    nacos_config_id: str
    agent_names: List[str]
    namespace: Optional[str] = "public"


class UpdateAgentProtocolRequest(BaseModel):
    """Request to update the protocol type for an external A2A agent."""

    protocol_type: str = Field(description="Protocol type to use: JSONRPC, HTTP+JSON, or GRPC")


class UpdateExternalAgentSecurityCredentialsRequest(BaseModel):
    """Request to configure credentials required by an Agent Card."""

    security_credentials: Dict[str, str] = Field(default_factory=dict)
    selected_security_requirement_index: Optional[int] = Field(default=None, ge=0)


class TestNacosConnectionRequest(BaseModel):
    """Request to test Nacos connectivity without saving the config."""

    nacos_addr: str = Field(description="Nacos server address (e.g., http://nacos-server:8848)")
    nacos_username: Optional[str] = None
    nacos_password: Optional[str] = None
    namespace_id: Optional[str] = "public"


class AddRelationRequest(BaseModel):
    """Request body for adding a relation between local agent and external A2A agent."""

    local_agent_id: int
    external_agent_id: int


class CreateNacosConfigRequest(BaseModel):
    """Request to create a Nacos config."""

    name: str
    nacos_addr: str
    nacos_username: Optional[str] = None
    nacos_password: Optional[str] = None
    namespace_id: Optional[str] = "public"
    description: Optional[str] = None


class UpdateNacosConfigRequest(BaseModel):
    """Request to update a Nacos config."""

    name: Optional[str] = None
    nacos_addr: Optional[str] = None
    nacos_username: Optional[str] = None
    nacos_password: Optional[str] = None
    namespace_id: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ChatRequest(BaseModel):
    """Request to send a chat message to an external A2A agent."""

    message: str = Field(..., description="The chat message to send")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional runtime metadata sent as A2A Message.metadata",
    )
    include_metadata: bool = Field(
        default=False,
        description="Deprecated compatibility field. Internal identity is never sent as runtime metadata.",
    )
