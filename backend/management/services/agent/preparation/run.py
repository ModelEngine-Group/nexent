# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prepare an in-process run and delegate local object construction to Runtime."""

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from contracts.constants.environment import (
    AGENT_WORKSPACE_ROOT,
    MCP_REQUEST_TIMEOUT_SECONDS,
    NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT,
    NEXENT_SANDBOX_FAILURE_POLICY,
    NEXENT_SANDBOX_WORKSPACE_MODE,
    NEXENT_SANDBOX_WORKSPACE_VOLUME,
    NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS,
    NEXENT_TOOL_FASTPATH_ENABLED,
    RUNTIME_MCP_CLOSE_TIMEOUT_SECONDS,
    RUNTIME_MCP_TOOL_TIMEOUT_SECONDS,
    TOKEN,
)
from contracts.tool import ToolParamsRequest
from infrastructure.http.client import create_httpx_client
from infrastructure.redis import get_redis_client
from management.db.agent.repository import search_agent_info_by_agent_id
from management.db.agent.version import query_current_version_no, update_agent_snapshot
from management.db.client import minio_client
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
from runtime.adapters.nexent.factory import build_run_info

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)


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
            normalize_profiles=False,
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
    requested_output_tokens: int | None = None,
    tool_params: Optional[ToolParamsRequest | Dict[str, Any]] = None,
    conversation_id: Optional[int] = None,
    context_policy: Optional[Dict[str, Any]] = None,
    enable_planning: bool = False,
    enable_automation_tool: bool = True,
    runtime_knowledge_context: Optional[Dict[str, str]] = None,
    runtime_skill_snapshot: Optional[List[Dict[str, Any]]] = None,
    runtime_knowledge_tools: Optional[List[Dict[str, Any]]] = None,
    runtime_sub_agent_mounts: Optional[List[Dict[str, Any]]] = None,
    model_parameter_preferences: Optional[Dict[str, Dict[str, Any]]] = None,
):
    if override_model_id is not None:
        from management.services.model.run_controls import validate_selected_record

        validate_selected_record(
            get_model_by_model_id(override_model_id, tenant_id=tenant_id)
        )
    workspace_run_id = uuid.uuid4().hex
    workspace_path = _build_run_workspace(user_id, workspace_run_id)
    if runtime_skill_snapshot is not None:
        runtime_skill_snapshot = _materialize_runtime_skill_snapshot(
            runtime_skill_snapshot,
            workspace_path,
            tenant_id,
        )
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

    final_query = await join_minio_file_description_to_query(
        minio_files=minio_files,
        query=query,
        history=history,
        language=language,
    )
    model_list = await create_model_config_list(tenant_id)
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
    if runtime_knowledge_context is not None:
        create_config_kwargs["runtime_knowledge_context"] = runtime_knowledge_context
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
    from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
    from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
    captured_records = {}
    outlet_profiles = {}
    for configured in model_list:
        if isinstance(getattr(configured, "resolved_profile", None), ResolvedModelProfile):
            from nexent.core.model_service.registry import model_service_references

            outlet_profiles[configured.resolved_profile.outlet_id] = configured.resolved_profile
            captured = encode_resolved_model_profile(configured.resolved_profile, registered_references=model_service_references())
            if captured.get("model_id") is not None:
                captured_records[captured["model_id"]] = captured
    if captured_records:
        create_config_kwargs["runtime_model_records"] = captured_records
    agent_config = await create_agent_config(**create_config_kwargs, tool_params=tool_params)

    # v2.6.0: Apply per-agent model params override to model_config_list.
    # model_params_override is a {model_id_str: {temperature, top_p, extra_params}} dict
    # stored on ag_tenant_agent_t. We match each override entry to a ModelConfig
    # by display_name (the cite_name used in model_config_list) and merge the
    # override values on top of the model-level defaults.
    _agent_info_for_override = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)
    model_params_override = (_agent_info_for_override or {}).get("model_params_override") or {}
    from management.services.agent.model_parameters import bind_agent_model_profiles

    bind_agent_model_profiles(model_list, agent_config, _agent_info_for_override or {},
        lambda selected_agent_id, selected_version: search_agent_info_by_agent_id(
            agent_id=selected_agent_id, tenant_id=tenant_id, version_no=selected_version))
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
                if isinstance(getattr(mc, "resolved_profile", None), ResolvedModelProfile):
                    continue  # Saved outlets were bound independently for each Agent above.
                if mc.cite_name == display_name:
                    if override_entry.get("temperature") is not None:
                        mc.temperature = override_entry["temperature"]
                    if override_entry.get("top_p") is not None:
                        mc.top_p = override_entry["top_p"]
                    override_extra = override_entry.get("extra_params")
                    if override_extra and isinstance(override_extra, dict):
                        merged = dict(mc.extra_body or {})
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
                            if k == "__custom__" and isinstance(v, dict):
                                from nexent.core.model_service.profiles.protocol_parameters import without_outlet_token_limits

                                for custom_key, custom_value in without_outlet_token_limits(v).items():
                                    # A null custom value is an explicit
                                    # removal marker: the agent opts out of a
                                    # model-level custom param instead of
                                    # inheriting it.
                                    if custom_value is None:
                                        merged.pop(custom_key, None)
                                    else:
                                        merged[custom_key] = custom_value
                            else:
                                merged[k] = v
                        mc.extra_body = merged if merged else None
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
    remote_mcp_list = await get_remote_mcp_server_list(tenant_id=tenant_id, is_need_auth=True)
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

    # Resolve sandbox config: DB policy overrides env-var defaults.
    # build_sandbox_policy returns None when level=local (backward-compatible).
    # Import inside function body to avoid circular dependency.
    from management.services.agent.policy import (
        build_sandbox_policy,
        get_sandbox_minio_client,
    )
    from runtime.adapters.nexent.sandbox import resolve_sandbox_config

    sandbox_policy = build_sandbox_policy(tenant_id=tenant_id, agent_type="")
    agent_db_policy = getattr(agent_config, "sandbox_policy", None)
    sandbox_config = resolve_sandbox_config(
        agent_db_policy,
        sandbox_policy,
        workspace_mode=NEXENT_SANDBOX_WORKSPACE_MODE,
        container_workspace_root=NEXENT_SANDBOX_CONTAINER_WORKSPACE_ROOT,
        failure_policy=NEXENT_SANDBOX_FAILURE_POLICY,
    )
    sandbox_minio_client = (
        get_sandbox_minio_client()
        if sandbox_config and sandbox_config.auto_sync_outputs
        else None
    )
    if sandbox_config is not None:
        sandbox_config.output_dir = str(Path(workspace_path) / "outputs")
        sandbox_config.extra_kwargs = {
            **sandbox_config.extra_kwargs,
            "workspace_root": str(Path(AGENT_WORKSPACE_ROOT).resolve()),
            "workspace_path": workspace_path,
        }
        if (
            getattr(sandbox_config.level, "value", sandbox_config.level) == "docker"
            and getattr(sandbox_config.scope, "value", sandbox_config.scope) == "system"
            and sandbox_config.workspace_mode == "legacy"
        ):
            sandbox_config.extra_kwargs.update(
                {
                    "workspace_volume_name": NEXENT_SANDBOX_WORKSPACE_VOLUME,
                    "shared_workspace": True,
                }
            )

    apply_root_model_preferences(model_list, agent_config, model_parameter_preferences,
        outlet_profiles=outlet_profiles, agent_overrides=model_params_override)

    agent_run_info = build_run_info(
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
        sandbox_config=sandbox_config,
        tool_fastpath_enabled=NEXENT_TOOL_FASTPATH_ENABLED,
        tool_fastpath_allowed_tools=list(NEXENT_TOOL_FASTPATH_ALLOWED_TOOLS),
        minio_client=sandbox_minio_client,
        workspace_path=workspace_path,
        workspace_run_id=workspace_run_id,
        tenant_id=tenant_id,
        minio_files=effective_minio_files,
        redis_client=get_redis_client(),
        user_context=resolve_tool_user_context(agent_config, user_id, tenant_id),
    )
    return agent_run_info


def apply_root_model_preferences(model_list, agent_config, preferences, *, outlet_profiles=None, agent_overrides=None):
    """Give the root a private alias; never change a child Agent's model defaults."""
    if not preferences:
        return
    from management.services.conversation.model_preferences import merge_model_preferences

    for configured in model_list:
        profile = getattr(configured, "resolved_profile", None)
        if configured.cite_name != agent_config.model_name or profile is None:
            continue
        values = preferences.get(str(profile.outlet_id))
        if values is None:
            return
        original = (outlet_profiles or {}).get(profile.outlet_id)
        if original is not None:
            from management.services.agent.model_parameters import merge_runtime_model_parameters

            resolved = merge_runtime_model_parameters(original, (agent_overrides or {}).get(str(profile.outlet_id), {}), values)
        else:
            resolved = merge_model_preferences(profile, values)
        root = configured.model_copy(deep=True, update={"cite_name": "conversation_root_model_" + uuid.uuid4().hex,
            "resolved_profile": resolved,
            "default_output_reserve_tokens": resolved.parameter_values.get("max_output_tokens",
                configured.default_output_reserve_tokens)})
        model_list.append(root)
        agent_config.model_name = root.cite_name
        return
