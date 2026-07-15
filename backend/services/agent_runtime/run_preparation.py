"""Runtime preparation boundary for legacy smolagents-compatible runs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from consts.const import (
    AGENT_RUNTIME_PROVIDER_OPENJIUWEN,
    AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
    LANGUAGE,
)

from .assembly import (
    freeze_agent_run_plan,
    initialize_assembly_state,
    merge_capability_contribution,
    sort_capability_providers,
)
from .config import get_openjiuwen_sandbox_settings
from .models import (
    AgentRunPlan,
    AgentRunRequestContext,
    AgentSpec,
    AssemblyState,
    CapabilityContribution,
    ContextMode,
    ContextPolicy,
    MCPConnectionConfig,
    OperatorSpec,
    PromptBundle,
    RunControl,
    RuntimeWarningInfo,
    SandboxExecutionSpec,
    ToolSource,
)
from .providers import KnowledgeProvider
from .registry import agent_runtime_registry
from .tool_factory import build_production_tool_factory_registry
from .tool_schema import tool_spec_from_legacy_tool_config


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeMemoryPreview:
    """Request-scoped memory state needed by the Runtime API Layer."""

    enabled: bool
    metadata: dict[str, Any]
    user_config: Any | None = None


@dataclass(frozen=True)
class RuntimeRunPreparation:
    """Prepared runtime inputs consumed by the streaming layer."""

    agent_run_info: Any
    memory_context: Any
    plan: AgentRunPlan
    runtime: Any


@dataclass(frozen=True)
class PreparedAgentRunCapabilityProvider:
    """Production provider for an already authorized AgentRunInfo snapshot."""

    contribution: CapabilityContribution
    name: str = "prepared-agent-run"
    priority: int = 0
    depends_on: tuple[str, ...] = ()

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        """Return the request-scoped production contribution."""
        _ = (request, state)
        return self.contribution


def preview_runtime_memory(
    user_id: str,
    tenant_id: str,
    agent_id: int | str,
    *,
    skip_query: bool = False,
) -> RuntimeMemoryPreview:
    """Return memory preview metadata without exposing DB/service calls to API code."""
    from services.memory_config_service import build_memory_context

    memory_context = build_memory_context(
        user_id,
        tenant_id,
        agent_id,
        skip_query=skip_query,
    )
    user_config = getattr(memory_context, "user_config", None)
    return RuntimeMemoryPreview(
        enabled=bool(getattr(user_config, "memory_switch", False)),
        metadata={
            "agent_share_option": getattr(user_config, "agent_share_option", "unknown"),
            "disable_agent_ids": list(
                getattr(user_config, "disable_agent_ids", []) or []
            ),
            "disable_user_agent_ids": list(
                getattr(user_config, "disable_user_agent_ids", []) or []
            ),
        },
        user_config=user_config,
    )


async def prepare_runtime_agent_run(
    agent_request: Any,
    user_id: str,
    tenant_id: str,
    *,
    language: str = LANGUAGE["ZH"],
    allow_memory_search: bool = True,
    run_request_context: AgentRunRequestContext | None = None,
) -> RuntimeRunPreparation:
    """Prepare a legacy AgentRunInfo through the runtime preparation boundary."""
    from agents.create_agent_info import create_agent_run_info
    from services.memory_config_service import build_memory_context

    request_context = run_request_context or _request_context_from_agent_request(
        agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
    )
    logger.info(
        "Agent runtime preparation starting, request_id=%s, provider=%s, agent_id=%s, "
        "conversation_id=%s, debug=%s, allow_memory_search=%s",
        request_context.request_id,
        request_context.runtime_provider,
        request_context.agent_id,
        request_context.conversation_id,
        request_context.is_debug,
        allow_memory_search,
    )
    memory_context = build_memory_context(
        user_id,
        tenant_id,
        agent_request.agent_id,
        skip_query=not allow_memory_search,
    )
    agent_run_info = await create_agent_run_info(
        agent_id=agent_request.agent_id,
        minio_files=agent_request.minio_files,
        query=agent_request.query,
        history=agent_request.history,
        tenant_id=tenant_id,
        user_id=user_id,
        language=language,
        allow_memory_search=allow_memory_search,
        is_debug=agent_request.is_debug,
        override_version_no=agent_request.version_no,
        override_model_id=agent_request.model_id,
        requested_output_tokens=agent_request.requested_output_tokens,
        tool_params=agent_request.tool_params,
    )

    enhance_legacy_knowledge_tools(agent_run_info, request_context)
    plan = agent_run_plan_from_legacy_info(agent_run_info, request_context)
    logger.info(
        "Agent run plan assembled, request_id=%s, provider=%s, agent_id=%s, "
        "agent_name=%s, conversation_id=%s, history_count=%d, tool_count=%d, "
        "mcp_count=%d, required_capabilities=%s, optional_capabilities=%s, warning_count=%d",
        plan.request_id,
        plan.runtime_provider,
        plan.root_agent.agent_id,
        plan.root_agent.name,
        plan.run_control.conversation_id,
        len(plan.history or []),
        _visible_tool_count(plan),
        len(plan.mcp_connections),
        _sorted_capabilities(plan.capability_requirements.required),
        _sorted_capabilities(plan.capability_requirements.optional),
        len(plan.monitoring_metadata.get("assembly_warnings") or []),
    )
    runtime = agent_runtime_registry.get(
        request_context.runtime_provider,
        plan.capability_requirements,
    )
    logger.info(
        "Agent runtime preparation finished, request_id=%s, provider=%s, runtime_class=%s",
        plan.request_id,
        request_context.runtime_provider,
        type(runtime).__name__,
    )
    _mount_conversation_context_manager(agent_request, agent_run_info)
    _register_prepared_run(
        agent_request,
        agent_run_info,
        user_id=user_id,
        run_request_context=run_request_context,
        run_control=plan.run_control,
    )
    return RuntimeRunPreparation(
        agent_run_info=agent_run_info,
        memory_context=memory_context,
        plan=plan,
        runtime=runtime,
    )


def agent_run_plan_from_legacy_info(
    agent_run_info: Any,
    request_context: AgentRunRequestContext,
) -> AgentRunPlan:
    """Convert the production legacy assembly result into a neutral run plan."""
    effective_request = request_context.model_copy(
        update={
            "query": str(getattr(agent_run_info, "query", request_context.query) or ""),
            "history": [
                _model_dump(item)
                for item in (getattr(agent_run_info, "history", None) or [])
            ],
        }
    )
    state = initialize_assembly_state(
        effective_request,
        version_no=(
            request_context.version_no
            if request_context.version_no is not None
            else 0
            if request_context.is_debug
            else None
        ),
    )
    for provider in sort_capability_providers(
        build_production_capability_providers(agent_run_info, request_context)
    ):
        merge_capability_contribution(
            state,
            provider.contribute(effective_request, state),
        )
    run_control = RunControl(
        request_id=request_context.request_id,
        user_id=request_context.user_id,
        conversation_id=request_context.conversation_id,
        legacy_stop_event=getattr(agent_run_info, "stop_event", None),
        metadata={
            "tenant_id": request_context.tenant_id,
            "language": request_context.language,
        },
    )
    return freeze_agent_run_plan(
        effective_request,
        state,
        run_control=run_control,
    )


def build_production_capability_providers(
    agent_run_info: Any,
    request_context: AgentRunRequestContext,
) -> list[PreparedAgentRunCapabilityProvider]:
    """Build non-NoOp production providers from the authorized run snapshot."""
    root_agent = _agent_spec_from_legacy_config(
        agent_run_info.agent_config,
        agent_id=request_context.agent_id,
        runtime_provider=request_context.runtime_provider,
    )
    mcp_connections = [
        connection
        for connection in (
            _mcp_connection_from_legacy_host(host, root_agent)
            for host in (getattr(agent_run_info, "mcp_host", None) or [])
        )
        if connection is not None
    ]
    runtime_resources = {
        "tool_factory_registry": build_production_tool_factory_registry(),
        "smolagents.observer": getattr(agent_run_info, "observer", None),
    }
    skill_tools_enabled = any(
        tool.source in {ToolSource.SKILL, ToolSource.BUILTIN}
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
        for tool in root_agent.tools
    )
    run_skill_script_enabled = any(
        tool.source in {ToolSource.SKILL, ToolSource.BUILTIN}
        and (tool.class_name or tool.name) == "RunSkillScriptTool"
        for tool in root_agent.tools
    )
    if skill_tools_enabled:
        runtime_resources["runtime.tool_artifacts_enabled"] = True

    sandbox_execution = None
    sandbox_monitoring = {"sandbox.enabled": False}
    if (
        request_context.runtime_provider == AGENT_RUNTIME_PROVIDER_OPENJIUWEN
        and run_skill_script_enabled
    ):
        sandbox_settings = get_openjiuwen_sandbox_settings()
        sandbox_monitoring = {
            "sandbox.enabled": sandbox_settings.enabled,
            "sandbox.provider": sandbox_settings.provider,
        }
        if sandbox_settings.base_url:
            sandbox_monitoring["sandbox.endpoint_host_hash"] = (
                _endpoint_host_hash(sandbox_settings.base_url)
            )
        if sandbox_settings.enabled:
            host_staging_root = os.path.join(
                tempfile.gettempdir(), "nexent-sandbox"
            )
            runtime_resources.update(
                {
                    "sandbox.attachments": _local_attachment_mapping(
                        request_context.minio_files
                    ),
                    "sandbox.host_staging_dirs": [],
                    "sandbox.host_staging_root": host_staging_root,
                    "skill.upload_allowed_roots": [host_staging_root],
                }
            )
            sandbox_execution = SandboxExecutionSpec(
                enabled=True,
                required=True,
                purpose="skill_script",
                profile="fixed_aio",
                execution_timeout_seconds=(
                    sandbox_settings.execution_timeout_seconds
                ),
                workspace_policy={
                    "root": sandbox_settings.workspace_root,
                    "request_scoped": True,
                    "shared_container": True,
                    "concurrent": True,
                },
            )

    context_compatibility = dict(
        root_agent.runtime_hints.get("context_compatibility") or {}
    )
    warnings = []
    if context_compatibility.get("legacy_managed_normalized"):
        warnings.append(
            RuntimeWarningInfo(
                code="context_policy_normalized",
                message=(
                    "OpenJiuwen uses runtime-native context for the legacy default "
                    "context manager; Nexent managed compression is not enabled."
                ),
                metadata=context_compatibility,
            )
        )

    contribution = CapabilityContribution(
        agent_record={"agent_id": request_context.agent_id},
        model_configs=[
            _model_dump(config)
            for config in (getattr(agent_run_info, "model_config_list", None) or [])
        ],
        root_agent=root_agent,
        sandbox_execution=sandbox_execution,
        mcp_connections=mcp_connections,
        runtime_resources=runtime_resources,
        operators=(
            [
                OperatorSpec(
                    name="skill_file_upload",
                    stages={"after_tool_call", "after_run"},
                    priority=400,
                    required=False,
                )
            ]
            + (
                [
                    OperatorSpec(
                        name="sandbox_staging_cleanup",
                        stages={"after_tool_call", "after_run", "on_error"},
                        priority=450,
                        required=False,
                    )
                ]
                if sandbox_execution is not None
                else []
            )
        )
        if skill_tools_enabled
        else [],
        warnings=warnings,
        monitoring_metadata={
            "language": request_context.language,
            "tenant_id": request_context.tenant_id,
            "assembly_path": "production_prepared_provider",
            **sandbox_monitoring,
        },
    )
    return [PreparedAgentRunCapabilityProvider(contribution=contribution)]


def _sorted_capabilities(values: Any) -> list[str]:
    return sorted(str(value) for value in (values or []))


def _visible_tool_count(plan: AgentRunPlan) -> int:
    return sum(
        1
        for tool in plan.root_agent.tools
        if str(getattr(tool.visibility, "value", tool.visibility)) != "internal"
    )


def _endpoint_host_hash(base_url: str) -> str:
    """Return a stable non-sensitive endpoint identifier for monitoring."""
    parsed = urlparse(base_url)
    host = parsed.netloc or parsed.path
    return hashlib.sha256(host.encode("utf-8")).hexdigest()[:12]


def _local_attachment_mapping(
    minio_files: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Return only explicitly supplied, existing local attachment paths."""
    attachments: dict[str, str] = {}
    for item in minio_files or []:
        if not isinstance(item, dict):
            continue
        raw_path = next(
            (
                item.get(key)
                for key in ("absolute_path", "local_path", "path")
                if item.get(key)
            ),
            None,
        )
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute() or not path.is_file():
            continue
        attachments[str(path.resolve())] = str(item.get("name") or path.name)
    return attachments


def _agent_spec_from_legacy_config(
    agent_config: Any,
    *,
    agent_id: Any,
    runtime_provider: str,
) -> AgentSpec:
    prompt_templates = dict(getattr(agent_config, "prompt_templates", None) or {})
    prompt_fragments = dict(getattr(agent_config, "prompt_fragments", None) or {})
    tools = []
    for tool_config in getattr(agent_config, "tools", None) or []:
        tool = tool_spec_from_legacy_tool_config(tool_config)
        class_name = tool.class_name or tool.name
        metadata = dict(tool.metadata or {})
        if (
            metadata.get("capability") == "knowledge"
            or class_name == "KnowledgeBaseSearchTool"
        ):
            tool = tool.model_copy(update={"source": ToolSource.KNOWLEDGE})
        elif class_name in {"SearchMemoryTool", "StoreMemoryTool"}:
            tool = tool.model_copy(update={"source": ToolSource.MEMORY})
        tools.append(tool)

    context_policy, legacy_managed_normalized = _legacy_context_policy(
        getattr(agent_config, "context_manager_config", None),
        runtime_provider=runtime_provider,
    )
    return AgentSpec(
        agent_id=agent_id,
        name=str(getattr(agent_config, "name", None) or "root"),
        description=str(getattr(agent_config, "description", None) or ""),
        model_name=str(getattr(agent_config, "model_name", None) or "main_model"),
        max_steps=int(getattr(agent_config, "max_steps", 15) or 15),
        prompt=PromptBundle(
            fragments=prompt_fragments,
            context_components=list(
                getattr(agent_config, "context_components", None) or []
            ),
            rendered_legacy_system_prompt=prompt_templates.get("system_prompt"),
            templates=prompt_templates,
        ),
        tools=tools,
        managed_agents=[
            _agent_spec_from_legacy_config(
                child,
                agent_id=f"{agent_id}:{index}",
                runtime_provider=runtime_provider,
            )
            for index, child in enumerate(
                getattr(agent_config, "managed_agents", None) or [],
                start=1,
            )
        ],
        external_a2a_agents=list(
            getattr(agent_config, "external_a2a_agents", None) or []
        ),
        context_policy=context_policy,
        verification_config=_model_dump(
            getattr(agent_config, "verification_config", None)
        ),
        runtime_hints={
            "requested_output_tokens": getattr(
                agent_config,
                "requested_output_tokens",
                None,
            ),
            "provide_run_summary": bool(
                getattr(agent_config, "provide_run_summary", False)
            ),
            "instructions": getattr(agent_config, "instructions", None),
            "capacity_snapshot": getattr(agent_config, "capacity_snapshot", None),
            "safe_input_budget_snapshot": getattr(
                agent_config,
                "safe_input_budget_snapshot",
                None,
            ),
            "context_compatibility": {
                "legacy_managed_normalized": legacy_managed_normalized,
                "source_mode": ContextMode.MANAGED.value,
                "target_mode": context_policy.mode.value,
            }
            if legacy_managed_normalized
            else {},
        },
    )


def _legacy_context_policy(
    context_manager_config: Any,
    *,
    runtime_provider: str,
) -> tuple[ContextPolicy, bool]:
    """Normalize the legacy default context manager for the selected runtime."""
    enabled = bool(getattr(context_manager_config, "enabled", False))
    compression = dict(getattr(context_manager_config, "compression", None) or {})
    legacy_managed_normalized = (
        enabled
        and runtime_provider == AGENT_RUNTIME_PROVIDER_OPENJIUWEN
        and not compression
    )
    if legacy_managed_normalized:
        context_mode = ContextMode.RUNTIME_NATIVE
    elif enabled:
        context_mode = ContextMode.MANAGED
    else:
        context_mode = ContextMode.LEGACY
    return (
        ContextPolicy(
            mode=context_mode,
            token_threshold=getattr(context_manager_config, "token_threshold", None),
            soft_input_budget_tokens=getattr(
                context_manager_config,
                "soft_input_budget_tokens",
                None,
            ),
            hard_input_budget_tokens=getattr(
                context_manager_config,
                "hard_input_budget_tokens",
                None,
            ),
            compression=compression,
        ),
        legacy_managed_normalized,
    )


def _mcp_connection_from_legacy_host(
    host: Any,
    root_agent: AgentSpec,
) -> MCPConnectionConfig | None:
    data = dict(host) if isinstance(host, dict) else {"url": str(host)}
    url = str(data.get("url") or "")
    if not url:
        return None
    configured_name = str(data.get("name") or "")
    usage_names = sorted(
        {
            str(tool.usage)
            for tool in root_agent.tools
            if tool.source == ToolSource.MCP and tool.usage
        }
    )
    name = configured_name or (usage_names[0] if len(usage_names) == 1 else url)
    transport = str(data.get("transport") or "")
    if transport not in {"sse", "streamable-http"}:
        transport = "sse" if url.endswith("/sse") else "streamable-http"
    headers = dict(data.get("headers") or {})
    if data.get("authorization") and "Authorization" not in headers:
        headers["Authorization"] = str(data["authorization"])
    return MCPConnectionConfig(
        name=name,
        url=url,
        transport=transport,
        headers=headers,
        required=True,
    )


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    return {key: item for key, item in vars(value).items() if not key.startswith("_")}


def enhance_legacy_knowledge_tools(
    agent_run_info: Any,
    request_context: AgentRunRequestContext,
) -> None:
    """Enhance legacy KB ToolConfig values through KnowledgeProvider output."""
    agent_config = getattr(agent_run_info, "agent_config", None)
    tools = getattr(agent_config, "tools", None)
    if not isinstance(tools, list):
        return

    knowledge_positions: list[int] = []
    knowledge_specs = []
    for index, tool_config in enumerate(tools):
        class_name = str(getattr(tool_config, "class_name", "") or "")
        if class_name != "KnowledgeBaseSearchTool":
            continue
        metadata = getattr(tool_config, "metadata", None) or {}
        if isinstance(metadata, dict) and metadata.get("capability") == "knowledge":
            continue
        knowledge_positions.append(index)
        knowledge_specs.append(tool_spec_from_legacy_tool_config(tool_config))

    if not knowledge_specs:
        return

    agent_name = str(getattr(agent_config, "name", "") or "root")
    provider = _default_knowledge_provider()
    contribution = provider.contribute(
        request_context,
        AssemblyState(
            agent_record={"name": agent_name},
            tools_by_agent={
                agent_name: [
                    spec.model_dump() if hasattr(spec, "model_dump") else spec
                    for spec in knowledge_specs
                ]
            },
        ),
    )
    enhanced_specs = list(contribution.tools_by_agent.get(agent_name, []))
    if len(enhanced_specs) != len(knowledge_positions):
        raise ValueError(
            "KnowledgeProvider did not return all enhanced knowledge tools."
        )

    updated_tools = list(tools)
    for position, enhanced_spec in zip(knowledge_positions, enhanced_specs):
        original_source = getattr(updated_tools[position], "source", "local")
        updated_tools[position] = _legacy_tool_config_from_spec(
            enhanced_spec,
            source=original_source,
        )
    agent_config.tools = updated_tools


def _legacy_tool_config_from_spec(
    tool_spec: Any,
    *,
    source: str,
) -> Any:
    from nexent.core.agents.agent_model import ToolConfig

    inputs = tool_spec.raw_inputs
    if inputs is None:
        inputs = json.dumps(tool_spec.input_schema or {}, ensure_ascii=False)
    return ToolConfig(
        class_name=tool_spec.class_name or tool_spec.name,
        name=tool_spec.name,
        description=tool_spec.description,
        inputs=inputs,
        output_type=tool_spec.output_type,
        params=dict(tool_spec.params),
        source=source,
        usage=tool_spec.usage,
        metadata=dict(tool_spec.metadata or {}),
    )


def _default_knowledge_provider() -> KnowledgeProvider:
    from database.knowledge_db import get_knowledge_name_map_by_index_names
    from services.vectordatabase_service import (
        ElasticSearchService,
        get_embedding_model_by_index_name,
        get_rerank_model,
        get_vector_db_core,
    )

    return KnowledgeProvider(
        embedding_model_resolver=get_embedding_model_by_index_name,
        rerank_model_resolver=get_rerank_model,
        vector_db_resolver=get_vector_db_core,
        knowledge_name_map_resolver=get_knowledge_name_map_by_index_names,
        knowledge_summary_resolver=lambda index_name: (
            ElasticSearchService().get_summary(index_name=index_name)
        ),
    )


def _mount_conversation_context_manager(
    agent_request: Any, agent_run_info: Any
) -> None:
    from agents.agent_run_manager import agent_run_manager

    agent_config = getattr(agent_run_info, "agent_config", None)
    cm_config = getattr(agent_config, "context_manager_config", None)
    if not (cm_config and getattr(cm_config, "enabled", False)):
        return
    agent_run_info.context_manager = agent_run_manager.get_or_create_context_manager(
        conversation_id=str(agent_request.conversation_id),
        config=cm_config,
        max_steps=agent_config.max_steps,
    )


def _register_prepared_run(
    agent_request: Any,
    agent_run_info: Any,
    *,
    user_id: str,
    run_request_context: AgentRunRequestContext | None,
    run_control: RunControl,
) -> None:
    from agents.agent_run_manager import agent_run_manager

    if run_request_context is not None:
        agent_run_manager.register_agent_run(
            agent_request.conversation_id,
            agent_run_info,
            user_id,
            request_id=run_request_context.request_id,
            runtime_provider=run_request_context.runtime_provider,
            run_control=run_control,
        )
        return
    agent_run_manager.register_agent_run(
        agent_request.conversation_id,
        agent_run_info,
        user_id,
        run_control=run_control,
    )


def _request_context_from_agent_request(
    agent_request: Any,
    *,
    user_id: str,
    tenant_id: str,
    language: str,
) -> AgentRunRequestContext:
    return AgentRunRequestContext(
        request_id="legacy-runtime-preparation",
        runtime_provider=AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        agent_id=int(agent_request.agent_id or 0),
        conversation_id=agent_request.conversation_id,
        query=agent_request.query or "",
        history=agent_request.history,
        minio_files=agent_request.minio_files,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        is_debug=bool(agent_request.is_debug),
        version_no=agent_request.version_no,
        override_model_id=agent_request.model_id,
        requested_output_tokens=agent_request.requested_output_tokens,
        tool_params=agent_request.tool_params,
    )
