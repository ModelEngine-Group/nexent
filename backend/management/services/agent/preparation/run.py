# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compile serializable Agent resources for AgentOS execution."""

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from contracts.agentos import PreparedConversationScope, TurnModelGeneration
from contracts.errors.exceptions import RunModelControlsError
from contracts.tool import ToolParamsRequest
from infrastructure.agent_model_overrides import apply_turn_model_generation, merge_provider_body
from management.db.agent.repository import search_agent_info_by_agent_id
from management.db.agent.version import query_current_version_no, update_agent_snapshot
from management.db.model.repository import get_model_by_model_id
from management.services.agent.preparation.compiler import create_agent_config
from management.services.agent.preparation.inputs import join_minio_file_description_to_query
from management.services.model.run_bindings import create_model_config_list
from management.services.model.run_budget import _OPERATOR_OVERRIDE_FIELDS
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
from nexent.monitor.phase_capture import capture_preparation

if TYPE_CHECKING:
    from management.services.agent.workbench import PreparedWorkbench


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
        if not agent_info or agent_info.get("agent_origin") == "SYSTEM":
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


@capture_preparation
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
    runtime_generation_config: Optional[Dict[str, Any]] = None,
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
    export_debug_planning: bool = False,
    prepared_conversation: PreparedConversationScope | None = None,
    prepared_workbench: "PreparedWorkbench | None" = None,
    turn_generation: TurnModelGeneration | None = None,
    authorized_knowledge_tools: dict | None = None,
    model_parameter_preferences: Optional[Dict[str, Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    user_query: str | None = None,
):
    if override_model_id is not None:
        from management.services.model.run_controls import validate_selected_record

        validate_selected_record(
            get_model_by_model_id(override_model_id, tenant_id=tenant_id)
        )
    from management.services.agent.preparation.evaluation_snapshot import build_evaluation_input

    run_input = build_evaluation_input(query, minio_files, history, user_id, tenant_id)
    if user_query is not None and user_query != query:
        run_input = run_input.model_copy(update={"user_query": user_query})

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

    final_query = query
    model_versions = {}
    model_list = await create_model_config_list(tenant_id, versions=model_versions)
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
        "portable_evaluation": True,
    }
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
    from nexent.core.model_service.profiles.outlet_storage import (
        encode_resolved_model_profile,
    )
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

    if getattr(agent_config, "agent_core", "smolagents") == "jiuwen":
        final_query = await join_minio_file_description_to_query(
            minio_files=minio_files, query=query, history=None, language=language,
        )

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
            raise RunModelControlsError("model_not_available")
        source_model_alias = selected.cite_name
        root = apply_turn_model_generation(selected, turn_generation, "turn_root_model")
        model_list.append(root)
        agent_config.model_name = root.cite_name
    else:
        source_model_alias = apply_root_generation_overlay(model_list, agent_config, runtime_generation_config)

    # Apply Workbench reasoning settings when no turn overlay is present.
    if turn_generation is None and (reasoning_effort is not None or reasoning_budget_tokens is not None):
        from management.services.model.run_controls import overlay_root_model

        selected_config = next(
            (m for m in model_list if m.cite_name == agent_config.model_name), None
        )
        if selected_config is None:
            raise RunModelControlsError("model_not_available")
        legacy = {}
        if reasoning_effort is not None:
            legacy["thinking_effort"] = reasoning_effort
        if reasoning_budget_tokens is not None:
            legacy["reasoning_budget_tokens"] = reasoning_budget_tokens
        overlay = overlay_root_model(selected_config, legacy, selected_config.cite_name)
        index = model_list.index(selected_config)
        model_list[index] = overlay

    from management.services.agent.preparation.evaluation_snapshot import compile_snapshot

    apply_root_model_preferences(model_list, agent_config, model_parameter_preferences,
        outlet_profiles=outlet_profiles, agent_overrides=model_params_override)

    export_options = {}
    if turn_generation is not None:
        export_options.update(turn_generation=turn_generation, source_model_alias=source_model_alias)
    if export_debug_planning:
        export_options["allow_debug_planning"] = True
    if prepared_workbench is not None:
        from management.services.agent.workbench import compile_runtime_mount_plan

        agent_config = compile_runtime_mount_plan(prepared_workbench.plan, agent_config).root.agent_config
        export_options.update(
            root_generation=None,
            source_model_alias=source_model_alias,
            workbench_skills=prepared_workbench.plan.root_skills,
            workbench_knowledge_tools=prepared_workbench.knowledge_tools,
        )
        if reasoning_effort is not None or reasoning_budget_tokens is not None:
            export_options["turn_generation"] = TurnModelGeneration(
                reasoning_effort=reasoning_effort, reasoning_budget_tokens=reasoning_budget_tokens,
            )
    return compile_snapshot(
        agent_config, model_list, final_query, None, run_input=run_input,
        tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id, language=language,
        agent_model_overrides=model_params_override, prepared_conversation=prepared_conversation,
        catalog_model_versions=model_versions,
        model_parameter_preferences=model_parameter_preferences,
        **export_options,
    )


def apply_root_model_preferences(model_list, agent_config, preferences, *, outlet_profiles=None, agent_overrides=None):
    """Give the root a private alias; never change a child Agent's model defaults."""
    if not preferences:
        return
    from management.services.conversation.model_preferences import (
        merge_model_preferences,
    )

    for configured in model_list:
        profile = getattr(configured, "resolved_profile", None)
        if configured.cite_name != agent_config.model_name or profile is None:
            continue
        values = preferences.get(str(profile.outlet_id))
        if values is None:
            return
        original = (outlet_profiles or {}).get(profile.outlet_id)
        if original is not None:
            from management.services.agent.model_parameters import (
                merge_runtime_model_parameters,
            )

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


def _apply_agent_model_overrides(model_list, *, agent_id, tenant_id, version_no):
    """Apply legacy child options only when no canonical outlet is available."""
    from nexent.core.model_service.profiles.protocol_parameters import without_outlet_token_limits
    _agent_info_for_override = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)
    model_params_override = (_agent_info_for_override or {}).get("model_params_override") or {}
    if model_params_override:
        for model_id_str, override_entry in model_params_override.items():
            if not isinstance(override_entry, dict):
                continue
            try:
                override_model_id = int(model_id_str)
            except (ValueError, TypeError):
                continue
            override_model_info = get_model_by_model_id(override_model_id, tenant_id=tenant_id)
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
                                if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                                    mc.reasoning_budget_tokens = v
                                continue
                            if k == "__custom__" and isinstance(v, dict):
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
                        if isinstance(budget, int) and not isinstance(budget, bool) and budget > 0:
                            mc.reasoning_budget_tokens = budget
                    break


def _capture_child_model_configs(config, models, tenant_id):
    """Freeze already bound child outlets before root-only conversation preferences."""
    from management.services.model.runtime_options import compile_bound_model_profile, compile_model_runtime_profile

    for child in getattr(config, "worker_agents", ()):
        child_models = [model.model_copy(deep=True) for model in models]
        selected = next((model for model in child_models if model.cite_name == child.model_name), None)
        if selected is None:
            raise ValueError("CHILD_MODEL_OUTLET_NOT_FOUND")
        if selected.resolved_profile is None:
            _apply_agent_model_overrides(child_models, agent_id=child.agent_id,
                                         tenant_id=tenant_id, version_no=child.version_no)
            if child.agent_core == "jiuwen":
                selected.resolved_profile = compile_model_runtime_profile(selected, child)
        elif child.agent_core == "jiuwen":
            selected.resolved_profile = compile_bound_model_profile(selected, child)
        if child.agent_core == "jiuwen":
            selected.prompt_cache = None
        child.runtime_model_config = selected.model_copy(deep=True)
        _capture_child_model_configs(child, models, tenant_id)
