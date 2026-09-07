import asyncio
import base64
import io
import json
import logging
import os
import zipfile
from collections import deque
from typing import Any, Optional, Dict, List

from fastapi import Header
from fastapi.responses import JSONResponse

from agents.create_agent_info import create_tool_config_list
from services.agent_version_service import publish_version_impl
from consts.const import TOOL_TYPE_MAPPING, \
    MODEL_CONFIG_MAPPING, CAN_EDIT_ALL_USER_ROLES, PERMISSION_PRIVATE
from consts.exceptions import (
    SkillDuplicateError,
)
from consts.model import (
    ExportAndImportAgentInfo,
    ExportAndImportDataFormat,
    MCPInfo,
    SkillInstanceInfoRequest,
    SkillResolution,
    SkillZipEntry,
    ToolInstanceInfoRequest,
    ToolSourceEnum,
)
from services.asset_owner_visibility import resolve_agent_list_permission
from management.services.agent.read import (
    apply_deleted_model_reason, apply_duplicate_name_availability_rules, check_agent_availability,
    project_agent_models,
)
from management.services.agent.naming import check_agent_value_duplicate, generate_unique_agent_value
from database.agent_db import (
    create_agent,
    delete_agent_by_id,
    delete_agent_relationship,
    delete_related_agent,
    insert_related_agent,
    query_all_agent_info_by_tenant_id,
    query_sub_agent_relations,
    query_sub_agents_id_list,
    resolve_sub_agent_version_no,
    search_agent_id_by_agent_name,
    search_agent_info_by_agent_id,
    clear_agent_new_mark
)
from database.model_management_db import (
    get_model_by_model_id,
    get_model_id_by_display_name,
)
from database.remote_mcp_db import get_mcp_server_by_name_and_tenant
from database.tool_db import (
    create_or_update_tool_by_tool_info,
    delete_tools_by_agent_id,
    query_all_tools,
    query_tool_instances_by_id,  # noqa: F401 - compatibility patch point
    search_tools_for_sub_agent
)
from database import skill_db
from management.services.skill.service import SkillService
from database.agent_version_db import query_version_list
from database.group_db import query_group_ids_by_user
from database.user_tenant_db import get_user_tenant_by_user_id
from database.a2a_agent_db import get_server_agent_ids
from services.prompt_template_service import (
    SYSTEM_PROMPT_TEMPLATE_ID,
    SYSTEM_PROMPT_TEMPLATE_NAME,
)
from utils.str_utils import convert_list_to_string, convert_string_to_list
from utils.skill_import_utils import generate_available_copy_skill_name
from services.conversation_management_service import (
    generate_conversation_title_service,  # noqa: F401 - compatibility patch point
    save_message_unit,  # noqa: F401 - retained as a compatibility re-export
    update_unit_status,  # noqa: F401 - retained as a compatibility re-export
)
from utils.auth_utils import get_current_user_info
from utils.config_utils import tenant_config_manager
from utils.skill_import_utils import generate_available_copy_skill_name

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


def _get_user_group_ids(user_id: str, tenant_id: str) -> str:
    """
    Get user's group IDs as a comma-separated string.

    Args:
        user_id: User ID
        tenant_id: Tenant ID

    Returns:
        Comma-separated string of group IDs
    """
    try:
        group_ids = query_group_ids_by_user(user_id)
        return convert_list_to_string(group_ids)
    except Exception as e:
        logger.warning(
            f"Failed to get user groups for user {user_id}: {str(e)}")
        return ""




def _resolve_model_ids_with_fallback(
    model_ids: List[int] | None,
    model_display_names: List[str] | None,
    model_label: str,
    tenant_id: str,
) -> List[int] | None:
    """
    Resolve model_ids from an import payload, merging two sources in priority order:

      1. Explicit `model_ids` provided in the payload. Each id is validated against
         the target tenant's catalog; missing ids are dropped (logged).
      2. `model_display_names` resolved via ``get_model_id_by_display_name`` to
         cover ids that were lost in step 1.
      3. A single quick config LLM model id is appended if any of the desired
         models could not be resolved (so the agent always has at least one
         usable model after import).

    Args:
        model_ids: Optional list of model ids from the export payload.
        model_display_names: Optional list of display names for fallback lookup.
        model_label: Label for logging (e.g., "Model", "Business logic model").
        tenant_id: Tenant ID for catalog lookup.

    Returns:
        Ordered, de-duplicated list of resolved model_ids; empty list if no
        input was provided (caller should skip persisting model_ids).
    """
    if not model_ids and not model_display_names:
        return None

    resolved_ids: List[int] = []
    seen: set[int] = set()
    missing_ids: List[int] = []

    # Step 1: validate explicit ids against the current tenant catalog.
    for mid in model_ids or []:
        if mid in seen:
            continue
        info = get_model_by_model_id(mid)
        if info:
            seen.add(mid)
            resolved_ids.append(mid)
        else:
            missing_ids.append(mid)

    if resolved_ids:
        logger.info(
            f"{model_label} import: kept {len(resolved_ids)}/{len(model_ids or [])} "
            f"explicit model_ids in tenant {tenant_id}"
            + (f"; missing ids: {missing_ids}" if missing_ids else "")
        )
        # When the caller explicitly provides model_ids, the selection is intentional —
        # do NOT supplement with extra models from model_display_names.
        return resolved_ids

    # Step 2: resolve remaining slots by display name.
    # Only reached when model_ids was empty/None (caller did not specify a preference),
    # so we use display names to find a suitable model in the target tenant.
    used_name_indices: set[int] = set()
    missing_names: List[str] = []

    for idx, display_name in enumerate(model_display_names or []):
        if not display_name:
            continue

        resolved_id = get_model_id_by_display_name(display_name, tenant_id)
        if resolved_id and resolved_id not in seen:
            seen.add(resolved_id)
            resolved_ids.append(resolved_id)
            used_name_indices.add(idx)
        else:
            missing_names.append(display_name)
            used_name_indices.add(idx)

    if model_display_names:
        logger.info(
            f"{model_label} import: resolved {len(used_name_indices) - len(missing_names)}/"
            f"{len(model_display_names)} display names in tenant {tenant_id}"
            + (f"; missing names: {missing_names}" if missing_names else "")
        )

    # Step 3: quick config LLM fallback when still nothing resolved.
    if not resolved_ids and (missing_ids or missing_names):
        quick_config_model = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["llm"],
            tenant_id=tenant_id,
        )
        if quick_config_model:
            fallback_id = quick_config_model.get("model_id")
            if fallback_id is not None and fallback_id not in seen:
                logger.warning(
                    f"{model_label} import: no usable model found in tenant {tenant_id} "
                    f"(missing ids: {missing_ids}, missing names: {missing_names}); "
                    f"falling back to quick config LLM model "
                    f"'{quick_config_model.get('display_name')}' (model_id: {fallback_id})"
                )
                resolved_ids.append(fallback_id)

    return resolved_ids




async def delete_agent_impl(agent_id: int, tenant_id: str, user_id: str):
    """
    Delete an agent and all related data.

    Args:
        agent_id: Agent ID to delete
        tenant_id: Tenant ID
        user_id: User ID performing the deletion
    """
    try:
        try:
            agent = search_agent_info_by_agent_id(agent_id, tenant_id)
        except ValueError:
            agent = None
        is_tenant_owned_agent = bool(
            agent and str(agent.get("tenant_id") or "") == str(tenant_id)
        )
        delete_agent_by_id(agent_id, tenant_id, user_id)
        delete_agent_relationship(agent_id, tenant_id, user_id)
        delete_tools_by_agent_id(agent_id, tenant_id, user_id)
        skill_db.delete_skills_by_agent_id(agent_id, tenant_id, user_id)
        if is_tenant_owned_agent:
            from services.tag_management_service import TagManagementService

            TagManagementService.cleanup_resource_assignments(
                tenant_id, "agent", str(agent_id), user_id
            )
    except Exception as e:
        logger.error(f"Failed to delete agent: {str(e)}")
        raise ValueError(f"Failed to delete agent: {str(e)}")


async def _export_agent_dict_core(
    root_agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int = 0,
) -> dict:
    """Build ExportAndImportDataFormat dict for an agent tree at the given version."""
    export_agent_dict = {}
    search_list: deque = deque([(root_agent_id, version_no)])
    visited: set = set()

    mcp_info_set = set()

    while search_list:
        current_agent_id, current_version_no = search_list.popleft()
        visit_key = (current_agent_id, current_version_no)
        if visit_key in visited:
            continue
        visited.add(visit_key)

        agent_info = await export_agent_by_agent_id(
            agent_id=current_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=current_version_no,
        )

        for tool in agent_info.tools:
            if tool.source == "mcp" and tool.usage:
                mcp_info_set.add(tool.usage)

        relations = query_sub_agent_relations(
            main_agent_id=current_agent_id,
            tenant_id=tenant_id,
            version_no=current_version_no,
        )
        for rel in relations:
            child_id = rel["selected_agent_id"]
            child_version = resolve_sub_agent_version_no(
                child_id,
                rel.get("selected_agent_version_no"),
                tenant_id,
            )
            search_list.append((child_id, child_version))

        export_agent_dict[str(agent_info.agent_id)] = agent_info

    mcp_info_list = []
    for mcp_server_name in mcp_info_set:
        mcp_url = get_mcp_server_by_name_and_tenant(mcp_server_name, tenant_id)
        mcp_info_list.append(
            MCPInfo(mcp_server_name=mcp_server_name, mcp_url=mcp_url))

    export_data = ExportAndImportDataFormat(
        agent_id=root_agent_id,
        agent_info=export_agent_dict,
        mcp_info=mcp_info_list,
    )
    return export_data.model_dump()


async def export_agent_dict_impl(
    agent_id: int,
    authorization: str = Header(None),
    version_no: int = 0,
) -> dict:
    """
    Export the configuration information of the specified agent and all its sub-agents.

    Args:
        agent_id (int): The ID of the agent to export.
        authorization (str): User authentication information, obtained from the Header.
        version_no (int): Version to export. Default 0 = draft.

    Returns:
        dict: ExportAndImportDataFormat as a plain dict (via model_dump).
    """
    user_id, tenant_id, _ = get_current_user_info(authorization)
    return await _export_agent_dict_core(
        root_agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )


async def export_agent_dict_for_repository_impl(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int,
) -> dict:
    """Export agent tree for marketplace repository storage (no HTTP auth header)."""
    return await _export_agent_dict_core(
        root_agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )


async def export_agent_impl(
    agent_id: int,
    authorization: str = Header(None),
    version_no: int = 0,
) -> str:
    """Serialize export_agent_dict_impl output to a JSON string for download or ZIP embedding."""
    agent_dict = await export_agent_dict_impl(
        agent_id, authorization, version_no=version_no
    )
    return json.dumps(agent_dict)


def _collect_skill_names_from_tree(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    visited: Optional[set] = None,
) -> List[str]:
    """Collect unique skill names from an agent tree at the given version."""
    if visited is None:
        visited = set()

    skill_names: List[str] = []
    seen_names: set = set()

    def _walk(current_agent_id: int, current_version_no: int) -> None:
        visit_key = (current_agent_id, current_version_no)
        if visit_key in visited:
            return
        visited.add(visit_key)

        skill_instances = skill_db.query_skill_instances_by_agent_id(
            agent_id=current_agent_id,
            tenant_id=tenant_id,
            version_no=current_version_no,
        )
        for inst in skill_instances:
            skill_id = inst.get("skill_id")
            skill = skill_db.get_skill_by_id(skill_id, tenant_id)
            if skill:
                name = skill.get("name")
                if name and name not in seen_names:
                    seen_names.add(name)
                    skill_names.append(name)

        relations = query_sub_agent_relations(
            main_agent_id=current_agent_id,
            tenant_id=tenant_id,
            version_no=current_version_no,
        )
        for rel in relations:
            child_id = rel["selected_agent_id"]
            child_version = resolve_sub_agent_version_no(
                child_id,
                rel.get("selected_agent_version_no"),
                tenant_id,
            )
            _walk(child_id, child_version)

    _walk(agent_id, version_no)
    return skill_names


def collect_skill_zip_entries(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0,
) -> List[SkillZipEntry]:
    """Export skill ZIP payloads for all skills in an agent tree."""
    skill_names = _collect_skill_names_from_tree(agent_id, tenant_id, version_no)
    if not skill_names:
        return []

    skill_service = SkillService(tenant_id=tenant_id)
    exported = skill_service.export_skills_by_names(skill_names, tenant_id)
    return [
        SkillZipEntry(
            skill_name=entry["skill_name"],
            skill_zip_base64=entry["skill_zip_base64"],
        )
        for entry in exported
    ]


async def export_agent_by_agent_id(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int = 0,
) -> ExportAndImportAgentInfo:
    """Export a single agent's information based on agent_id and version_no."""
    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )
    agent_relation_in_db = query_sub_agents_id_list(
        main_agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )
    tool_list = await create_tool_config_list(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )

    # Collect skill names from skill instances
    skill_names: List[str] = []
    try:
        skill_instances = skill_db.query_skill_instances_by_agent_id(
            agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
        )
        for inst in skill_instances:
            skill_id = inst.get("skill_id")
            skill = skill_db.get_skill_by_id(skill_id, tenant_id)
            if skill:
                name = skill.get("name")
                if name:
                    skill_names.append(name)
    except Exception as e:
        logger.warning(
            f"Failed to collect skill instances for agent {agent_id}: {e}")

    # Check if any tool is KnowledgeBaseSearchTool and set its metadata to empty dict
    for tool in tool_list:
        if tool.class_name in ["KnowledgeBaseSearchTool", "AnalyzeTextFileTool", "AnalyzeImageTool", "AnalyzeAudioTool", "AnalyzeVideoTool", "DataMateSearchTool"]:
            tool.metadata = {}
        if tool.class_name == "IndependentAidpSearchTool":
            tool.metadata = {}
            if isinstance(tool.params, dict) and "api_key" in tool.params:
                tool.params["api_key"] = ""

    # Resolve model display names from model_ids array
    model_ids_list = agent_info.get("model_ids") or []
    model_names_list: List[str] = []
    for mid in model_ids_list:
        mid_info = get_model_by_model_id(mid)
        if mid_info:
            display = mid_info.get("display_name")
            if display:
                model_names_list.append(display)

    # Get business_logic_model_id and business logic model display name
    business_logic_model_id = agent_info.get("business_logic_model_id")
    business_logic_model_display_name = None
    if business_logic_model_id is not None:
        business_logic_model_info = get_model_by_model_id(
            business_logic_model_id)
        business_logic_model_display_name = business_logic_model_info.get(
            "display_name") if business_logic_model_info is not None else None

    agent_info = ExportAndImportAgentInfo(agent_id=agent_id,
                                          tenant_id=agent_info["tenant_id"],
                                          name=agent_info["name"],
                                          display_name=agent_info["display_name"],
                                          description=agent_info["description"],
                                          author=agent_info.get("author"),
                                          max_steps=agent_info["max_steps"],
                                          requested_output_tokens=agent_info.get("requested_output_tokens"),
                                          is_main_agent=agent_info.get("is_main_agent", True),
                                          provide_run_summary=agent_info["provide_run_summary"],
                                          allow_chat_metadata=agent_info.get("allow_chat_metadata", False),
                                          verification_config=agent_info.get("verification_config"),
                                          context_policy=agent_info.get("context_policy"),
                                          duty_prompt=agent_info.get(
                                              "duty_prompt"),
                                          constraint_prompt=agent_info.get(
                                              "constraint_prompt"),
                                          few_shots_prompt=agent_info.get(
                                              "few_shots_prompt"),
                                          enabled=agent_info["enabled"],
                                          tools=tool_list,
                                          managed_agents=agent_relation_in_db,
                                          model_ids=model_ids_list,
                                          model_names=model_names_list,
                                          business_logic_model_id=business_logic_model_id,
                                          business_logic_model_name=business_logic_model_display_name,
                                          skill_names=skill_names,
                                          prompt_template_id=agent_info.get(
                                              "prompt_template_id"),
                                          prompt_template_name=agent_info.get("prompt_template_name"),
                                          greeting_message=agent_info.get("greeting_message"),
                                          example_questions=agent_info.get("example_questions"))
    return agent_info


async def import_agent_impl(
    agent_info: ExportAndImportDataFormat,
    authorization: str = Header(None),
    force_import: bool = False,
    skill_name_to_id: Optional[Dict[str, int]] = None,
    resolve_name_conflicts: bool = False,
):
    """
    Import agent using DFS.

    Note:
        MCP server registration and tool list refresh are now handled
        on the frontend / dedicated MCP configuration flows.
        The backend import logic only consumes the tools that already
        exist for the current tenant.
    """
    user_id, tenant_id, _ = get_current_user_info(authorization)
    agent_id = agent_info.agent_id

    agent_stack = deque([agent_id])
    agent_id_set = set()
    mapping_agent_id = {}

    while len(agent_stack):
        need_import_agent_id = agent_stack.pop()
        if need_import_agent_id in agent_id_set:
            continue

        need_import_agent_info = agent_info.agent_info[str(
            need_import_agent_id)]
        managed_agents = need_import_agent_info.managed_agents

        if agent_id_set.issuperset(managed_agents):
            new_agent_id = await import_agent_by_agent_id(
                import_agent_info=agent_info.agent_info[str(
                    need_import_agent_id)],
                tenant_id=tenant_id,
                user_id=user_id,
                skip_duplicate_regeneration=force_import,
                resolve_name_conflicts=resolve_name_conflicts,
            )
            mapping_agent_id[need_import_agent_id] = new_agent_id

            agent_id_set.add(need_import_agent_id)
            # Establish relationships with sub-agents - new sub-agents always use version 1
            for sub_agent_id in managed_agents:
                insert_related_agent(parent_agent_id=mapping_agent_id[need_import_agent_id],
                                     child_agent_id=mapping_agent_id[sub_agent_id],
                                     tenant_id=tenant_id,
                                     user_id=user_id,
                                     selected_agent_version_no=1)
        else:
            # Current agent still has sub-agents that haven't been imported
            agent_stack.append(need_import_agent_id)
            agent_stack.extend(managed_agents)

    # Return the mapping of original IDs to new IDs
    return mapping_agent_id


async def import_agent_by_agent_id(
    import_agent_info: ExportAndImportAgentInfo,
    tenant_id: str,
    user_id: str,
    skip_duplicate_regeneration: bool = False,
    resolve_name_conflicts: bool = False,
):
    tool_list = []

    # query all tools in the current tenant
    tool_info = query_all_tools(tenant_id=tenant_id)
    db_all_tool_info_dict = {
        f"{tool['class_name']}&{tool['source']}": tool for tool in tool_info}

    for tool in import_agent_info.tools:
        db_tool_info: dict | None = db_all_tool_info_dict.get(
            f"{tool.class_name}&{tool.source}", None)

        if db_tool_info is None:
            raise ValueError(
                f"Cannot find tool {tool.class_name} in {tool.source}.")

        db_tool_info_params = db_tool_info["params"]
        db_tool_info_params_name_set = set(
            [param_info["name"] for param_info in db_tool_info_params])

        for tool_param_name in tool.params:
            if tool_param_name not in db_tool_info_params_name_set:
                raise ValueError(
                    f"Parameter {tool_param_name} in tool {tool.class_name} from {tool.source} cannot be found.")

        tool_list.append(ToolInstanceInfoRequest(tool_id=db_tool_info['tool_id'],
                                                 agent_id=-1,
                                                 enabled=True,
                                                 params=tool.params))
    # check the validity of the agent parameters
    if import_agent_info.max_steps <= 0:
        raise ValueError(
            f"Invalid max steps: {import_agent_info.max_steps}. max steps must be greater than 0.")
    if not import_agent_info.name.isidentifier():
        raise ValueError(
            f"Invalid agent name: {import_agent_info.name}. agent name must be a valid python variable name.")

    # Resolve model_ids from the export payload.
    # Payload may carry explicit model_ids (preferred when still valid in the
    # target tenant) plus model_names for cross-tenant compatibility.
    model_ids = _resolve_model_ids_with_fallback(
        model_ids=import_agent_info.model_ids,
        model_display_names=import_agent_info.model_names,
        model_label="Model",
        tenant_id=tenant_id,
    )

    business_logic_model_id = _resolve_model_ids_with_fallback(
        model_ids=[import_agent_info.business_logic_model_id]
        if import_agent_info.business_logic_model_id is not None
        else None,
        model_display_names=[import_agent_info.business_logic_model_name]
        if import_agent_info.business_logic_model_name
        else None,
        model_label="Business logic model",
        tenant_id=tenant_id,
    )

    agent_names = {"name": import_agent_info.name, "display_name": import_agent_info.display_name}
    if resolve_name_conflicts:
        agents_cache = query_all_agent_info_by_tenant_id(tenant_id)
        for field_key, value in agent_names.items():
            if check_agent_value_duplicate(field_key, value, tenant_id, agents_cache=agents_cache):
                agent_names[field_key] = generate_unique_agent_value(
                    field_key, value, tenant_id, agents_cache=agents_cache
                )

    # create a new agent - use current user's groups instead of imported group_ids
    user_group_ids = _get_user_group_ids(user_id, tenant_id)
    new_agent = create_agent(agent_info={"name": agent_names["name"],
                                         "display_name": agent_names["display_name"],
                                         "description": import_agent_info.description,
                                         "author": import_agent_info.author,
                                         "model_ids": model_ids,
                                         "business_logic_model_id": (
                                             business_logic_model_id[0]
                                             if business_logic_model_id else None
                                         ),
                                         "business_logic_model_name": import_agent_info.business_logic_model_name,
                                         "prompt_template_id": import_agent_info.prompt_template_id or SYSTEM_PROMPT_TEMPLATE_ID,
                                         "prompt_template_name": import_agent_info.prompt_template_name or SYSTEM_PROMPT_TEMPLATE_NAME,
                                         "max_steps": import_agent_info.max_steps,
                                         "is_main_agent": getattr(import_agent_info, "is_main_agent", True),
                                         "provide_run_summary": import_agent_info.provide_run_summary,
                                         "allow_chat_metadata": import_agent_info.allow_chat_metadata,
                                         "verification_config": getattr(import_agent_info, "verification_config", None),
                                         "duty_prompt": import_agent_info.duty_prompt,
                                         "constraint_prompt": import_agent_info.constraint_prompt,
                                         "few_shots_prompt": import_agent_info.few_shots_prompt,
                                         "enabled": import_agent_info.enabled,
                                         "group_ids": user_group_ids,
                                         "greeting_message": getattr(import_agent_info, "greeting_message", None),
                                         "example_questions": getattr(import_agent_info, "example_questions", None)},
                             tenant_id=tenant_id,
                             user_id=user_id)
    new_agent_id = new_agent["agent_id"]
    # create tool_instance
    for tool in tool_list:
        tool.agent_id = new_agent_id
        create_or_update_tool_by_tool_info(
            tool_info=tool, tenant_id=tenant_id, user_id=user_id)
    # Auto-publish initial version V1 for market-imported agents
    try:
        publish_version_impl(
            agent_id=new_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_name="V1",
            release_note="Initial version from Agent Market"
        )
    except Exception as e:
        logger.warning(
            f"Failed to auto-publish version V1 for agent {new_agent_id}: {str(e)}")
    return new_agent_id


def load_default_agents_json_file(default_agent_path):
    # load all json files in the folder
    all_json_files = []
    agent_file_list = os.listdir(default_agent_path)
    for agent_file in agent_file_list:
        if agent_file.endswith(".json"):
            with open(os.path.join(default_agent_path, agent_file), "r", encoding="utf-8") as f:
                agent_json = json.load(f)

            export_agent_info = ExportAndImportAgentInfo.model_validate(
                agent_json)
            all_json_files.append(export_agent_info)
    return all_json_files


async def clear_agent_new_mark_impl(agent_id: int, tenant_id: str, user_id: str):
    """
    Clear the NEW mark for an agent

    Args:
        agent_id (int): Agent ID
        tenant_id (str): Tenant ID
        user_id (str): User ID (for audit purposes)
    """
    rowcount = clear_agent_new_mark(agent_id, tenant_id, user_id)
    logger.info(
        f"clear_agent_new_mark_impl called for agent_id={agent_id}, tenant_id={tenant_id}, user_id={user_id}, affected_rows={rowcount}")
    return rowcount


async def list_all_agent_info_impl(tenant_id: str, user_id: str) -> list[dict]:
    """
    list all agent info

    Args:
        tenant_id (str): tenant id
        user_id (str): user id (used for permission calculation and filtering)

    Raises:
        ValueError: failed to query all agent info

    Returns:
        list: list of agent info
    """
    try:
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()

        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

        # For DEV/USER, restrict visible agents to those whose group_ids overlap user's groups.
        user_group_ids: set[int] = set()
        if not can_edit_all:
            try:
                user_group_ids = set(query_group_ids_by_user(user_id) or [])
            except Exception as e:
                logger.warning(
                    f"Failed to query user group ids for filtering: user_id={user_id}, err={str(e)}"
                )
                user_group_ids = set()

        agent_list = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)

        # Get all agent IDs that are registered as A2A Server agents
        a2a_server_agent_ids = get_server_agent_ids(tenant_id)

        model_cache: Dict[int, Optional[dict]] = {}
        enriched_agents: list[dict] = []

        for agent in agent_list:
            if not agent["enabled"]:
                continue

            # Apply visibility filter for DEV/USER based on group overlap
            if not can_edit_all:
                agent_group_ids = set(
                    convert_string_to_list(agent.get("group_ids")))
                ingroup_permission = agent.get("ingroup_permission")
                is_creator = str(agent.get("created_by")) == str(user_id)
                # Hide agent if: no group overlap OR (ingroup_permission is PRIVATE AND user is not creator)
                if not is_creator and (len(user_group_ids.intersection(agent_group_ids)) == 0 or ingroup_permission == PERMISSION_PRIVATE):
                    continue

            # Filter out deleted models (delete_flag='Y' in model_record_t)
            model_projection = project_agent_models(agent, tenant_id, model_cache)
            agent.update(model_projection.fields)

            # Use shared availability check function
            _, unavailable_reasons = check_agent_availability(
                agent_id=agent["agent_id"],
                tenant_id=tenant_id,
                agent_info=agent,
                model_cache=model_cache
            )
            _, unavailable_reasons = apply_deleted_model_reason(
                not unavailable_reasons,
                unavailable_reasons,
                model_projection.deleted_model_ids,
            )

            # Preserve the raw data so we can adjust availability for duplicates
            enriched_agents.append({
                "raw_agent": agent,
                "unavailable_reasons": unavailable_reasons,
            })

        # Handle duplicate name/display_name: keep the earliest created agent available,
        # mark later ones as unavailable due to duplication.
        apply_duplicate_name_availability_rules(enriched_agents)

        simple_agent_list: list[dict] = []
        for entry in enriched_agents:
            agent = entry["raw_agent"]
            unavailable_reasons = list(
                dict.fromkeys(entry["unavailable_reasons"]))

            model_ids = agent["model_ids"]
            model_names = agent["model_names"]
            first_model_name = agent["model_name"]

            # Permission logic (ASSET_OWNER-scoped + non-ASSET_OWNER role => READ_ONLY first):
            permission = resolve_agent_list_permission(
                user_role=user_role,
                agent=agent,
                user_id=user_id,
                can_edit_all=can_edit_all,
            )

            simple_agent_list.append({
                "agent_id": agent["agent_id"],
                "name": agent["name"] if agent["name"] else agent["display_name"],
                "display_name": agent["display_name"] if agent["display_name"] else agent["name"],
                "description": agent["description"],
                "author": agent.get("author"),
                "model_ids": model_ids,
                "model_names": model_names,
                "model_name": first_model_name,
                "is_available": len(unavailable_reasons) == 0,
                "unavailable_reasons": unavailable_reasons,
                "is_new": agent.get("is_new", False),
                "group_ids": convert_string_to_list(agent.get("group_ids")),
                "permission": permission,
                "is_published": agent.get("current_version_no") is not None,
                "current_version_no": agent.get("current_version_no"),
                "is_a2a_server": agent["agent_id"] in a2a_server_agent_ids,
                "allow_chat_metadata": bool(agent.get("allow_chat_metadata", False)),
            })

        return simple_agent_list
    except Exception as e:
        logger.error(f"Failed to query all agent info: {str(e)}")
        raise ValueError(f"Failed to query all agent info: {str(e)}")




def insert_related_agent_impl(parent_agent_id, child_agent_id, tenant_id):
    # search the agent by bfs, check if there is a circular call
    search_list = deque([child_agent_id])
    agent_id_set = set()

    while len(search_list):
        left_ele = search_list.popleft()
        if left_ele == parent_agent_id:
            return JSONResponse(
                status_code=500,
                content={
                    "message": "There is a circular call in the agent", "status": "error"}
            )
        if left_ele in agent_id_set:
            continue
        else:
            agent_id_set.add(left_ele)
        sub_ids = query_sub_agents_id_list(
            main_agent_id=left_ele, tenant_id=tenant_id)
        search_list.extend(sub_ids)

    result = insert_related_agent(parent_agent_id, child_agent_id, tenant_id)
    if result:
        return JSONResponse(
            status_code=200,
            content={"message": "Insert relation success", "status": "success"}
        )
    else:
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to insert relation", "status": "error"}
        )


# Debug runs have no persisted conversation. Use their server-generated ID to
# register and stop them without affecting conversation-backed runs.
async def get_agent_id_by_name(agent_name: str, tenant_id: str) -> int:
    """
    Resolve unique agent id by its unique name under the same tenant.
    """
    if not agent_name:
        raise Exception("agent_name required")
    try:
        return search_agent_id_by_agent_name(agent_name, tenant_id)
    except Exception as _:
        logger.error(
            f"Failed to find agent id with '{agent_name}' in tenant {tenant_id}")
        raise Exception("agent not found")


def get_agent_by_name_impl(agent_name: str, tenant_id: str) -> dict:
    """
    Resolve agent id and latest published version by agent name.

    Returns:
        dict with agent_id and latest_version_no (may be None)
    """
    if not agent_name:
        raise Exception("agent_name required")
    try:
        agent_id = search_agent_id_by_agent_name(agent_name, tenant_id)
        versions = query_version_list(agent_id, tenant_id)
        latest_version = versions[0]["version_no"] if versions else None
        return {"agent_id": agent_id, "latest_version_no": latest_version}
    except Exception as _:
        logger.error(
            f"Failed to find agent '{agent_name}' in tenant {tenant_id}")
        raise Exception("agent not found")


def delete_related_agent_impl(parent_agent_id: int, child_agent_id: int, tenant_id: str):
    """
    Delete the relationship between a parent agent and its child agent

    Args:
        parent_agent_id (int): The ID of the parent agent
        child_agent_id (int): The ID of the child agent to be removed from parent
        tenant_id (str): The tenant ID for data isolation

    Raises:
        ValueError: When deletion operation fails
    """
    try:
        return delete_related_agent(parent_agent_id, child_agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Failed to delete related agent: {str(e)}")
        raise Exception(f"Failed to delete related agent: {str(e)}")


def get_agent_call_relationship_impl(agent_id: int, tenant_id: str) -> dict:
    """
    Get agent call relationship tree including tools and sub-agents

    Args:
        agent_id (int): agent id
        tenant_id (str): tenant id

    Returns:
        dict: agent call relationship tree structure
    """
    def _normalize_tool_type(source: str) -> str:
        """Normalize the source from database to the expected display type for testing."""
        if not source:
            return "UNKNOWN"
        s = str(source)
        ls = s.lower()
        if ls in TOOL_TYPE_MAPPING:
            return TOOL_TYPE_MAPPING[ls]
        # Unknown source: capitalize first letter, keep the rest unchanged (unknown_source -> Unknown_source)
        return s[:1].upper() + s[1:]

    try:

        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id)
        if not agent_info:
            raise ValueError(f"Agent {agent_id} not found")

        tool_info = search_tools_for_sub_agent(
            agent_id=agent_id, tenant_id=tenant_id)
        tools = []
        for tool in tool_info:
            tool_name = tool.get("name") or tool.get(
                "tool_name") or str(tool["tool_id"])
            tool_source = tool.get("source", ToolSourceEnum.LOCAL.value)
            tool_type = _normalize_tool_type(tool_source)

            tools.append({
                "tool_id": tool["tool_id"],
                "name": tool_name,
                "type": tool_type
            })

        def get_sub_agents_recursive(parent_agent_id: int, depth: int = 0, max_depth: int = 5) -> list:
            if depth >= max_depth:
                return []

            sub_agent_id_list = query_sub_agents_id_list(
                main_agent_id=parent_agent_id, tenant_id=tenant_id)
            sub_agents = []

            for sub_agent_id in sub_agent_id_list:
                try:
                    sub_agent_info = search_agent_info_by_agent_id(
                        sub_agent_id, tenant_id)
                    if sub_agent_info:

                        sub_tool_info = search_tools_for_sub_agent(
                            agent_id=sub_agent_id, tenant_id=tenant_id)
                        sub_tools = []
                        for tool in sub_tool_info:
                            tool_name = tool.get("name") or tool.get(
                                "tool_name") or str(tool["tool_id"])
                            tool_source = tool.get(
                                "source", ToolSourceEnum.LOCAL.value)
                            tool_type = _normalize_tool_type(tool_source)

                            sub_tools.append({
                                "tool_id": tool["tool_id"],
                                "name": tool_name,
                                "type": tool_type
                            })

                        deeper_sub_agents = get_sub_agents_recursive(
                            sub_agent_id, depth + 1, max_depth)

                        sub_agents.append({
                            "agent_id": str(sub_agent_id),
                            "name": sub_agent_info.get("display_name") or sub_agent_info.get("name",
                                                                                             f"Agent {sub_agent_id}"),
                            "tools": sub_tools,
                            "sub_agents": deeper_sub_agents,
                            "depth": depth + 1
                        })
                except Exception as e:
                    logger.warning(
                        f"Failed to get sub-agent {sub_agent_id} info: {str(e)}")
                    continue

            return sub_agents

        sub_agents = get_sub_agents_recursive(agent_id)

        return {
            "agent_id": str(agent_id),
            "name": agent_info.get("display_name") or agent_info.get("name", f"Agent {agent_id}"),
            "tools": tools,
            "sub_agents": sub_agents
        }

    except Exception as e:
        logger.exception(
            f"Failed to get agent call relationship for agent {agent_id}: {str(e)}")
        raise ValueError(f"Failed to get agent call relationship: {str(e)}")


async def export_agent_with_skills_impl(
    agent_id: int,
    authorization: str,
    version_no: int = 0,
) -> dict:
    """Export an agent, returning a ZIP if it has skill instances, otherwise a plain dict.

    The response is either:
      - A dict with {"_zip": True, "data": bytes, "filename": str} when the agent has skills
      - ExportAndImportDataFormat as a plain dict when the agent has no skills
    """
    user_id, tenant_id, _ = get_current_user_info(authorization)

    skill_zip_entries = collect_skill_zip_entries(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )

    if not skill_zip_entries:
        return await export_agent_dict_impl(
            agent_id, authorization, version_no=version_no
        )

    agent_json_str = await export_agent_impl(
        agent_id, authorization, version_no=version_no
    )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("agent.json", agent_json_str)
        for entry in skill_zip_entries:
            skill_zip_bytes = base64.b64decode(entry.skill_zip_base64)
            zf.writestr(f"skills/{entry.skill_name}.zip", skill_zip_bytes)

    zip_buffer.seek(0)
    zip_data = zip_buffer.read()

    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )
    agent_name = agent_info.get(
        "name", "anonymous") if agent_info else "anonymous"

    filename = f"{agent_name}.zip"

    return {
        "_zip": True,
        "data": zip_data,
        "filename": filename
    }


async def import_agent_with_skills_impl(
    agent_info: "ExportAndImportDataFormat",
    skills: List[SkillZipEntry],
    authorization: str,
    force_import: bool = False,
    skill_resolutions: Optional[List[SkillResolution]] = None,
    resolve_name_conflicts: bool = False,
):
    """Import an agent with skills bundled from a ZIP export.

    Duplicate skills require an explicit rename or use-existing resolution. New
    and renamed skills share the same ZIP creation path, while imported agent
    skill names are resolved to tenant-local skill IDs before creating instances.
    """
    user_id, tenant_id, _ = get_current_user_info(authorization)

    skill_name_to_zip_base64 = {
        entry.skill_name: entry.skill_zip_base64 for entry in skills}

    existing_skills = skill_db.list_skills(tenant_id)
    existing_skills_by_name = {
        skill.get("name"): skill
        for skill in existing_skills
        if skill.get("name")
    }
    existing_skill_names = set(existing_skills_by_name)

    skill_conflicts = build_skill_import_conflicts(
        list(skill_name_to_zip_base64),
        existing_skill_names,
    )
    duplicate_names = [conflict["skill_name"] for conflict in skill_conflicts]
    resolutions_by_name = {
        resolution.skill_name: resolution
        for resolution in skill_resolutions or []
    }

    conflict_by_name = {
        conflict["skill_name"]: conflict
        for conflict in skill_conflicts
    }
    has_unresolved_conflict = any(
        (
            (resolution := resolutions_by_name.get(skill_name)) is None
            or (
                resolution.action == "rename"
                and str(resolution.new_name or "").strip()
                != conflict_by_name[skill_name]["suggested_new_name"]
            )
        )
        for skill_name in duplicate_names
    )
    if has_unresolved_conflict:
        raise SkillDuplicateError(duplicate_names, skill_conflicts)

    skill_name_to_id: Dict[str, int] = {}
    skill_service = SkillService(tenant_id=tenant_id)

    for skill_name, zip_base64 in skill_name_to_zip_base64.items():
        resolution = (
            resolutions_by_name.get(skill_name)
            if skill_name in existing_skills_by_name
            else None
        )
        if skill_name in existing_skills_by_name and resolution and resolution.action == "use_existing":
            skill_name_to_id[skill_name] = existing_skills_by_name[skill_name]["skill_id"]
            continue

        target_name = (
            str(resolution.new_name).strip()
            if resolution and resolution.action == "rename"
            else skill_name
        )
        zip_bytes = base64.b64decode(zip_base64)
        result = skill_service.create_skill_from_zip_bytes(
            zip_bytes=zip_bytes,
            skill_name=target_name,
            source="导入",
            user_id=user_id,
            tenant_id=tenant_id,
            skip_duplicate_check=False,
        )
        skill_name_to_id[skill_name] = result.get("skill_id")

    agent_id_mapping = await import_agent_impl(
        agent_info, authorization, force_import,
        skill_name_to_id=skill_name_to_id,
        resolve_name_conflicts=resolve_name_conflicts,
    )

    for imported_agent in agent_info.agent_info.values():
        new_agent_id = agent_id_mapping.get(imported_agent.agent_id)
        if not new_agent_id:
            continue
        for skill_name in imported_agent.skill_names or []:
            resolved_skill_id = skill_name_to_id.get(skill_name)
            if resolved_skill_id is None:
                continue
            skill_db.create_or_update_skill_by_skill_info(
                skill_info=SkillInstanceInfoRequest(
                    skill_id=resolved_skill_id,
                    agent_id=new_agent_id,
                    enabled=True,
                    version_no=0
                ),
                tenant_id=tenant_id,
                user_id=user_id,
                version_no=0
            )

    return agent_id_mapping


def build_skill_import_conflicts(
    skill_names: List[str],
    existing_skill_names: set[str],
) -> List[Dict[str, str]]:
    """Build duplicate skill resolutions without creating any data."""
    ordered_skill_names = list(dict.fromkeys(skill_names))
    unavailable_names = existing_skill_names | set(ordered_skill_names)
    conflicts: List[Dict[str, str]] = []

    for skill_name in ordered_skill_names:
        if skill_name not in existing_skill_names:
            continue
        suggested_name = generate_available_copy_skill_name(
            skill_name,
            unavailable_names,
        )
        unavailable_names.add(suggested_name)
        conflicts.append({
            "skill_name": skill_name,
            "suggested_new_name": suggested_name,
        })

    return conflicts


def check_skill_conflicts_impl(
    skill_names: List[str],
    authorization: str,
) -> List[Dict[str, str]]:
    """Check agent import skill names against the current tenant."""
    _, tenant_id, _ = get_current_user_info(authorization)
    existing_skill_names = {
        skill.get("name")
        for skill in skill_db.list_skills(tenant_id)
        if skill.get("name")
    }
    return build_skill_import_conflicts(skill_names, existing_skill_names)


# =============================================================================
# Sandbox Policy Builder
# =============================================================================


def build_sandbox_policy(tenant_id: str, agent_type: str) -> Optional[dict]:
    """
    Assemble a sandbox policy dict from ``NEXENT_SANDBOX_*`` environment variables.

    This is the canonical factory used by the backend service layer to resolve
    ``SandboxConfig`` for every agent run.  It is called before constructing
    ``AgentRunInfo`` so that the resolved config flows into ``NexentAgent``.

    Resolution order:
      1. ``AgentConfig.sandbox_policy`` from the DB (takes precedence).
      2. ``NEXENT_SANDBOX_*`` environment variables (fallback when DB has no policy).

    Args:
        tenant_id: tenant identifier (reserved for future per-tenant overrides).
        agent_type: agent type string (reserved for future per-type overrides).

    Returns:
        A sandbox policy dict, or None when ``NEXENT_SANDBOX_DEFAULT_LEVEL=local``.
    """
    from consts.const import (
        NEXENT_SANDBOX_DEFAULT_LEVEL,
        NEXENT_SANDBOX_DEFAULT_SCOPE,
        NEXENT_SANDBOX_DOCKER_IMAGE,
        NEXENT_SANDBOX_MEMORY_LIMIT_MB,
        NEXENT_SANDBOX_CPU_QUOTA,
        NEXENT_SANDBOX_TIMEOUT_S,
        NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S,
        NEXENT_SANDBOX_NETWORK_DISABLED,
        NEXENT_SANDBOX_SHELL_POLICY,
        NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS,
    )

    level = NEXENT_SANDBOX_DEFAULT_LEVEL
    if level == "local":
        return None

    return {
        "level": level,
        "scope": NEXENT_SANDBOX_DEFAULT_SCOPE,
        "docker_image": NEXENT_SANDBOX_DOCKER_IMAGE,
        "memory_limit_mb": NEXENT_SANDBOX_MEMORY_LIMIT_MB,
        "cpu_quota": NEXENT_SANDBOX_CPU_QUOTA,
        "timeout_seconds": NEXENT_SANDBOX_TIMEOUT_S,
        "host_tool_timeout_seconds": NEXENT_SANDBOX_HOST_TOOL_TIMEOUT_S,
        "network_disabled": NEXENT_SANDBOX_NETWORK_DISABLED,
        "shell_policy": NEXENT_SANDBOX_SHELL_POLICY,
        "auto_sync_outputs": NEXENT_SANDBOX_AUTO_SYNC_OUTPUTS,
    }


def get_sandbox_minio_client() -> Optional[Any]:
    """
    Build and return a MinIO client for sandbox output sync.

    Returns None when MinIO is not configured (safe no-op).

    The caller is responsible for managing the client lifecycle — this function
    returns a fresh client on each call so the caller can call ``close()`` on it
    after the run finishes.
    """
    from consts.const import (
        NEXENT_SANDBOX_OUTPUT_BUCKET,
        MINIO_ENDPOINT,
        MINIO_ACCESS_KEY,
        MINIO_SECRET_KEY,
        MINIO_SECURE,
    )

    if not MINIO_ENDPOINT:
        return None

    try:
        from nexent.storage import MinIOStorageClient
    except ImportError:
        return None

    client = MinIOStorageClient(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY or "",
        secret_key=MINIO_SECRET_KEY or "",
        region=None,
        default_bucket=NEXENT_SANDBOX_OUTPUT_BUCKET,
        secure=MINIO_SECURE,
    )
    return client
