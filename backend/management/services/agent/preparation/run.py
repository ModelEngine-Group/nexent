# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compile Agent resources for AgentOS and the temporary in-process fallback."""

import logging
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from contracts.agentos import PreparedConversationScope, TurnModelGeneration
from contracts.constants.environment import (
    AGENT_WORKSPACE_ROOT,
    MCP_REQUEST_TIMEOUT_SECONDS,
    NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS,
    NEXENT_TOOL_FASTPATH_ENABLED,
    RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
    RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
    TOKEN,
)
from contracts.tool import ToolParamsRequest
from backend.http.client import create_httpx_client
from infrastructure.agent_model_overrides import apply_turn_model_generation, merge_provider_body
from infrastructure.redis.client import get_redis_client
from management.db.agent.repository import search_agent_info_by_agent_id
from management.db.agent.version import query_current_version_no, update_agent_snapshot
from infrastructure.object_storage.client import minio_client
from management.db.model.repository import get_model_by_model_id
from management.services.agent.preparation.compiler import create_agent_config
from management.services.agent.preparation.inputs import (
    _build_run_workspace,
    _collect_run_minio_files,
    _convert_history_with_minio_files,
    _materialize_runtime_skill_snapshot,
    _validate_run_minio_files,
    join_minio_file_description_to_query,
)
from management.services.agent.preparation.tools import filter_mcp_servers_and_tools
from management.services.agent.tool_identity import resolve_tool_user_context
from management.services.file.service import validate_urls_access
from management.services.mcp.addressing import get_tenant_local_mcp_server
from management.services.mcp.service import get_remote_mcp_server_list
from management.services.model.run_bindings import create_model_config_list
from management.services.model.run_budget import _OPERATOR_OVERRIDE_FIELDS
from nexent.core.agents.agent_model import AgentConfig, ModelConfig

if TYPE_CHECKING:
    from management.services.agent.workbench import PreparedWorkbench
    from nexent.core.agents.agent_model import AgentRunInfo


logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)

LegacyRunMaterializer = Callable[..., "AgentRunInfo"]


def _ensure_agent_reasoning_snapshot(
    agent_id: int,
    tenant_id: str,
    version_no: int,
) -> None:
    """Backfill reasoning ownership for agents created before Scheme B."""
    from management.services.agent.reasoning import snapshot_agent_reasoning_config

    try:
        agent_info = search_agent_info_by_agent_id(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        if not agent_info:
            return
        current_overrides = agent_info.get("model_params_override")
        updated_overrides = snapshot_agent_reasoning_config(
            model_ids=agent_info.get("model_ids"),
            requested_overrides=current_overrides,
            existing_overrides=current_overrides,
            tenant_id=agent_info.get("tenant_id") or tenant_id,
        )
        if updated_overrides == current_overrides:
            return
        update_agent_snapshot(
            agent_id=agent_id,
            tenant_id=agent_info.get("tenant_id") or tenant_id,
            version_no=version_no,
            agent_data={"model_params_override": updated_overrides},
        )
    except Exception as exc:  # pragma: no cover - defensive migration fallback
        logger.warning(
            "Failed to backfill agent reasoning snapshot for agent %s: %s",
            agent_id,
            exc,
        )


def apply_root_generation_overlay(
    model_list: List[ModelConfig],
    agent_config: AgentConfig,
    generation_config: Optional[Dict[str, Any]],
) -> str | None:
    """Add a root-only model alias without changing child Agent aliases."""
    if not generation_config:
        return
    from management.services.model.run_controls import overlay_root_model

    for model_config in model_list:
        if model_config.cite_name != agent_config.model_name:
            continue
        root_model = overlay_root_model(
            model_config,
            generation_config,
            "workbench_root_model",
        )
        model_list.append(root_model)
        agent_config.model_name = root_model.cite_name
        return model_config.cite_name
    return None


async def create_agent_run_info(
    agent_id,
    minio_files,
    query,
    history,
    tenant_id: str,
    user_id: str,
    language: str = "zh",
    allow_memory_search: bool = True,
    is_debug: bool = False,
    override_version_no: int | None = None,
    override_model_id: int | None = None,
    reasoning_effort: str | None = None,
    reasoning_budget_tokens: int | None = None,
    requested_output_tokens: int | None = None,
    tool_params: Optional[ToolParamsRequest | Dict[str, Any]] = None,
    conversation_id: Optional[int] = None,
    context_policy: Optional[Dict[str, Any]] = None,
    enable_planning: bool = False,
    enable_automation_tool: bool = True,
    runtime_knowledge_context: Optional[Dict[str, str]] = None,
    runtime_skill_snapshot: Optional[List[Dict[str, Any]]] = None,
    runtime_knowledge_tools: Optional[List[Dict[str, Any]]] = None,
    runtime_generation_config: Optional[Dict[str, Any]] = None,
    runtime_sub_agent_mounts: Optional[List[Dict[str, Any]]] = None,
    export_evaluation: bool = False,
    export_debug_planning: bool = False,
    resource_versions: dict | None = None,
    prepared_conversation: PreparedConversationScope | None = None,
    prepared_workbench: "PreparedWorkbench | None" = None,
    turn_generation: TurnModelGeneration | None = None,
    authorized_knowledge_tools: dict | None = None,
    *,
    legacy_materializer: LegacyRunMaterializer | None = None,
):
    export_resources = export_evaluation or prepared_conversation is not None
    if not export_resources and legacy_materializer is None:
        raise ValueError("Legacy run preparation requires a Runtime materializer")
    if override_model_id is not None:
        from management.services.model.run_controls import validate_selected_record

        validate_selected_record(
            get_model_by_model_id(override_model_id, tenant_id=tenant_id)
        )
    workspace_run_id = uuid.uuid4().hex
    workspace_path = _build_run_workspace(user_id, workspace_run_id)
    if runtime_skill_snapshot is not None and not export_resources:
        runtime_skill_snapshot = _materialize_runtime_skill_snapshot(
            runtime_skill_snapshot,
            workspace_path,
            tenant_id,
        )
    if export_resources:
        from management.services.agent.preparation.evaluation_snapshot import build_evaluation_input

        try:
            run_input = build_evaluation_input(query, minio_files, history, user_id, tenant_id)
        except (TypeError, ValueError):
            return None
    else:
        effective_minio_files = _collect_run_minio_files(minio_files, history)
        _validate_run_minio_files(effective_minio_files, user_id, tenant_id)
    runtime_file_context = {
        "workspace_path": workspace_path,
        "minio_client": minio_client,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "run_id": workspace_run_id,
        "validate_url_access": lambda urls: validate_urls_access(
            urls, user_id, tenant_id
        ),
    }

    # Determine which version_no to use based on is_debug flag
    # If is_debug=false, use the current published version (current_version_no)
    # If is_debug=true, use version 0 (draft/editing state)
    if override_version_no is not None:
        version_no = override_version_no
    elif is_debug:
        version_no = 0
    else:
        version_no = query_current_version_no(agent_id=agent_id, tenant_id=tenant_id)
        if version_no is None:
            version_no = 0
            logger.info(
                f"Agent {agent_id} has no published version, using draft version 0"
            )

    _ensure_agent_reasoning_snapshot(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
    )

    final_query = query if export_resources else await join_minio_file_description_to_query(
        minio_files=minio_files,
        query=query,
        history=history,
        language=language,
    )
    model_versions = {} if resource_versions is not None else None
    model_options = {"versions": model_versions} if model_versions is not None else {}
    model_list = await create_model_config_list(tenant_id, **model_options)
    create_config_kwargs = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "language": language,
        "last_user_query": final_query,
        "allow_memory_search": allow_memory_search,
        "version_no": version_no,
        "conversation_id": conversation_id,
        "enable_planning": enable_planning,
        "runtime_file_context": runtime_file_context,
    }
    if export_resources:
        create_config_kwargs["portable_evaluation"] = True
    if runtime_knowledge_context is not None:
        create_config_kwargs["runtime_knowledge_context"] = runtime_knowledge_context
    if authorized_knowledge_tools is not None:
        create_config_kwargs["authorized_knowledge_tools"] = authorized_knowledge_tools
    if runtime_skill_snapshot is not None:
        create_config_kwargs["runtime_skill_snapshot"] = runtime_skill_snapshot
    if enable_automation_tool and not is_debug and conversation_id is not None:
        create_config_kwargs.update(
            {
                "include_automation_tool": True,
                "automation_user_message": query,
                "automation_model_id": override_model_id,
                "automation_has_attachments": bool(minio_files),
            }
        )
    if override_model_id is not None:
        create_config_kwargs["override_model_id"] = override_model_id
    if requested_output_tokens is not None:
        create_config_kwargs["request_requested_output_tokens"] = (
            requested_output_tokens
        )
    if context_policy is not None:
        create_config_kwargs["request_context_policy"] = context_policy

    if runtime_knowledge_tools is not None:
        create_config_kwargs["runtime_knowledge_tools"] = runtime_knowledge_tools
    if runtime_sub_agent_mounts is not None:
        create_config_kwargs["runtime_sub_agent_mounts"] = runtime_sub_agent_mounts
    agent_config = await create_agent_config(
        **create_config_kwargs, tool_params=tool_params
    )

    # v2.6.0: Apply per-agent model params override to model_config_list.
    # model_params_override is a {model_id_str: {temperature, top_p, extra_params}} dict
    # stored on ag_tenant_agent_t. We match each override entry to a ModelConfig
    # by display_name (the cite_name used in model_config_list) and merge the
    # override values on top of the model-level defaults.
    _agent_info_for_override = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )
    model_params_override = (_agent_info_for_override or {}).get(
        "model_params_override"
    ) or {}
    if model_params_override:
        for model_id_str, override_entry in model_params_override.items():
            if not isinstance(override_entry, dict):
                continue
            try:
                override_model_id = int(model_id_str)
            except (ValueError, TypeError):
                continue
            override_model_info = get_model_by_model_id(
                override_model_id, tenant_id=tenant_id
            )
            if not override_model_info:
                continue
            display_name = override_model_info.get("display_name")
            if not display_name:
                continue
            for mc in model_list:
                if mc.cite_name == display_name:
                    if override_entry.get("temperature") is not None:
                        mc.temperature = override_entry["temperature"]
                    if override_entry.get("top_p") is not None:
                        mc.top_p = override_entry["top_p"]
                    # v2.6.0: capacity fields are overridable per-agent. The
                    # authoritative consumer for request shaping is the W1/W2
                    # resolution (agent-selected model), this keeps each
                    # ModelConfig consistent with its override entry.
                    for field in _OPERATOR_OVERRIDE_FIELDS:
                        if override_entry.get(field) is not None:
                            setattr(mc, field, override_entry[field])
                    override_extra = override_entry.get("extra_params")
                    if override_extra and isinstance(override_extra, dict):
                        for k, v in override_extra.items():
                            if k == "enable_thinking":
                                if isinstance(v, bool):
                                    mc.enable_thinking = v
                                    if not v:
                                        mc.reasoning_effort = None
                                        mc.reasoning_budget_tokens = None
                                continue
                            if k == "reasoning_effort":
                                if isinstance(v, str):
                                    mc.reasoning_effort = v
                                continue
                            if k == "reasoning_budget_tokens":
                                if (
                                    isinstance(v, int)
                                    and not isinstance(v, bool)
                                    and v > 0
                                ):
                                    mc.reasoning_budget_tokens = v
                                continue
                        mc.extra_body = merge_provider_body(mc.extra_body, override_extra)
                    if override_entry.get("reasoning_effort") is not None:
                        mc.reasoning_effort = override_entry["reasoning_effort"]
                    if override_entry.get("reasoning_budget_tokens") is not None:
                        budget = override_entry["reasoning_budget_tokens"]
                        if (
                            isinstance(budget, int)
                            and not isinstance(budget, bool)
                            and budget > 0
                        ):
                            mc.reasoning_budget_tokens = budget
                    break
    # Request-scoped settings apply only to the root model.
    if turn_generation is not None:
        selected = next((model for model in model_list if model.cite_name == agent_config.model_name), None)
        if selected is None:
            return None
        source_model_alias = selected.cite_name
        root = apply_turn_model_generation(selected, turn_generation, "turn_root_model")
        model_list.append(root)
        agent_config.model_name = root.cite_name
    else:
        source_model_alias = apply_root_generation_overlay(model_list, agent_config, runtime_generation_config)

    # Retain legacy in-process and Workbench reasoning handling.
    if turn_generation is None and (reasoning_effort is not None or reasoning_budget_tokens is not None):
        from management.services.model.run_controls import overlay_root_model

        selected_config = next(
            (m for m in model_list if m.cite_name == agent_config.model_name), None
        )
        if selected_config is None:
            from contracts.errors.exceptions import RunModelControlsError

            raise RunModelControlsError("model_not_available")
        legacy = {}
        if reasoning_effort is not None:
            legacy["thinking_effort"] = reasoning_effort
        if reasoning_budget_tokens is not None:
            legacy["reasoning_budget_tokens"] = reasoning_budget_tokens
        overlay = overlay_root_model(selected_config, legacy, selected_config.cite_name)
        index = model_list.index(selected_config)
        model_list[index] = overlay

    if export_resources:
        from management.services.agent.preparation.evaluation_snapshot import export_snapshot

        export_options = {}
        if turn_generation is not None:
            export_options.update(turn_generation=turn_generation, source_model_alias=source_model_alias)
        if export_debug_planning:
            export_options["allow_debug_planning"] = True
        if prepared_workbench is not None:
            from management.services.agent.workbench import compile_runtime_mount_plan

            if source_model_alias is None:
                return None
            agent_config = compile_runtime_mount_plan(prepared_workbench.plan, agent_config).root.agent_config
            export_options.update(
                root_generation=prepared_workbench.config.generation_config,
                source_model_alias=source_model_alias,
                workbench_skills=prepared_workbench.plan.root_skills,
                workbench_knowledge_tools=prepared_workbench.knowledge_tools,
            )
            if reasoning_effort is not None or reasoning_budget_tokens is not None:
                export_options["turn_generation"] = TurnModelGeneration(
                    reasoning_effort=reasoning_effort, reasoning_budget_tokens=reasoning_budget_tokens,
                )
        return export_snapshot(
            agent_config, model_list, final_query, None, run_input=run_input,
            tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id, language=language,
            agent_model_overrides=model_params_override, prepared_conversation=prepared_conversation,
            **export_options,
        )

    if resource_versions is not None:
        resource_versions.update(agent_id=int(agent_id), agent_version_no=version_no)
        model_id, revision = model_versions.get(agent_config.model_name, (None, None))
        if model_id is not None:
            resource_versions.update(model_id=int(model_id), model_revision=revision)

    remote_mcp_list = await get_remote_mcp_server_list(
        tenant_id=tenant_id, is_need_auth=True
    )
    default_mcp_url = get_tenant_local_mcp_server(tenant_id)
    remote_mcp_list.append(
        {
            "remote_mcp_server_name": "outer-apis",
            "remote_mcp_server": default_mcp_url,
            "status": True,
            "authorization_token": None,
        }
    )
    remote_mcp_dict = {
        record["remote_mcp_server_name"]: record
        for record in remote_mcp_list
        if record["status"]
    }

    # Filter MCP servers and tools, and build mcp_host with authorization
    used_mcp_urls = filter_mcp_servers_and_tools(agent_config, remote_mcp_dict)

    # Build mcp_host list with authorization tokens and custom headers
    mcp_host = []
    for url in used_mcp_urls:
        # Find the MCP record for this URL
        mcp_record = None
        for record in remote_mcp_list:
            if record.get("remote_mcp_server") == url and record.get("status"):
                mcp_record = record
                break

        if mcp_record:
            mcp_config = {
                "url": url,
                "transport": "sse" if url.endswith("/sse") else "streamable-http",
            }
            if url == default_mcp_url:
                mcp_config["httpx_client_factory"] = create_httpx_client
                mcp_config["headers"] = {
                    "X-Tenant-ID": str(tenant_id),
                    "X-Nexent-Internal-Token": TOKEN,
                }
            headers = {}
            auth_token = mcp_record.get("authorization_token")
            if auth_token:
                headers["Authorization"] = auth_token
            custom_headers = mcp_record.get("custom_headers")
            if custom_headers and isinstance(custom_headers, dict):
                headers.update(custom_headers)
            if headers:
                mcp_config["headers"] = headers
            mcp_host.append(mcp_config)
        else:
            # Fallback to string format if record not found
            mcp_host.append(url)

    # Convert HistoryItem (from API) to AgentHistory (expected by SDK)
    converted_history = _convert_history_with_minio_files(history, language=language)

    return legacy_materializer(
        workspace_root=AGENT_WORKSPACE_ROOT,
        query=final_query,
        model_config_list=model_list,
        language=language,
        agent_config=agent_config,
        mcp_host=mcp_host,
        mcp_request_timeout_seconds=MCP_REQUEST_TIMEOUT_SECONDS,
        history=converted_history,
        mcp_tool_timeout_seconds=RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
        mcp_close_timeout_seconds=RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
        capacity_snapshot=getattr(agent_config, "capacity_snapshot", None),
        context_budget_snapshot=getattr(
            agent_config,
            "context_budget_snapshot",
            None,
        ),
        tool_fastpath_enabled=NEXENT_TOOL_FASTPATH_ENABLED,
        tool_fastpath_allowed_tools=list(NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS),
        workspace_path=workspace_path,
        workspace_run_id=workspace_run_id,
        tenant_id=tenant_id,
        minio_files=effective_minio_files,
        redis_client=get_redis_client(),
        user_context=resolve_tool_user_context(agent_config, user_id, tenant_id),
    )
