# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare authorized knowledge-tool trials and execute them through AgentOS."""

from uuid import uuid4

from contracts.agentos import AgentToolInvocation, ToolBinding
from contracts.constants import environment
from contracts.errors.exceptions import ToolExecutionException
from management.services.agent.preparation.knowledge_search import (
    prepare_knowledge_search,
)
from nexent.core.agents.agent_model import ToolConfig

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient


async def validate_knowledge_tool(request, tenant_id, user_id):
    if not tenant_id or not user_id:
        raise ToolExecutionException("Tenant ID and User ID are required for knowledge validation")
    params = dict(request.params or {})
    paths = params.pop("document_paths", None)
    config = ToolConfig(name="knowledge_base_search", class_name="KnowledgeBaseSearchTool", source="local", params=params)
    if not await prepare_knowledge_search(config, user_id, tenant_id, paths):
        raise ToolExecutionException("Unsupported knowledge search configuration")
    result = await AgentOSClient(environment.RUNTIME_SERVICE_URL, create_httpx_client).invoke_tool(
        AgentToolInvocation(run_id=uuid4().hex, tool=ToolBinding(tool_id=config.name, version="2",
                                                               parameters=config.metadata["prepared_knowledge_search"]),
                            inputs=request.inputs or {}, language=request.language or "en"), user_id, tenant_id)
    return result.result
