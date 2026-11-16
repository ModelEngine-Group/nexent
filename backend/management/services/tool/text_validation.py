# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compile a text-tool trial in Management and execute it through AgentOS."""

from uuid import uuid4

from contracts.agentos import AgentToolInvocation
from contracts.constants import environment
from contracts.errors.exceptions import ToolExecutionException
from management.services.agent.preparation.analysis import prepare_analysis_tool
from management.services.agent.preparation.evaluation_snapshot import (
    _export_analysis_binding,
)
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.concurrency import run_blocking

from backend.http.client import create_httpx_client
from infrastructure.agentos_client import AgentOSClient


def _binding(params, tenant_id):
    config = ToolConfig(
        name="analyze_text_file",
        class_name="AnalyzeTextFileTool",
        source="local",
        params=params or {},
    )
    if not prepare_analysis_tool(config, tenant_id):
        raise ToolExecutionException("Unsupported text analysis configuration")
    return _export_analysis_binding(config)


async def validate_text_tool(request, tenant_id, user_id):
    if not tenant_id or not user_id:
        raise ToolExecutionException(
            "Tenant ID and User ID are required for text analysis validation"
        )
    binding = await run_blocking(
        "compile-text-tool-trial",
        _binding,
        request.params,
        tenant_id,
        lane="control-io",
        owner="management.services.tool",
    )
    result = await AgentOSClient(
        environment.RUNTIME_SERVICE_URL, create_httpx_client
    ).invoke_tool(
        AgentToolInvocation(
            run_id=uuid4().hex,
            tool=binding,
            inputs=request.inputs or {},
            language=request.language or "en",
        ),
        user_id,
        tenant_id,
    )
    return result.result
