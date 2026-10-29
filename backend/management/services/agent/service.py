# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from collections import deque
from typing import Optional
from uuid import uuid4

from contracts.agent import AgentUnavailableReason
from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.constants.constants import LANGUAGE
from contracts.constants.constants import MODEL_CONFIG_MAPPING
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AgentNotFoundError, AgentRelationValidationError, AppException, ForbiddenError, TenantResourceLimitError
from contracts.agent import AgentInfoRequest, AgentNameBatchCheckRequest, AgentNameBatchRegenerateRequest
from contracts.skill import SkillInstanceInfoRequest
from contracts.tool import ToolInstanceInfoRequest
from management.db.a2a import repository as a2a_agent_db
from management.db.skill import repository as skill_db
from management.db.a2a.repository import query_external_sub_agents
from management.db.agent.repository import batch_search_agent_display_names, create_agent, is_system_agent, query_all_agent_info_by_tenant_id, query_sub_agent_relations, query_sub_agents_id_list, search_agent_info_by_agent_id, update_agent, update_agent_icon, update_related_agents
from management.db.agent.version import batch_query_current_version_nos, batch_search_version_names, query_current_version_no
from management.db.model.repository import get_model_by_model_id
from management.db.tool.repository import create_or_update_tool_by_tool_info, query_all_enabled_tool_instances, query_tool_instances_by_agent_id, query_tool_instances_by_id, query_tools_by_ids, search_tools_for_sub_agent
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.services.agent.icon import (
    read_icon_image,
    upload_icon_image,
    validate_icon_image,
)
from management.services.agent.naming import (
    check_agent_value_duplicate,
    generate_unique_agent_value,
    regenerate_agent_value,
)
from management.services.agent.read import (
    apply_deleted_model_reason,
    check_agent_availability,
    project_agent_models,
    tool_has_deleted_model,
)
from management.services.skill.service import SkillService
from nexent.core.concurrency import run_blocking
from management.services.agent.reasoning import (
    snapshot_agent_reasoning_config as build_reasoning_snapshot,
)
from management.services.permission.asset_owner import resolve_agent_list_permission
from management.services.conversation.service import (
    generate_conversation_title_service,  # noqa: F401 - compatibility patch point
    save_message_unit,  # noqa: F401 - retained as a compatibility re-export
    update_unit_status,  # noqa: F401 - retained as a compatibility re-export
)
from management.services.permission.identity.display import enrich_cas_usernames
from contracts.authentication import AuthenticatedIdentity
from management.services.configuration.tenant.settings import tenant_config_manager
from management.utils.serialization import convert_list_to_string, convert_string_to_list

# Monitoring utilities: bind Agent metadata once at the request boundary.

# Import monitoring utilities

logger = logging.getLogger(__name__)


from management.services.agent.execution import (
    _agent_run_identifier,
    _cancel_task_on_runtime_signal,
    _cleanup_channel_later,
    _consume_agent_stream_producer,
    _poll_runtime_cancel_signal,
    _stream_agent_chunks,
    shutdown_agent_stream_tasks,
)
from management.services.agent.management import (
    clear_agent_new_mark_impl,
    delete_agent_impl,
    get_agent_by_name_impl,
    get_agent_call_relationship_impl,
    list_agent_page_impl,
    list_all_agent_info_impl,
)
from management.services.agent.policy import (
    build_sandbox_policy,
    get_sandbox_minio_client,
)
from management.services.agent.run import (
    generate_stream,
    is_agent_running,
    prepare_agent_run,
    run_agent_background,
    save_messages,
    stop_agent_tasks,
)
from management.services.agent.stream import (
    finalize_buffered_unit_fragments as _finalize_buffered_unit_fragments,
)
from management.services.agent.subscription import (
    _detect_resume_position,
    _resolve_user_tenant_language,
    run_agent_stream,
)
from management.services.agent.transfer import (
    _collect_skill_names_from_tree,
    _export_agent_dict_core,
    _get_user_group_ids,
    _resolve_model_ids_with_fallback,
    build_skill_import_conflicts,
    check_skill_conflicts_impl,
    collect_skill_zip_entries,
    export_agent_by_agent_id,
    export_agent_dict_for_repository_impl,
    export_agent_dict_impl,
    export_agent_impl,
    export_agent_with_skills_impl,
    import_agent_by_agent_id,
    import_agent_impl,
    import_agent_with_skills_impl,
)

__all__ = (
    "_get_user_group_ids",
    "_resolve_model_ids_with_fallback",
    "delete_agent_impl",
    "_export_agent_dict_core",
    "export_agent_dict_impl",
    "export_agent_dict_for_repository_impl",
    "export_agent_impl",
    "_collect_skill_names_from_tree",
    "collect_skill_zip_entries",
    "export_agent_by_agent_id",
    "import_agent_impl",
    "import_agent_by_agent_id",
    "clear_agent_new_mark_impl",
    "list_all_agent_info_impl",
    "list_agent_page_impl",
    "get_agent_by_name_impl",
    "get_agent_call_relationship_impl",
    "export_agent_with_skills_impl",
    "import_agent_with_skills_impl",
    "build_skill_import_conflicts",
    "check_skill_conflicts_impl",
    "build_sandbox_policy",
    "get_sandbox_minio_client",
    "_finalize_buffered_unit_fragments",
    "_cleanup_channel_later",
    "_consume_agent_stream_producer",
    "_poll_runtime_cancel_signal",
    "_cancel_task_on_runtime_signal",
    "_resolve_user_tenant_language",
    "_stream_agent_chunks",
    "_agent_run_identifier",
    "prepare_agent_run",
    "save_messages",
    "generate_stream",
    "_detect_resume_position",
    "run_agent_stream",
    "run_agent_background",
    "shutdown_agent_stream_tasks",
    "stop_agent_tasks",
    "is_agent_running",
)


def _agent_icon_object_name(agent_id: int, tenant_id: str) -> str:
    return f"agent-icons/{tenant_id}/{agent_id}/icon"


async def upload_agent_icon_impl(
    agent_id: int,
    content: bytes,
    tenant_id: str,
    user_id: str,
) -> dict:
    """Validate, store, and attach a user-supplied image to an editable agent."""
    if is_system_agent(agent_id, tenant_id) is True:
        raise ForbiddenError("System Agent is managed by the platform")
    validate_icon_image(content)
    agent = await get_agent_info_impl(agent_id, tenant_id, user_id=user_id)
    if agent.get("permission") != "EDIT":
        raise ForbiddenError("You do not have permission to edit this agent")

    owner_tenant_id = agent.get("tenant_id") or tenant_id
    object_name = _agent_icon_object_name(agent_id, owner_tenant_id)
    content_type = upload_icon_image(content, object_name)

    icon_url = f"/api/agent/{agent_id}/icon?v={uuid4().hex}"
    update_agent_icon(
        agent_id=agent_id,
        tenant_id=owner_tenant_id,
        icon_url=icon_url,
        user_id=user_id,
    )
    return {"icon_url": icon_url, "content_type": content_type}


async def get_agent_icon_impl(
    agent_id: int, tenant_id: str, user_id: str
) -> tuple[bytes, str]:
    """Return a stored agent icon after applying normal agent visibility rules."""
    agent = await get_agent_info_impl(agent_id, tenant_id, user_id=user_id)
    if not agent.get("icon_url"):
        raise FileNotFoundError("Agent icon not found")

    owner_tenant_id = agent.get("tenant_id") or tenant_id
    return read_icon_image(_agent_icon_object_name(agent_id, owner_tenant_id))


async def check_agent_name_conflict_batch_impl(
    request: AgentNameBatchCheckRequest, identity: AuthenticatedIdentity
) -> list[dict]:
    """
    Batch check name/display_name duplication for multiple agents.
    """
    tenant_id = identity.tenant_id
    agents_cache = query_all_agent_info_by_tenant_id(tenant_id)

    results: list[dict] = []
    for item in request.items:
        conflicts: list[dict] = []
        name_conflict = False
        display_name_conflict = False
        for agent in agents_cache:
            if item.agent_id and agent.get("agent_id") == item.agent_id:
                continue
            matches_name = item.name and agent.get("name") == item.name
            matches_display = (
                item.display_name and agent.get("display_name") == item.display_name
            )
            if matches_name:
                name_conflict = True
            if matches_display:
                display_name_conflict = True
            if matches_name or matches_display:
                conflicts.append(
                    {
                        "name": agent.get("name"),
                        "display_name": agent.get("display_name"),
                    }
                )

        results.append(
            {
                "name_conflict": name_conflict,
                "display_name_conflict": display_name_conflict,
                "conflict_agents": conflicts,
            }
        )
    return results


async def regenerate_agent_name_batch_impl(
    request: AgentNameBatchRegenerateRequest, identity: AuthenticatedIdentity
) -> list[dict]:
    """
    Batch regenerate agent name/display_name with LLM (or suffix fallback).
    """
    tenant_id = identity.tenant_id
    agents_cache = query_all_agent_info_by_tenant_id(tenant_id)

    existing_names = [agent.get("name") for agent in agents_cache if agent.get("name")]
    existing_display_names = [
        agent.get("display_name") for agent in agents_cache if agent.get("display_name")
    ]

    # Always use tenant quick-config LLM model
    quick_config_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id
    )
    resolved_model_id = (
        quick_config_model.get("model_id") if quick_config_model else None
    )
    if not resolved_model_id:
        raise ValueError(
            "No available model for regeneration. Please configure an LLM model first."
        )

    results: list[dict] = []
    existing_by_field = {
        "name": set(existing_names),
        "display_name": set(existing_display_names),
    }
    for item in request.items:
        values = {"name": item.name or "", "display_name": item.display_name or ""}
        for field_key, value in values.items():
            if value and check_agent_value_duplicate(
                field_key,
                value,
                tenant_id,
                agents_cache=agents_cache,
                exclude_agent_id=item.agent_id,
            ):
                try:
                    values[field_key] = await run_blocking(
                        "regenerate-agent-value",
                        regenerate_agent_value,
                        lane="model-tool-io",
                        owner="config",
                        field_key=field_key,
                        original_value=value,
                        existing_values=list(existing_by_field[field_key]),
                        task_description=item.task_description or "",
                        model_id=resolved_model_id,
                        tenant_id=tenant_id,
                        language=LANGUAGE["ZH"],
                        agents_cache=agents_cache,
                        exclude_agent_id=item.agent_id,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to regenerate agent %s with LLM: %s, using fallback",
                        field_key,
                        exc,
                    )
                    values[field_key] = generate_unique_agent_value(
                        field_key, value, tenant_id, agents_cache, item.agent_id
                    )
            if values[field_key]:
                existing_by_field[field_key].add(values[field_key])
        results.append(values)
    return results


def get_enable_tool_id_by_agent_id(agent_id: int, tenant_id: str):
    all_tool_instance = query_all_enabled_tool_instances(
        agent_id=agent_id, tenant_id=tenant_id
    )
    enable_tool_id_set = set()
    for tool_instance in all_tool_instance:
        if tool_instance["enabled"]:
            enable_tool_id_set.add(tool_instance["tool_id"])
    return list(enable_tool_id_set)


async def get_agent_info_impl(
    agent_id: int, tenant_id: str, version_no: int = 0, user_id: Optional[str] = None
):
    try:
        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id, version_no)
        if (
            agent_info.get("agent_origin") == "SYSTEM"
            or agent_info.get("system_key") is not None
        ):
            raise ForbiddenError("Agent is not accessible")
        # Keep the request-scoped tenant_id unless the record explicitly provides one.
        record_tenant_id = agent_info.get("tenant_id")
        if record_tenant_id:
            tenant_id = record_tenant_id
    except (AgentNotFoundError, ForbiddenError):
        raise
    except Exception as e:
        logger.error(f"Failed to get agent info: {str(e)}")
        raise ValueError(f"Failed to get agent info: {str(e)}")

    # Calculate permission if user_id is provided
    if user_id is not None:
        try:
            user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
            user_role = str(user_tenant_record.get("user_role") or "").upper()
            can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

            # Permission logic (same as agent list, including ASSET_OWNER read-only override)
            agent_info["permission"] = resolve_agent_list_permission(
                user_role=user_role,
                agent=agent_info,
                user_id=user_id,
                can_edit_all=can_edit_all,
            )
        except Exception as e:
            logger.warning(f"Failed to calculate agent permission: {str(e)}")

    try:
        tool_info = search_tools_for_sub_agent(agent_id=agent_id, tenant_id=tenant_id)
        for tool in tool_info:
            tool["unavailable_reasons"] = (
                [AgentUnavailableReason.MCP_MODEL_UNAVAILABLE]
                if tool_has_deleted_model(tool, tenant_id)
                else []
            )
        agent_info["tools"] = tool_info
    except Exception as e:
        logger.error(f"Failed to get agent tools: {str(e)}")
        agent_info["tools"] = []

    try:
        sub_agent_id_list = query_sub_agents_id_list(
            main_agent_id=agent_id, tenant_id=tenant_id
        )
        agent_info["sub_agent_id_list"] = sub_agent_id_list

        # Enrich sub-agent relations with version names (batch query)
        relations = query_sub_agent_relations(agent_id, tenant_id, version_no)
        enriched_relations = []

        # Collect all agent_ids and (agent_id, version_no) pairs for batch lookup
        all_agent_ids = set()
        lookup_agent_ids = set()
        lookup_version_nos = set()
        # Track agents whose pinned version_no is null -> need to resolve latest published version
        missing_version_agent_ids = set()
        for rel in relations:
            aid = rel.get("selected_agent_id")
            if aid:
                all_agent_ids.add(aid)
            vno = rel.get("selected_agent_version_no")
            if aid and vno is not None and vno != 0:
                lookup_agent_ids.add(aid)
                lookup_version_nos.add(vno)
            elif aid:
                # Historical data: pinned version_no is null or 0 (draft), resolve from child's current published version
                missing_version_agent_ids.add(aid)

        # Batch query current published version_no for agents with missing pinned version
        resolved_version_no_map: dict = {}
        if missing_version_agent_ids:
            resolved_version_no_map = batch_query_current_version_nos(
                agent_ids=list(missing_version_agent_ids),
                tenant_id=tenant_id,
            )
            # Merge resolved version_nos into the version name lookup set
            for aid, resolved_vno in resolved_version_no_map.items():
                lookup_agent_ids.add(aid)
                lookup_version_nos.add(resolved_vno)

        # Batch query all version names at once
        version_name_map: dict = {}
        if lookup_agent_ids and lookup_version_nos:
            batch_results = batch_search_version_names(
                agent_ids=list(lookup_agent_ids),
                tenant_id=tenant_id,
                version_nos=list(lookup_version_nos),
            )
            for item in batch_results:
                key = (item["agent_id"], item["version_no"])
                version_name_map[key] = item["version_name"]

        # Batch query all agent display names at once
        agent_name_map = batch_search_agent_display_names(
            agent_ids=list(all_agent_ids),
            tenant_id=tenant_id,
        )

        for rel in relations:
            selected_agent_id = rel.get("selected_agent_id")
            selected_version_no = rel.get("selected_agent_version_no")
            # Fallback to resolved latest published version_no when pinned version is null or 0 (draft)
            if (
                selected_version_no is None or selected_version_no == 0
            ) and selected_agent_id in resolved_version_no_map:
                selected_version_no = resolved_version_no_map[selected_agent_id]
            version_name = None
            if selected_agent_id and selected_version_no is not None:
                version_name = version_name_map.get(
                    (selected_agent_id, selected_version_no)
                )
            enriched_relations.append(
                {
                    "agent_id": selected_agent_id,
                    "agent_name": agent_name_map.get(selected_agent_id)
                    if selected_agent_id
                    else None,
                    "version_no": selected_version_no,
                    "version_name": version_name,
                }
            )

        agent_info["sub_agent_relations"] = enriched_relations
    except Exception as e:
        logger.error(f"Failed to get sub agent id list: {str(e)}")
        agent_info["sub_agent_id_list"] = []
        agent_info["sub_agent_relations"] = []

    try:
        skill_service = SkillService()
        instances = skill_service.list_skill_instances(
            agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
        )
        # Keep disabled instances for their saved configuration, but do not
        # return them as selected skills in the agent configuration.
        instances = [
            instance for instance in instances if instance.get("enabled", True)
        ]

        # Fallback: verify each instance's skill_id still exists in ag_skill_info_t
        valid_skill_ids = skill_db.get_valid_skill_ids(
            tenant_id=tenant_id,
            skill_ids=[
                inst.get("skill_id") for inst in instances if isinstance(inst, dict)
            ],
        )
        filtered = []
        for inst in instances:
            skill_id = inst.get("skill_id")
            if skill_id in valid_skill_ids:
                filtered.append(inst)
            else:
                logger.warning(
                    "Filtering out stale skill instance: agent_id=%s, skill_id=%s (not found in ag_skill_info_t)",
                    agent_id,
                    skill_id,
                )
        agent_info["skills"] = filtered

    except Exception as e:
        logger.exception(f"Failed to get agent skills: {str(e)}")
        agent_info["skills"] = []

    try:
        external_agents = query_external_sub_agents(
            local_agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
        )
        agent_info["external_sub_agent_id_list"] = [
            ea["external_agent_id"] for ea in external_agents
        ]
    except Exception as e:
        logger.error(f"Failed to get external sub agents: {str(e)}")
        agent_info["external_sub_agent_id_list"] = []

    model_projection = project_agent_models(agent_info, tenant_id, detail=True)
    agent_info.update(model_projection.fields)
    agent_info["model_ids"] = model_projection.availability_model_ids

    # Get business logic model display name from model_id
    if agent_info.get("business_logic_model_id") is not None:
        business_logic_model_info = get_model_by_model_id(
            agent_info["business_logic_model_id"]
        )
        agent_info["business_logic_model_name"] = (
            business_logic_model_info.get("display_name", None)
            if business_logic_model_info is not None
            else None
        )
    elif "business_logic_model_name" not in agent_info:
        agent_info["business_logic_model_name"] = None

    if agent_info.get("group_ids") is not None:
        agent_info["group_ids"] = convert_string_to_list(agent_info.get("group_ids"))

    # Check agent availability
    is_available, unavailable_reasons = check_agent_availability(
        agent_id=agent_id, tenant_id=tenant_id, agent_info=agent_info
    )
    agent_info["model_ids"] = model_projection.fields["model_ids"]

    is_available, unavailable_reasons = apply_deleted_model_reason(
        is_available,
        unavailable_reasons,
        model_projection.deleted_model_ids,
    )

    agent_info["is_available"] = is_available
    agent_info["unavailable_reasons"] = unavailable_reasons

    # Set current_version_no from draft record (version_no=0)
    # This ensures the returned data always has the current published version info
    if version_no > 0:
        draft_version_no = query_current_version_no(agent_id, tenant_id)
        agent_info["current_version_no"] = draft_version_no

    enrich_cas_usernames(
        [agent_info], {"author_cas_username": "created_by"},
        email_fields={"author_cas_username": "author"},
    )
    return agent_info


def _normalize_agent_output_reserve(request: AgentInfoRequest) -> None:
    """Retire historical Agent reserves; output limits belong to saved outlets."""
    request.requested_output_tokens = None


def _validate_agent_relationships(request: AgentInfoRequest, tenant_id: str):
    """Validate and normalize relationship selections before any update writes."""
    if isinstance(request.related_agents, list):
        relations = [
            {"agent_id": relation.agent_id, "version_no": relation.version_no}
            for relation in request.related_agents
        ]
        if request.related_agent_ids is not None and set(request.related_agent_ids) != {
            relation["agent_id"] for relation in relations
        }:
            raise AgentRelationValidationError(
                "related_agent_ids and related_agents must select the same Agents"
            )
    elif request.related_agent_ids is not None:
        relations = [
            {"agent_id": agent_id, "version_no": None}
            for agent_id in request.related_agent_ids
        ]
    else:
        return None

    selected_ids = [relation["agent_id"] for relation in relations]
    if request.agent_id is not None and request.agent_id in selected_ids:
        raise AgentRelationValidationError(
            "Circular dependency detected: Agent cannot be related to itself"
        )
    if len(selected_ids) != len(set(selected_ids)) or (
        request.related_agent_ids is not None
        and len(request.related_agent_ids) != len(set(request.related_agent_ids))
    ):
        raise AgentRelationValidationError(
            "Related Agent IDs must not contain duplicates"
        )

    for relation in relations:
        search_agent_info_by_agent_id(
            relation["agent_id"], tenant_id, version_no=relation["version_no"] or 0
        )

    search_list = deque(
        (relation["agent_id"], relation["version_no"] or 0) for relation in relations
    )
    visited = set()
    while search_list:
        current_id, version_no = search_list.popleft()
        if request.agent_id is not None and current_id == request.agent_id:
            raise AgentRelationValidationError(
                "Circular dependency detected: Agent cannot create circular calls"
            )
        if (current_id, version_no) in visited:
            continue
        visited.add((current_id, version_no))
        sub_ids = query_sub_agents_id_list(
            main_agent_id=current_id, tenant_id=tenant_id, version_no=version_no
        )
        search_list.extend((sub_id, 0) for sub_id in sub_ids)
    return relations


async def update_agent_info_impl(
    request: AgentInfoRequest, identity: AuthenticatedIdentity
):
    user_id, tenant_id = identity.user_id, identity.tenant_id

    if (
        request.agent_id is not None
        and is_system_agent(request.agent_id, tenant_id) is True
    ):
        raise ForbiddenError("System Agent is managed by the platform")

    related_agents_dicts = _validate_agent_relationships(request, tenant_id)

    # Validate external selections before any Agent or relationship mutation.
    for external_agent_id in getattr(request, "related_external_agent_ids", None) or []:
        if a2a_agent_db.get_external_agent_by_id(external_agent_id, tenant_id) is None:
            raise AgentNotFoundError("External agent not found")

    if request.example_questions is not None and len(request.example_questions) > 6:
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            "example_questions cannot exceed 6 items",
        )

    _normalize_agent_output_reserve(request)

    existing_agent = None
    if request.agent_id is not None:
        existing_agent = search_agent_info_by_agent_id(
            agent_id=request.agent_id,
            tenant_id=tenant_id,
            version_no=getattr(request, "version_no", 0),
        )
    request_fields = getattr(request, "model_fields_set", set())
    model_ids = (
        request.model_ids
        if "model_ids" in request_fields and request.model_ids is not None
        else (existing_agent or {}).get("model_ids")
    )
    requested_overrides = (
        request.model_params_override
        if "model_params_override" in request_fields
        else None
    )
    model_params_override = build_reasoning_snapshot(
        model_ids=model_ids,
        requested_overrides=requested_overrides,
        existing_overrides=(existing_agent or {}).get("model_params_override"),
        tenant_id=tenant_id,
    )

    # If agent_id is None, create a new agent; otherwise, update existing
    agent_id: Optional[int] = request.agent_id
    if agent_id is not None:
        agent_record = search_agent_info_by_agent_id(agent_id, tenant_id)
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()
        permission = resolve_agent_list_permission(
            user_role=user_role,
            agent=agent_record,
            user_id=user_id,
            can_edit_all=user_role in CAN_EDIT_ALL_USER_ROLES,
        )
        if permission != "EDIT":
            raise ForbiddenError("You do not have permission to edit this agent")
    try:
        if agent_id is None:
            # Create agent - automatically set group_ids to current user's groups
            # Guard against duplicate name/display_name regardless of the caller
            # (dev-page copy, direct API, ...) so new agents stay publishable.
            agents_cache = query_all_agent_info_by_tenant_id(tenant_id)
            for field_key in ("name", "display_name"):
                value = getattr(request, field_key, None)
                if value and check_agent_value_duplicate(
                    field_key, value, tenant_id, agents_cache=agents_cache
                ):
                    setattr(
                        request,
                        field_key,
                        generate_unique_agent_value(
                            field_key, value, tenant_id, agents_cache=agents_cache
                        ),
                    )
            user_group_ids = _get_user_group_ids(user_id, tenant_id)
            created = create_agent(
                agent_info={
                    "name": request.name,
                    "display_name": request.display_name,
                    "description": request.description,
                    "business_description": request.business_description,
                    "author": request.author,
                    "model_ids": request.model_ids,
                    "business_logic_model_id": request.business_logic_model_id,
                    "business_logic_model_name": request.business_logic_model_name,
                    "max_steps": request.max_steps,
                    "requested_output_tokens": request.requested_output_tokens,
                    "is_main_agent": request.is_main_agent
                    if request.is_main_agent is not None
                    else True,
                    "provide_run_summary": request.provide_run_summary,
                    "allow_chat_metadata": request.allow_chat_metadata
                    if request.allow_chat_metadata is not None
                    else False,
                    "enable_protocol_repair_retry": request.enable_protocol_repair_retry
                    if request.enable_protocol_repair_retry is not None
                    else False,
                    "is_a2a": request.is_a2a if request.is_a2a is not None else False,
                    "verification_config": request.verification_config,
                    "context_policy": request.context_policy,
                    "model_params_override": model_params_override,
                    "prompt": request.prompt,
                    "greeting_message": request.greeting_message,
                    "example_questions": request.example_questions,
                    "icon_url": request.icon_url,
                    "enabled": request.enabled if request.enabled is not None else True,
                    "group_ids": convert_list_to_string(request.group_ids)
                    if request.group_ids
                    else user_group_ids,
                    "ingroup_permission": request.ingroup_permission,
                },
                tenant_id=tenant_id,
                user_id=user_id,
            )
            agent_id = created["agent_id"]
        else:
            # Update agent
            request.model_params_override = model_params_override
            update_agent(agent_id, request, user_id)
    except TenantResourceLimitError:
        raise
    except Exception as e:
        logger.error(f"Failed to update agent info: {str(e)}")
        raise ValueError(f"Failed to update agent info: {str(e)}")

    # Handle enabled tools saving when provided
    try:
        if request.enabled_tool_ids is not None and agent_id is not None:
            requested_enabled_set = set(request.enabled_tool_ids)
            available_tools = query_tools_by_ids(list(requested_enabled_set))
            enabled_set = {
                tool["tool_id"]
                for tool in available_tools
                if tool.get("is_available") is not False
            }
            # Query existing tool instances for this agent
            existing_instances = query_tool_instances_by_agent_id(agent_id, tenant_id)

            # Handle unselected tool（already exist instance）→ enabled=False
            for instance in existing_instances:
                inst_tool_id = instance.get("tool_id")
                if inst_tool_id is not None and inst_tool_id not in enabled_set:
                    create_or_update_tool_by_tool_info(
                        tool_info=ToolInstanceInfoRequest(
                            tool_id=inst_tool_id,
                            agent_id=agent_id,
                            params=instance.get("params", {}),
                            enabled=False,
                        ),
                        tenant_id=tenant_id,
                        user_id=user_id,
                    )

            # Handle selected tool → enabled=True（create or update）
            for tool_id in enabled_set:
                # Keep existing params if any
                existing_instance = next(
                    (
                        inst
                        for inst in existing_instances
                        if inst.get("tool_id") == tool_id
                    ),
                    None,
                )
                # Safely get params, default to empty dict if None or not present
                raw_params = (existing_instance or {}).get("params")
                params = raw_params if raw_params is not None else {}
                create_or_update_tool_by_tool_info(
                    tool_info=ToolInstanceInfoRequest(
                        tool_id=tool_id,
                        agent_id=agent_id,
                        params=params,
                        enabled=True,
                    ),
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
    except Exception as e:
        logger.error(f"Failed to update agent tools: {str(e)}")
        raise ValueError(f"Failed to update agent tools: {str(e)}")

    # Handle enabled skills and their per-agent configuration.
    try:
        requested_skill_instances = getattr(request, "skill_instances", None)
        has_structured_skill_instances = isinstance(requested_skill_instances, list)
        if (
            has_structured_skill_instances or request.enabled_skill_ids is not None
        ) and agent_id is not None:
            raw_version_no = getattr(request, "version_no", 0)
            request_version_no = (
                raw_version_no if isinstance(raw_version_no, int) else 0
            )
            requested_by_id = {}
            if has_structured_skill_instances:
                for requested_instance in requested_skill_instances:
                    skill_id = requested_instance.skill_id
                    if skill_id in requested_by_id:
                        raise ValueError(
                            f"Duplicate skill_id in skill_instances: {skill_id}"
                        )
                    requested_by_id[skill_id] = requested_instance
                enabled_set = {
                    skill_id
                    for skill_id, requested_instance in requested_by_id.items()
                    if requested_instance.enabled
                }
            else:
                enabled_set = set(request.enabled_skill_ids or [])

            if has_structured_skill_instances:
                valid_skill_ids = skill_db.get_valid_skill_ids(
                    tenant_id=tenant_id,
                    skill_ids=list(enabled_set),
                )
                missing_skill_ids = enabled_set - valid_skill_ids
                if missing_skill_ids:
                    raise AppException(
                        ErrorCode.COMMON_PARAMETER_INVALID,
                        (
                            "skill_instances contains invalid or unavailable "
                            f"skill IDs: {sorted(missing_skill_ids)}"
                        ),
                    )

            # Query existing skill instances for this agent
            existing_instances = skill_db.query_skill_instances_by_agent_id(
                agent_id, tenant_id, version_no=request_version_no
            )

            # Handle unselected skill (already exist instance) -> enabled=False
            for instance in existing_instances:
                inst_skill_id = instance.get("skill_id")
                if inst_skill_id is not None and inst_skill_id not in enabled_set:
                    skill_db.create_or_update_skill_by_skill_info(
                        skill_info=SkillInstanceInfoRequest(
                            skill_id=inst_skill_id,
                            agent_id=agent_id,
                            enabled=False,
                            config_values=instance.get("config_values"),
                            version_no=request_version_no,
                        ),
                        tenant_id=tenant_id,
                        user_id=user_id,
                        version_no=request_version_no,
                    )

            # Handle selected skill -> enabled=True (create or update)
            for skill_id in enabled_set:
                existing_instance = next(
                    (
                        inst
                        for inst in existing_instances
                        if inst.get("skill_id") == skill_id
                    ),
                    None,
                )
                if has_structured_skill_instances:
                    config_values = requested_by_id[skill_id].config_values
                else:
                    config_values = (existing_instance or {}).get("config_values")
                skill_db.create_or_update_skill_by_skill_info(
                    skill_info=SkillInstanceInfoRequest(
                        skill_id=skill_id,
                        agent_id=agent_id,
                        enabled=True,
                        config_values=config_values,
                        version_no=request_version_no,
                    ),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    version_no=request_version_no,
                )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to update agent skills: {str(e)}")
        raise ValueError(f"Failed to update agent skills: {str(e)}")

    # Handle related agents saving when provided
    try:
        if related_agents_dicts is not None and agent_id is not None:
            update_related_agents(
                parent_agent_id=agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                related_agents=related_agents_dicts,
            )
    except ValueError:
        # Preserve explicitly classified persistence errors.
        raise
    except Exception as e:
        logger.error(f"Failed to update related agents: {str(e)}")
        raise ValueError(f"Failed to update related agents: {str(e)}")

    # Handle related external agents saving when provided
    try:
        if request.related_external_agent_ids is not None and agent_id is not None:
            related_external_agent_ids = request.related_external_agent_ids
            # Query current relations
            current_relations = a2a_agent_db.list_external_relations_by_local_agent(
                local_agent_id=agent_id, tenant_id=tenant_id
            )
            current_external_ids = {
                rel["external_agent_id"] for rel in current_relations
            }
            new_external_ids = (
                set(related_external_agent_ids) if related_external_agent_ids else set()
            )

            # Find IDs to delete (in current but not in new)
            ids_to_delete = current_external_ids - new_external_ids
            # Find IDs to add (in new but not in current)
            ids_to_add = new_external_ids - current_external_ids

            # Soft delete removed relations
            for ext_agent_id in ids_to_delete:
                a2a_agent_db.remove_external_agent_relation(
                    local_agent_id=agent_id,
                    external_agent_id=ext_agent_id,
                    tenant_id=tenant_id,
                )

            # Add new relations
            for ext_agent_id in ids_to_add:
                try:
                    a2a_agent_db.add_external_agent_relation(
                        local_agent_id=agent_id,
                        external_agent_id=ext_agent_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                    )
                except AgentNotFoundError:
                    raise
                except ValueError:
                    # Relation already exists, skip
                    pass
    except AgentNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Failed to update related external agents: {str(e)}")
        raise ValueError(f"Failed to update related external agents: {str(e)}")

    return {"agent_id": agent_id}
