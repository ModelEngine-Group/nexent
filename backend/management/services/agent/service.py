import asyncio
import imghdr
import io
import logging
from collections import deque
from typing import Optional

from fastapi import Header
from management.services.agent.naming import (
    check_agent_value_duplicate,
    generate_unique_agent_value,
    regenerate_agent_value,
)

from consts.const import LANGUAGE, MODEL_CONFIG_MAPPING, CAN_EDIT_ALL_USER_ROLES
from consts.exceptions import (
    AppException,
    ForbiddenError,
)
from consts.error_code import ErrorCode
from consts.agent_unavailable_reasons import AgentUnavailableReason
from consts.model import (
    AgentInfoRequest,
    AgentNameBatchCheckRequest,
    AgentNameBatchRegenerateRequest,
    SkillInstanceInfoRequest,
    ToolInstanceInfoRequest,
)
from services.asset_owner_visibility import resolve_agent_list_permission
from management.services.agent.read import (
    apply_deleted_model_reason, check_agent_availability,
    project_agent_models, tool_has_deleted_model,
)
from database.agent_db import (
    batch_search_agent_display_names,
    create_agent,
    query_all_agent_info_by_tenant_id,
    query_sub_agent_relations,
    query_sub_agents_id_list,
    search_agent_info_by_agent_id,
    search_blank_sub_agent_by_main_agent_id,
    update_agent,
    update_agent_icon,
    update_related_agents
)
from database import a2a_agent_db
from database.model_management_db import (
    get_model_by_model_id,
)
from database.tool_db import (
    create_or_update_tool_by_tool_info,
    query_all_enabled_tool_instances,
    query_tool_instances_by_id,  # noqa: F401 - compatibility patch point
    query_tool_instances_by_agent_id,
    search_tools_for_sub_agent
)
from database import skill_db
from database.attachment_db import (
    get_file_stream,
)
from database.client import minio_client
from management.services.skill.service import SkillService
from database.agent_version_db import query_current_version_no, batch_search_version_names, batch_query_current_version_nos
from database.user_tenant_db import get_user_tenant_by_user_id
from database.a2a_agent_db import query_external_sub_agents
from services.prompt_template_service import (
    SYSTEM_PROMPT_TEMPLATE_ID,
    SYSTEM_PROMPT_TEMPLATE_NAME,
    get_prompt_template_summary,
)
from utils.str_utils import convert_list_to_string, convert_string_to_list
from services.conversation_management_service import (
    generate_conversation_title_service,  # noqa: F401 - compatibility patch point
    save_message_unit,  # noqa: F401 - retained as a compatibility re-export
    update_unit_status,  # noqa: F401 - retained as a compatibility re-export
)
from utils.auth_utils import get_current_user_info
from utils.config_utils import tenant_config_manager

# Monitoring utilities: bind Agent metadata once at the request boundary.

# Import monitoring utilities

logger = logging.getLogger(__name__)
AGENT_ICON_MAX_BYTES = 2 * 1024 * 1024
AGENT_ICON_CONTENT_TYPES = {
    "gif": "image/gif",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
_channel_cleanup_tasks: set[asyncio.Task[None]] = set()
_agent_stream_producer_tasks: set[asyncio.Task[None]] = set()



from management.services.agent.management import (
    _get_user_group_ids,
    _resolve_model_ids_with_fallback,
    delete_agent_impl,
    _export_agent_dict_core,
    export_agent_dict_impl,
    export_agent_dict_for_repository_impl,
    export_agent_impl,
    _collect_skill_names_from_tree,
    collect_skill_zip_entries,
    export_agent_by_agent_id,
    import_agent_impl,
    import_agent_by_agent_id,
    load_default_agents_json_file,
    clear_agent_new_mark_impl,
    list_all_agent_info_impl,
    insert_related_agent_impl,
    get_agent_id_by_name,
    get_agent_by_name_impl,
    delete_related_agent_impl,
    get_agent_call_relationship_impl,
    export_agent_with_skills_impl,
    import_agent_with_skills_impl,
    build_skill_import_conflicts,
    check_skill_conflicts_impl,
    build_sandbox_policy,
    get_sandbox_minio_client,
)

from management.services.agent.run import (
    _finalize_buffered_unit_fragments,
    _cleanup_channel_later,
    _consume_agent_stream_producer,
    _poll_runtime_cancel_signal,
    _cancel_task_on_runtime_signal,
    _resolve_user_tenant_language,
    _stream_agent_chunks,
    _agent_run_identifier,
    prepare_agent_run,
    save_messages,
    generate_stream,
    _detect_resume_position,
    run_agent_stream,
    run_agent_background,
    stop_agent_tasks,
    is_agent_running,
)

__all__ = ('_get_user_group_ids', '_resolve_model_ids_with_fallback', 'delete_agent_impl', '_export_agent_dict_core', 'export_agent_dict_impl', 'export_agent_dict_for_repository_impl', 'export_agent_impl', '_collect_skill_names_from_tree', 'collect_skill_zip_entries', 'export_agent_by_agent_id', 'import_agent_impl', 'import_agent_by_agent_id', 'load_default_agents_json_file', 'clear_agent_new_mark_impl', 'list_all_agent_info_impl', 'insert_related_agent_impl', 'get_agent_id_by_name', 'get_agent_by_name_impl', 'delete_related_agent_impl', 'get_agent_call_relationship_impl', 'export_agent_with_skills_impl', 'import_agent_with_skills_impl', 'build_skill_import_conflicts', 'check_skill_conflicts_impl', 'build_sandbox_policy', 'get_sandbox_minio_client', '_finalize_buffered_unit_fragments', '_cleanup_channel_later', '_consume_agent_stream_producer', '_poll_runtime_cancel_signal', '_cancel_task_on_runtime_signal', '_resolve_user_tenant_language', '_stream_agent_chunks', '_agent_run_identifier', 'prepare_agent_run', 'save_messages', 'generate_stream', '_detect_resume_position', 'run_agent_stream', 'run_agent_background', 'stop_agent_tasks', 'is_agent_running')

def _agent_icon_object_name(agent_id: int, tenant_id: str) -> str:
    return f"agent-icons/{tenant_id}/{agent_id}/icon"


def _detect_agent_icon_content_type(content: bytes) -> str | None:
    image_type = imghdr.what(None, content)
    return AGENT_ICON_CONTENT_TYPES.get(image_type)


async def upload_agent_icon_impl(
    agent_id: int,
    content: bytes,
    tenant_id: str,
    user_id: str,
) -> dict:
    """Validate, store, and attach a user-supplied image to an editable agent."""
    if not content:
        raise ValueError("Agent icon file is empty")
    if len(content) > AGENT_ICON_MAX_BYTES:
        raise ValueError("Agent icon must not exceed 2 MB")

    content_type = _detect_agent_icon_content_type(content)
    if content_type is None:
        raise ValueError("Agent icon must be a PNG, JPEG, GIF, or WebP image")

    agent = await get_agent_info_impl(agent_id, tenant_id, user_id=user_id)
    if agent.get("permission") != "EDIT":
        raise ForbiddenError("You do not have permission to edit this agent")

    owner_tenant_id = agent.get("tenant_id") or tenant_id
    object_name = _agent_icon_object_name(agent_id, owner_tenant_id)
    success, error = minio_client.upload_fileobj(io.BytesIO(content), object_name)
    if not success:
        raise ValueError(f"Failed to upload agent icon: {error}")

    icon_url = f"/api/agent/{agent_id}/icon"
    update_agent_icon(
        agent_id=agent_id,
        tenant_id=owner_tenant_id,
        icon_url=icon_url,
        user_id=user_id,
    )
    return {"icon_url": icon_url, "content_type": content_type}


async def get_agent_icon_impl(agent_id: int, tenant_id: str, user_id: str) -> tuple[bytes, str]:
    """Return a stored agent icon after applying normal agent visibility rules."""
    agent = await get_agent_info_impl(agent_id, tenant_id, user_id=user_id)
    if not agent.get("icon_url"):
        raise FileNotFoundError("Agent icon not found")

    owner_tenant_id = agent.get("tenant_id") or tenant_id
    stream = get_file_stream(_agent_icon_object_name(agent_id, owner_tenant_id))
    if stream is None:
        raise FileNotFoundError("Agent icon not found")

    content = stream.read()
    content_type = _detect_agent_icon_content_type(content)
    if content_type is None:
        raise FileNotFoundError("Agent icon is invalid")
    return content, content_type



async def check_agent_name_conflict_batch_impl(
    request: AgentNameBatchCheckRequest,
    authorization: str
) -> list[dict]:
    """
    Batch check name/display_name duplication for multiple agents.
    """
    _, tenant_id, _ = get_current_user_info(authorization)
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
            matches_display = item.display_name and agent.get(
                "display_name") == item.display_name
            if matches_name:
                name_conflict = True
            if matches_display:
                display_name_conflict = True
            if matches_name or matches_display:
                conflicts.append({
                    "name": agent.get("name"),
                    "display_name": agent.get("display_name"),
                })

        results.append({
            "name_conflict": name_conflict,
            "display_name_conflict": display_name_conflict,
            "conflict_agents": conflicts
        })
    return results


async def regenerate_agent_name_batch_impl(
    request: AgentNameBatchRegenerateRequest,
    authorization: str
) -> list[dict]:
    """
    Batch regenerate agent name/display_name with LLM (or suffix fallback).
    """
    _, tenant_id, _ = get_current_user_info(authorization)
    agents_cache = query_all_agent_info_by_tenant_id(tenant_id)

    existing_names = [agent.get("name")
                      for agent in agents_cache if agent.get("name")]
    existing_display_names = [agent.get(
        "display_name") for agent in agents_cache if agent.get("display_name")]

    # Always use tenant quick-config LLM model
    quick_config_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id
    )
    resolved_model_id = quick_config_model.get(
        "model_id") if quick_config_model else None
    if not resolved_model_id:
        raise ValueError(
            "No available model for regeneration. Please configure an LLM model first.")

    results: list[dict] = []
    existing_by_field = {"name": set(existing_names), "display_name": set(existing_display_names)}
    for item in request.items:
        values = {"name": item.name or "", "display_name": item.display_name or ""}
        for field_key, value in values.items():
            if value and check_agent_value_duplicate(
                field_key, value, tenant_id, agents_cache=agents_cache, exclude_agent_id=item.agent_id
            ):
                try:
                    values[field_key] = await asyncio.to_thread(
                        regenerate_agent_value,
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
                    logger.error("Failed to regenerate agent %s with LLM: %s, using fallback", field_key, exc)
                    values[field_key] = generate_unique_agent_value(
                        field_key, value, tenant_id, agents_cache, item.agent_id
                    )
            if values[field_key]:
                existing_by_field[field_key].add(values[field_key])
        results.append(values)
    return results


def get_enable_tool_id_by_agent_id(agent_id: int, tenant_id: str):
    all_tool_instance = query_all_enabled_tool_instances(
        agent_id=agent_id, tenant_id=tenant_id)
    enable_tool_id_set = set()
    for tool_instance in all_tool_instance:
        if tool_instance["enabled"]:
            enable_tool_id_set.add(tool_instance["tool_id"])
    return list(enable_tool_id_set)


async def get_creating_sub_agent_id_service(tenant_id: str, user_id: str = None) -> int:
    """
        first find the blank sub agent, if it exists, it means the agent was created before, but exited prematurely;
                                  if it does not exist, create a new one
    """
    sub_agent_id = search_blank_sub_agent_by_main_agent_id(tenant_id=tenant_id)
    if sub_agent_id:
        return sub_agent_id
    else:
        return create_agent(agent_info={"enabled": False}, tenant_id=tenant_id, user_id=user_id)["agent_id"]


async def get_agent_info_impl(agent_id: int, tenant_id: str, version_no: int = 0, user_id: Optional[str] = None):
    try:
        agent_info = search_agent_info_by_agent_id(
            agent_id, tenant_id, version_no)
        # Keep the request-scoped tenant_id unless the record explicitly provides one.
        record_tenant_id = agent_info.get("tenant_id")
        if record_tenant_id:
            tenant_id = record_tenant_id
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
        tool_info = search_tools_for_sub_agent(
            agent_id=agent_id, tenant_id=tenant_id)
        for tool in tool_info:
            tool["unavailable_reasons"] = (
                [AgentUnavailableReason.MCP_MODEL_UNAVAILABLE]
                if tool_has_deleted_model(tool, tenant_id) else []
            )
        agent_info["tools"] = tool_info
    except Exception as e:
        logger.error(f"Failed to get agent tools: {str(e)}")
        agent_info["tools"] = []

    try:
        sub_agent_id_list = query_sub_agents_id_list(
            main_agent_id=agent_id, tenant_id=tenant_id)
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
            if (selected_version_no is None or selected_version_no == 0) and selected_agent_id in resolved_version_no_map:
                selected_version_no = resolved_version_no_map[selected_agent_id]
            version_name = None
            if selected_agent_id and selected_version_no is not None:
                version_name = version_name_map.get((selected_agent_id, selected_version_no))
            enriched_relations.append({
                "agent_id": selected_agent_id,
                "agent_name": agent_name_map.get(selected_agent_id) if selected_agent_id else None,
                "version_no": selected_version_no,
                "version_name": version_name,
            })

        agent_info["sub_agent_relations"] = enriched_relations
    except Exception as e:
        logger.error(f"Failed to get sub agent id list: {str(e)}")
        agent_info["sub_agent_id_list"] = []
        agent_info["sub_agent_relations"] = []

    try:
        skill_service = SkillService()
        instances = skill_service.list_skill_instances(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no
        )
        # Keep disabled instances for their saved configuration, but do not
        # return them as selected skills in the agent configuration.
        instances = [
            instance for instance in instances if instance.get("enabled", True)
        ]

        # Fallback: verify each instance's skill_id still exists in ag_skill_info_t
        valid_skill_ids = skill_db.get_valid_skill_ids(
            tenant_id=tenant_id,
            skill_ids=[inst.get("skill_id") for inst in instances if isinstance(inst, dict)]
        )
        filtered = []
        for inst in instances:
            skill_id = inst.get("skill_id")
            if skill_id in valid_skill_ids:
                filtered.append(inst)
            else:
                logger.warning(
                    "Filtering out stale skill instance: agent_id=%s, skill_id=%s (not found in ag_skill_info_t)",
                    agent_id, skill_id,
                )
        agent_info["skills"] = filtered

    except Exception as e:
        logger.exception(f"Failed to get agent skills: {str(e)}")
        agent_info["skills"] = []

    try:
        external_agents = query_external_sub_agents(
            local_agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)
        agent_info["external_sub_agent_id_list"] = [
            ea["external_agent_id"] for ea in external_agents
        ]
    except Exception as e:
        logger.error(f"Failed to get external sub agents: {str(e)}")
        agent_info["external_sub_agent_id_list"] = []

    model_projection = project_agent_models(agent_info, tenant_id, detail=True)
    agent_info.update(model_projection.fields)

    # Get business logic model display name from model_id
    if agent_info.get("business_logic_model_id") is not None:
        business_logic_model_info = get_model_by_model_id(
            agent_info["business_logic_model_id"])
        agent_info["business_logic_model_name"] = business_logic_model_info.get(
            "display_name", None) if business_logic_model_info is not None else None
    elif "business_logic_model_name" not in agent_info:
        agent_info["business_logic_model_name"] = None

    if not agent_info.get("prompt_template_id"):
        agent_info["prompt_template_id"] = SYSTEM_PROMPT_TEMPLATE_ID
    if not agent_info.get("prompt_template_name"):
        agent_info["prompt_template_name"] = SYSTEM_PROMPT_TEMPLATE_NAME

    if agent_info.get("group_ids") is not None:
        agent_info["group_ids"] = convert_string_to_list(
            agent_info.get("group_ids"))

    # Check agent availability
    is_available, unavailable_reasons = check_agent_availability(
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_info=agent_info
    )

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

    return agent_info


async def get_creating_sub_agent_info_impl(authorization: str = Header(None)):
    user_id, tenant_id, _ = get_current_user_info(authorization)

    try:
        sub_agent_id = await get_creating_sub_agent_id_service(tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get creating sub agent id: {str(e)}")
        raise ValueError(f"Failed to get creating sub agent id: {str(e)}")

    try:
        agent_info = search_agent_info_by_agent_id(
            agent_id=sub_agent_id, tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"Failed to get sub agent info: {str(e)}")
        raise ValueError(f"Failed to get sub agent info: {str(e)}")

    try:
        enable_tool_id_list = get_enable_tool_id_by_agent_id(
            sub_agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Failed to get sub agent enable tool id list: {str(e)}")
        raise ValueError(
            f"Failed to get sub agent enable tool id list: {str(e)}")

    return {"agent_id": sub_agent_id,
            "name": agent_info.get("name"),
            "display_name": agent_info.get("display_name"),
            "description": agent_info.get("description"),
            "enable_tool_id_list": enable_tool_id_list,
            "model_ids": agent_info.get("model_ids"),
            "model_names": agent_info.get("model_names"),
            "max_steps": agent_info["max_steps"],
            "requested_output_tokens": agent_info.get("requested_output_tokens"),
            "business_description": agent_info["business_description"],
            "duty_prompt": agent_info.get("duty_prompt"),
            "constraint_prompt": agent_info.get("constraint_prompt"),
            "few_shots_prompt": agent_info.get("few_shots_prompt"),
            "sub_agent_id_list": query_sub_agents_id_list(main_agent_id=sub_agent_id, tenant_id=tenant_id)}


def _validate_requested_output_tokens_for_agent(
    request: AgentInfoRequest,
    tenant_id: str,
) -> None:
    """Deprecated compatibility validator; runtime no longer calls this path."""
    requested_output_tokens = request.requested_output_tokens
    if requested_output_tokens is None:
        return

    model_ids = list(request.model_ids or [])
    if not model_ids and request.agent_id is not None:
        try:
            existing_agent = search_agent_info_by_agent_id(
                agent_id=request.agent_id,
                tenant_id=tenant_id,
                version_no=request.version_no,
            )
            model_ids = list(existing_agent.get("model_ids") or [])
        except Exception as exc:
            logger.warning("Could not resolve existing agent models: %s", exc)
    for model_id in model_ids:
        model_info = get_model_by_model_id(model_id, tenant_id=tenant_id)
        max_output_tokens = model_info.get("max_output_tokens") if model_info else None
        if max_output_tokens is not None and requested_output_tokens > max_output_tokens:
            model_display = (
                model_info.get("display_name") if model_info else f"model_id={model_id}"
            )
            raise AppException(
                ErrorCode.COMMON_PARAMETER_INVALID,
                f"requested_output_tokens ({requested_output_tokens}) cannot exceed "
                f"max_output_tokens ({max_output_tokens}) of model '{model_display}'",
            )


async def update_agent_info_impl(request: AgentInfoRequest, authorization: str = Header(None)):
    user_id, tenant_id, _ = get_current_user_info(authorization)

    if request.example_questions is not None and len(request.example_questions) > 6:
        raise AppException(ErrorCode.COMMON_PARAMETER_INVALID, "example_questions cannot exceed 6 items")

    # These fields remain accepted for rolling-client compatibility, but the
    # automatic context policy is the only policy persisted for new updates.
    request.requested_output_tokens = None
    request.context_policy = None
    request.enable_context_manager = True

    prompt_template_id, prompt_template_name = get_prompt_template_summary(
        template_id=request.prompt_template_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    # If agent_id is None, create a new agent; otherwise, update existing
    agent_id: Optional[int] = request.agent_id
    try:
        if agent_id is None:
            # Create agent - automatically set group_ids to current user's groups
            user_group_ids = _get_user_group_ids(user_id, tenant_id)
            created = create_agent(agent_info={
                "name": request.name,
                "display_name": request.display_name,
                "description": request.description,
                "business_description": request.business_description,
                "author": request.author,
                "model_ids": request.model_ids,
                "business_logic_model_id": request.business_logic_model_id,
                "business_logic_model_name": request.business_logic_model_name,
                "prompt_template_id": prompt_template_id,
                "prompt_template_name": prompt_template_name,
                "max_steps": request.max_steps,
                "is_main_agent": request.is_main_agent if request.is_main_agent is not None else True,
                "provide_run_summary": request.provide_run_summary,
                "allow_chat_metadata": request.allow_chat_metadata if request.allow_chat_metadata is not None else False,
                "is_a2a": request.is_a2a if request.is_a2a is not None else False,
                "verification_config": request.verification_config,
                "duty_prompt": request.duty_prompt,
                "constraint_prompt": request.constraint_prompt,
                "few_shots_prompt": request.few_shots_prompt,
                "greeting_message": request.greeting_message,
                "example_questions": request.example_questions,
                "icon_url": request.icon_url,
                "enabled": request.enabled if request.enabled is not None else True,
                "group_ids": convert_list_to_string(request.group_ids) if request.group_ids else user_group_ids,
                "ingroup_permission": request.ingroup_permission
            }, tenant_id=tenant_id, user_id=user_id)
            agent_id = created["agent_id"]
        else:
            # Update agent
            request.prompt_template_id = prompt_template_id
            request.prompt_template_name = prompt_template_name
            update_agent(agent_id, request, user_id)
    except Exception as e:
        logger.error(f"Failed to update agent info: {str(e)}")
        raise ValueError(f"Failed to update agent info: {str(e)}")

    # Handle enabled tools saving when provided
    try:
        if request.enabled_tool_ids is not None and agent_id is not None:
            enabled_set = set(request.enabled_tool_ids)
            # Query existing tool instances for this agent
            existing_instances = query_tool_instances_by_agent_id(
                agent_id, tenant_id)

            # Handle unselected tool（already exist instance）→ enabled=False
            for instance in existing_instances:
                inst_tool_id = instance.get("tool_id")
                if inst_tool_id is not None and inst_tool_id not in enabled_set:
                    create_or_update_tool_by_tool_info(
                        tool_info=ToolInstanceInfoRequest(
                            tool_id=inst_tool_id,
                            agent_id=agent_id,
                            params=instance.get("params", {}),
                            enabled=False
                        ),
                        tenant_id=tenant_id,
                        user_id=user_id
                    )

            # Handle selected tool → enabled=True（create or update）
            for tool_id in enabled_set:
                # Keep existing params if any
                existing_instance = next(
                    (inst for inst in existing_instances
                     if inst.get("tool_id") == tool_id),
                    None
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
                    user_id=user_id
                )
    except Exception as e:
        logger.error(f"Failed to update agent tools: {str(e)}")
        raise ValueError(f"Failed to update agent tools: {str(e)}")

    # Handle enabled skills and their per-agent configuration.
    try:
        requested_skill_instances = getattr(request, "skill_instances", None)
        has_structured_skill_instances = isinstance(requested_skill_instances, list)
        if (
            (has_structured_skill_instances or request.enabled_skill_ids is not None)
            and agent_id is not None
        ):
            raw_version_no = getattr(request, "version_no", 0)
            request_version_no = raw_version_no if isinstance(raw_version_no, int) else 0
            requested_by_id = {}
            if has_structured_skill_instances:
                for requested_instance in requested_skill_instances:
                    skill_id = requested_instance.skill_id
                    if skill_id in requested_by_id:
                        raise ValueError(f"Duplicate skill_id in skill_instances: {skill_id}")
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
                    raise ValueError(
                        f"Invalid or unavailable skill IDs: {sorted(missing_skill_ids)}"
                    )

            # Query existing skill instances for this agent
            existing_instances = skill_db.query_skill_instances_by_agent_id(
                agent_id, tenant_id, version_no=request_version_no)

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
                    (inst for inst in existing_instances
                     if inst.get("skill_id") == skill_id),
                    None
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
    except Exception as e:
        logger.error(f"Failed to update agent skills: {str(e)}")
        raise ValueError(f"Failed to update agent skills: {str(e)}")

    # Handle related agents saving when provided
    try:
        if request.related_agent_ids is not None and agent_id is not None:
            related_agent_ids = request.related_agent_ids
            # Check for circular dependencies using BFS
            search_list = deque(related_agent_ids)
            agent_id_set = set()

            while len(search_list):
                left_ele = search_list.popleft()
                if left_ele == agent_id:
                    raise ValueError(
                        "Circular dependency detected: Agent cannot be related to itself or create circular calls")
                if left_ele in agent_id_set:
                    continue
                else:
                    agent_id_set.add(left_ele)
                sub_ids = query_sub_agents_id_list(
                    main_agent_id=left_ele, tenant_id=tenant_id)
                search_list.extend(sub_ids)

            # Update related agents - use related_agents if provided, otherwise build from IDs
            if request.related_agents:
                related_agents_dicts = [
                    {"agent_id": ra.agent_id, "version_no": ra.version_no}
                    for ra in request.related_agents
                ]
            else:
                related_agents_dicts = [
                    {"agent_id": aid, "version_no": None}
                    for aid in related_agent_ids
                ]

            update_related_agents(
                parent_agent_id=agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                related_agents=related_agents_dicts,
            )
    except ValueError:
        # Re-raise ValueError (circular dependency) as-is
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
                local_agent_id=agent_id,
                tenant_id=tenant_id
            )
            current_external_ids = {
                rel["external_agent_id"] for rel in current_relations
            }
            new_external_ids = set(
                related_external_agent_ids) if related_external_agent_ids else set()

            # Find IDs to delete (in current but not in new)
            ids_to_delete = current_external_ids - new_external_ids
            # Find IDs to add (in new but not in current)
            ids_to_add = new_external_ids - current_external_ids

            # Soft delete removed relations
            for ext_agent_id in ids_to_delete:
                a2a_agent_db.remove_external_agent_relation(
                    local_agent_id=agent_id,
                    external_agent_id=ext_agent_id,
                    tenant_id=tenant_id
                )

            # Add new relations
            for ext_agent_id in ids_to_add:
                try:
                    a2a_agent_db.add_external_agent_relation(
                        local_agent_id=agent_id,
                        external_agent_id=ext_agent_id,
                        tenant_id=tenant_id,
                        user_id=user_id
                    )
                except ValueError:
                    # Relation already exists, skip
                    pass
    except Exception as e:
        logger.error(f"Failed to update related external agents: {str(e)}")
        raise ValueError(f"Failed to update related external agents: {str(e)}")

    return {"agent_id": agent_id}
