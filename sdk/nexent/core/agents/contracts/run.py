# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from __future__ import annotations

from threading import Event
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
from nexent.core.models.capacity_budget import ContextBudgetSnapshot
from nexent.core.utils.observer import MessageObserver


class AgentHistory(BaseModel):
    role: str = Field(description="Role, can be user or assistant")
    content: str = Field(description="Conversation content")


class AgentRunInfo(BaseModel):
    collaboration_timeout_seconds: float = Field(default=300.0, gt=0,
        description="Total deadline for a nested collaboration including queue wait")
    model_service: Optional[Any] = Field(default=None, exclude=True, repr=False)
    model_deadline: Optional[float] = Field(default=None, exclude=True)
    run_result: Optional[Any] = Field(default=None, exclude=True, description="Explicit public runtime result")
    attempt_outcome: Optional[str] = Field(default=None, description="Typed worker outcome for the application host")
    query: str = Field(description="User query")
    model_config_list: List[ModelConfig] = Field(description="List of model configurations")
    observer: MessageObserver = Field(description="Return data")
    agent_config: AgentConfig = Field(description="Detailed Agent configuration")
    mcp_host: Optional[List[Union[str, Dict[str, Any]]]] = Field(
        description="MCP server address(es). Can be a string (URL) or dict with 'url', 'transport', "
        "and optionally 'authorization', 'headers', or 'httpx_client_factory' keys. "
        "Transport can be 'sse' or 'streamable-http'. If string, transport is auto-detected based on URL ending: "
        "URLs ending with '/sse' use 'sse' transport, URLs ending with '/mcp' use 'streamable-http' transport. "
        "Authorization can be provided as 'authorization' (e.g., 'Bearer token') or as 'headers' dict.",
        default=None,
    )
    mcp_request_timeout_seconds: Optional[float] = Field(
        description=(
            "Maximum seconds allowed to establish an MCP connection and complete "
            "the initialization handshake. It does not limit tool execution."
        ),
        default=None,
    )
    history: Optional[List[AgentHistory]] = Field(description="Historical conversation information", default=None)
    stop_event: Event = Field(description="Stop event control")
    cancellation_scope: Optional[Any] = Field(
        description="Run-scoped cancellation and active resource registry",
        default=None,
        exclude=True,
    )
    mcp_tool_timeout_seconds: float = Field(
        description="Hard timeout for one MCP tool invocation",
        default=60.0,
        gt=0,
    )
    mcp_close_timeout_seconds: float = Field(
        description="Maximum wait for an MCP context to close",
        default=5.0,
        gt=0,
    )
    thread_manager: Optional[Any] = Field(
        description="Injected process-local thread manager",
        default=None,
        exclude=True,
    )
    thread_execution_id: Optional[str] = Field(
        description="Process-local managed execution identifier",
        default=None,
        exclude=True,
    )
    thread_future: Optional[Any] = Field(
        description="Process-local managed execution completion handle",
        default=None,
        exclude=True,
    )
    conversation_id: Optional[int] = Field(description="Conversation id for run-scoped persistence", default=None)
    user_id: Optional[str] = Field(description="User id for run-scoped persistence", default=None)
    user_context: Optional[Dict[str, Any]] = Field(
        description="Caller user context (tenant/user/groups) passed through to tools for "
        "tool-side authorization. Hidden from the model; values come only from the "
        "authenticated session, never from model output.",
        default=None,
        exclude=True,
    )
    runtime_metadata: Dict[str, Any] = Field(
        description="Immutable application-resolved runtime metadata snapshot",
        default_factory=dict,
    )
    runtime_metadata_version: Optional[int] = Field(
        description="Conversation runtime metadata version used by this run",
        default=None,
    )
    context_input: Optional[Any] = Field(
        description="Immutable run-scoped context snapshot supplied by the application boundary.",
        default=None,
    )
    capacity_snapshot: Optional[Dict[str, Any]] = Field(
        description="Resolved model capacity snapshot fields for request monitoring",
        default=None,
    )
    context_budget_snapshot: Optional[ContextBudgetSnapshot] = Field(
        description="Resolved canonical W2 context budget snapshot for request execution",
        default=None,
    )
    enable_planning: bool = Field(description="Whether to enable the planning phase before execution", default=False)
    redis_client: Optional[Any] = Field(
        description="Redis client for plan persistence. "
        "If provided, plan_repo will use Redis as primary storage with local fallback.",
        default=None,
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
    tool_fastpath_enabled: bool = Field(
        description="Enable restricted official-tool actions before ordinary Docker initialization.",
        default=True,
    )
    tool_fastpath_allowed_tools: Optional[List[str]] = Field(
        description="Deployment-approved official implementation IDs for local fast-path actions.",
        default=None,
    )
    minio_client: Optional[Any] = Field(
        description=(
            "MinIO client for syncing sandbox output files to object storage.  "
            "Required when sandbox_config.auto_sync_outputs is True."
        ),
        default=None,
    )
    workspace_path: Optional[str] = Field(
        description="Run-scoped local workspace used for uploaded inputs and generated outputs.",
        default=None,
    )
    workspace_run_id: Optional[str] = Field(
        description="Opaque run identifier used to isolate workspace files and object keys.",
        default=None,
    )
    tenant_id: Optional[str] = Field(
        description="Tenant id used for run-scoped file isolation.",
        default=None,
    )
    minio_files: Optional[List[Dict[str, Any]]] = Field(
        description="Authorized files uploaded with the current run request.",
        default=None,
    )

    class Config:
        arbitrary_types_allowed = True
