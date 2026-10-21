# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent listing, deletion, relationships and sandbox policy."""

import logging
from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from consts.agent_repository import (
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_SHARED,
)
from consts.const import (
    CAN_EDIT_ALL_USER_ROLES,
    PERMISSION_PRIVATE,
    TOOL_TYPE_MAPPING,
)
from consts.exceptions import (
    ForbiddenError,
)
from consts.model import (
    ToolSourceEnum,
)
from database import (
    skill_db,
)
from database.a2a_agent_db import (
    get_server_agent_ids,
)
from database.agent_db import (
    clear_agent_new_mark,
    delete_agent_by_id,
    delete_agent_relationship,
    is_system_agent,
    query_agent_info_by_ids,
    query_agent_list_candidates_by_tenant_id,
    query_all_agent_info_by_tenant_id,
    query_sub_agents_id_list,
    search_agent_id_by_agent_name,
    search_agent_info_by_agent_id,
)
from database.agent_repository_db import (
    list_agent_repository_by_agent_ids,
)
from database.agent_version_db import (
    batch_search_version_names,
    query_version_list,
)
from database.group_db import (
    query_group_ids_by_user,
)
from database.tag_management_db import (
    TagManagementDB,
)
from database.tool_db import (
    delete_tools_by_agent_id,
    search_tools_for_sub_agent,
)
from database.user_tenant_db import (
    get_user_tenant_by_user_id,
)
from management.services.agent.read import (
    apply_deleted_model_reason,
    apply_duplicate_name_availability_rules,
    check_agent_availability,
    project_agent_models,
)
from management.services.permission.asset_owner import (
    resolve_agent_list_permission,
)
from management.services.permission.identity.display import enrich_cas_usernames
from management.db.serialization import (
    convert_string_to_list,
)

logger = logging.getLogger(__name__)


async def delete_agent_impl(agent_id: int, tenant_id: str, user_id: str):
    """
    Delete an agent and all related data.

    Args:
        agent_id: Agent ID to delete
        tenant_id: Tenant ID
        user_id: User ID performing the deletion
    """
    if is_system_agent(agent_id, tenant_id) is True:
        raise ForbiddenError("System Agent is managed by the platform")

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
            from management.services.tag.library import TagManagementService

            TagManagementService.cleanup_resource_assignments(
                tenant_id, "agent", str(agent_id), user_id
            )
    except Exception as e:
        logger.error(f"Failed to delete agent: {str(e)}")
        raise ValueError(f"Failed to delete agent: {str(e)}")


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
        f"clear_agent_new_mark_impl called for agent_id={agent_id}, tenant_id={tenant_id}, user_id={user_id}, affected_rows={rowcount}"
    )
    return rowcount


def _publish_time_sort_value(value: Any) -> float:
    """Convert a stored publish time into a comparable epoch value."""
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _order_agents_by_publish_time(
    agents: List[Dict[str, Any]], tenant_ids: List[str]
) -> List[Dict[str, Any]]:
    """Order agents by their latest published version time, newest first.

    An agent that has never published a version has no publish time and is
    placed after every dated agent. The agent id breaks ties so pagination
    stays deterministic across pages.
    """
    publish_times: Dict[tuple, Any] = {}
    for scope_tenant_id in tenant_ids:
        versioned = [
            agent
            for agent in agents
            if agent.get("tenant_id") == scope_tenant_id
            and int(agent.get("current_version_no") or 0) > 0
        ]
        if not versioned:
            continue
        try:
            rows = batch_search_version_names(
                [int(agent["agent_id"]) for agent in versioned],
                scope_tenant_id,
                [int(agent["current_version_no"]) for agent in versioned],
            )
        except Exception as error:
            logger.warning("Failed to load agent publish times: %s", error)
            continue
        for row in rows:
            publish_times[
                (scope_tenant_id, int(row["agent_id"]), int(row["version_no"]))
            ] = row.get("create_time")

    dated: List[tuple] = []
    undated: List[Dict[str, Any]] = []
    for agent in agents:
        publish_time = publish_times.get(
            (
                agent.get("tenant_id"),
                int(agent["agent_id"]),
                int(agent.get("current_version_no") or 0),
            )
        )
        if publish_time is None:
            undated.append(agent)
        else:
            dated.append((publish_time, int(agent["agent_id"]), agent))

    dated.sort(
        key=lambda entry: (_publish_time_sort_value(entry[0]), entry[1]),
        reverse=True,
    )
    undated.sort(key=lambda agent: int(agent["agent_id"]), reverse=True)
    return [entry[2] for entry in dated] + undated


async def list_all_agent_info_impl(
    tenant_id: str, user_id: str, agent_ids: Optional[list[int]] = None
) -> list[dict]:
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

        agent_list = (
            query_agent_info_by_ids(tenant_id, agent_ids)
            if agent_ids is not None
            else query_all_agent_info_by_tenant_id(tenant_id=tenant_id)
        )

        # Get all agent IDs that are registered as A2A Server agents
        a2a_server_agent_ids = get_server_agent_ids(tenant_id)

        model_cache: Dict[int, Optional[dict]] = {}
        enriched_agents: list[dict] = []

        for agent in agent_list:
            if agent.get("agent_origin") == "SYSTEM" or agent.get("system_key"):
                continue
            if not agent["enabled"]:
                continue

            # Apply visibility filter for DEV/USER based on group overlap
            if not can_edit_all:
                agent_group_ids = set(convert_string_to_list(agent.get("group_ids")))
                ingroup_permission = agent.get("ingroup_permission")
                is_creator = str(agent.get("created_by")) == str(user_id)
                # Hide agent if: no group overlap OR (ingroup_permission is PRIVATE AND user is not creator)
                if not is_creator and (
                    len(user_group_ids.intersection(agent_group_ids)) == 0
                    or ingroup_permission == PERMISSION_PRIVATE
                ):
                    continue

            # Filter out deleted models (delete_flag='Y' in model_record_t)
            model_projection = project_agent_models(agent, tenant_id, model_cache)
            agent.update(model_projection.fields)
            agent["model_ids"] = model_projection.availability_model_ids

            # Use shared availability check function
            _, unavailable_reasons = check_agent_availability(
                agent_id=agent["agent_id"],
                tenant_id=tenant_id,
                agent_info=agent,
                model_cache=model_cache,
            )
            agent["model_ids"] = model_projection.fields["model_ids"]
            _, unavailable_reasons = apply_deleted_model_reason(
                not unavailable_reasons,
                unavailable_reasons,
                model_projection.deleted_model_ids,
            )

            # Preserve the raw data so we can adjust availability for duplicates
            enriched_agents.append(
                {
                    "raw_agent": agent,
                    "unavailable_reasons": unavailable_reasons,
                }
            )

        # Handle duplicate name/display_name: keep the earliest created agent available,
        # mark later ones as unavailable due to duplication.
        apply_duplicate_name_availability_rules(enriched_agents)

        agent_tag_values: Dict[str, List[str]] = {}
        agent_ids = [
            str(entry["raw_agent"]["agent_id"])
            for entry in enriched_agents
            if entry["raw_agent"].get("agent_id") is not None
        ]
        if agent_ids:
            try:
                agent_tag_values = (
                    TagManagementDB.list_resource_assignment_display_values_by_ids(
                        tenant_id, "agent", agent_ids
                    )
                )
            except Exception as error:
                logger.warning("Failed to load agent tags: %s", error)

        simple_agent_list: list[dict] = []
        enrich_cas_usernames(
            [entry["raw_agent"] for entry in enriched_agents],
            {"author_cas_username": "created_by"},
            email_fields={"author_cas_username": "author"},
        )
        for entry in enriched_agents:
            agent = entry["raw_agent"]
            unavailable_reasons = list(dict.fromkeys(entry["unavailable_reasons"]))

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

            simple_agent_list.append(
                {
                    "agent_id": agent["agent_id"],
                    "name": agent["name"] if agent["name"] else agent["display_name"],
                    "display_name": agent["display_name"]
                    if agent["display_name"]
                    else agent["name"],
                    "description": agent["description"],
                    "icon_url": agent.get("icon_url"),
                    "author": agent.get("author"),
                    **(
                        {"author_cas_username": agent["author_cas_username"]}
                        if agent.get("author_cas_username")
                        else {}
                    ),
                    "created_by": agent.get("created_by"),
                    "create_time": agent.get("create_time"),
                    "tags": agent_tag_values.get(str(agent["agent_id"]), []),
                    "model_ids": model_ids,
                    "model_names": model_names,
                    "model_name": first_model_name,
                    "is_available": len(unavailable_reasons) == 0,
                    "unavailable_reasons": unavailable_reasons,
                    "is_new": agent.get("is_new", False),
                    "is_main_agent": (
                        True
                        if agent.get("is_main_agent") is None
                        else bool(agent["is_main_agent"])
                    ),
                    "group_ids": convert_string_to_list(agent.get("group_ids")),
                    "permission": permission,
                    "is_published": agent.get("current_version_no") is not None,
                    "current_version_no": agent.get("current_version_no"),
                    "is_a2a_server": agent["agent_id"] in a2a_server_agent_ids,
                    "allow_chat_metadata": bool(
                        agent.get("allow_chat_metadata", False)
                    ),
                    "model_params_override": agent.get("model_params_override"),
                    "enable_protocol_repair_retry": agent.get(
                        "enable_protocol_repair_retry"
                    )
                    is True,
                }
            )

        return simple_agent_list
    except Exception as e:
        logger.error(f"Failed to query all agent info: {str(e)}")
        raise ValueError(f"Failed to query all agent info: {str(e)}")


async def list_agent_page_impl(
    tenant_id: str,
    user_id: str,
    caller_tenant_id: Optional[str] = None,
    permission: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    additional_tenant_id: Optional[str] = None,
    created_by: Optional[str] = None,
    created_by_not: Optional[str] = None,
    tag_predicates: Optional[list] = None,
    search_tag_predicates: Optional[list] = None,
    sort_by_update_time: bool = False,
    include_repository_info: bool = False,
) -> Dict[str, Any]:
    """List visible agents with server-side filters and pagination."""
    if created_by and created_by_not:
        raise ValueError("created_by and created_by_not cannot be used together")

    user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
    user_role = str(user_tenant_record.get("user_role") or "").upper()
    can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES
    user_group_ids: set[int] = set()
    if not can_edit_all:
        try:
            user_group_ids = set(query_group_ids_by_user(user_id) or [])
        except Exception as error:
            logger.warning("Failed to query user group ids for filtering: %s", error)

    agents: list[dict] = []
    duplicate_reasons: dict[tuple[str, int], list[str]] = {}
    tenant_ids = [tenant_id]
    if additional_tenant_id:
        tenant_ids.append(additional_tenant_id)
    for scope_tenant_id in tenant_ids:
        candidates = query_agent_list_candidates_by_tenant_id(
            scope_tenant_id, include_description=bool(search and search.strip())
        )
        visible: list[dict] = []
        for candidate in candidates:
            if candidate.get("enabled") is False:
                continue
            if not can_edit_all:
                agent_group_ids = set(
                    convert_string_to_list(candidate.get("group_ids"))
                )
                is_creator = str(candidate.get("created_by")) == str(user_id)
                if not is_creator and (
                    not user_group_ids.intersection(agent_group_ids)
                    or candidate.get("ingroup_permission") == PERMISSION_PRIVATE
                ):
                    continue
            candidate.setdefault("tenant_id", scope_tenant_id)
            if "permission" not in candidate:
                candidate["permission"] = resolve_agent_list_permission(
                    user_role=user_role,
                    agent=candidate,
                    user_id=user_id,
                    can_edit_all=can_edit_all,
                )
            visible.append(candidate)

        duplicate_entries = [
            {"raw_agent": candidate, "unavailable_reasons": []} for candidate in visible
        ]
        apply_duplicate_name_availability_rules(duplicate_entries)
        for entry in duplicate_entries:
            reasons = entry["unavailable_reasons"]
            if reasons:
                duplicate_reasons[
                    (scope_tenant_id, int(entry["raw_agent"]["agent_id"]))
                ] = reasons

        if tag and tag.strip():
            missing_tags = [
                candidate for candidate in visible if "tags" not in candidate
            ]
            try:
                values = (
                    TagManagementDB.list_resource_assignment_display_values_by_ids(
                        scope_tenant_id,
                        "agent",
                        [str(candidate["agent_id"]) for candidate in missing_tags],
                    )
                    if missing_tags
                    else {}
                )
            except Exception as error:
                logger.warning("Failed to load agent tags: %s", error)
                values = {}
            for candidate in missing_tags:
                candidate.setdefault("tags", values.get(str(candidate["agent_id"]), []))
        agents.extend(visible)

    agent_ids = [
        str(agent["agent_id"]) for agent in agents if agent.get("agent_id") is not None
    ]
    if tag_predicates:
        matched_ids = set(
            TagManagementDB.filter_authorized_resource_ids(
                tenant_id, "agent", agent_ids, tag_predicates
            )
        )
        agents = [
            agent for agent in agents if str(agent.get("agent_id")) in matched_ids
        ]
        agent_ids = [
            str(agent["agent_id"])
            for agent in agents
            if agent.get("agent_id") is not None
        ]

    search_tag_ids = set()
    if search_tag_predicates:
        search_tag_ids = set(
            TagManagementDB.filter_authorized_resource_ids(
                tenant_id, "agent", agent_ids, search_tag_predicates
            )
        )

    creator_count = sum(
        str(agent.get("created_by")) == str(user_id) for agent in agents
    )
    creator_counts = {
        "all": len(agents),
        "created": creator_count,
        "others": len(agents) - creator_count,
    }

    if created_by:
        agents = [
            agent for agent in agents if str(agent.get("created_by")) == created_by
        ]
    if created_by_not:
        agents = [
            agent for agent in agents if str(agent.get("created_by")) != created_by_not
        ]

    if permission:
        normalized_permission = permission.strip().upper()
        if normalized_permission not in {"EDIT", "READ_ONLY"}:
            raise ValueError("permission must be EDIT or READ_ONLY")
        agents = [
            agent
            for agent in agents
            if agent.get("permission") == normalized_permission
        ]

    if tag and tag.strip():
        normalized_tag = tag.strip().casefold()
        agents = [
            agent
            for agent in agents
            if any(
                str(agent_tag).casefold() == normalized_tag
                for agent_tag in agent.get("tags", [])
            )
        ]

    if search and search.strip():
        normalized_search = search.strip().casefold()
        agents = [
            agent
            for agent in agents
            if str(agent.get("agent_id")) in search_tag_ids
            or any(
                normalized_search in str(agent.get(field) or "").casefold()
                for field in ("name", "display_name", "description")
            )
        ]

    if sort_by_update_time:
        # Order the whole filtered set before slicing so the newest published
        # agents lead every page, not just the first one.
        agents = _order_agents_by_publish_time(agents, tenant_ids)

    total = len(agents)
    offset = (page - 1) * page_size
    paged_candidates = agents[offset : offset + page_size]
    enriched_by_key: dict[tuple[str, int], dict] = {}
    for scope_tenant_id in tenant_ids:
        page_ids = [
            int(agent["agent_id"])
            for agent in paged_candidates
            if agent["tenant_id"] == scope_tenant_id
        ]
        if not page_ids:
            continue
        enriched = await list_all_agent_info_impl(
            tenant_id=scope_tenant_id, user_id=user_id, agent_ids=page_ids
        )
        enriched_by_key.update(
            {
                (scope_tenant_id, int(agent["agent_id"])): agent
                for agent in enriched
                if int(agent["agent_id"]) in page_ids
            }
        )

    paged_scoped_agents: list[tuple[str, dict]] = []
    for candidate in paged_candidates:
        key = (candidate["tenant_id"], int(candidate["agent_id"]))
        enriched = enriched_by_key.get(key)
        if enriched is None:
            continue
        agent = dict(enriched)
        reasons = list(
            dict.fromkeys(
                [*agent.get("unavailable_reasons", []), *duplicate_reasons.get(key, [])]
            )
        )
        agent["unavailable_reasons"] = reasons
        agent["is_available"] = not reasons
        paged_scoped_agents.append((candidate["tenant_id"], agent))

    for scope_tenant_id in tenant_ids:
        versioned_agents = [
            agent
            for scope, agent in paged_scoped_agents
            if scope == scope_tenant_id and (agent.get("current_version_no") or 0) > 0
        ]
        if not versioned_agents:
            continue
        version_rows = batch_search_version_names(
            [int(agent["agent_id"]) for agent in versioned_agents],
            scope_tenant_id,
            [int(agent["current_version_no"]) for agent in versioned_agents],
        )
        version_by_key = {
            (row["agent_id"], row["version_no"]): row for row in version_rows
        }
        for agent in versioned_agents:
            version = version_by_key.get(
                (int(agent["agent_id"]), int(agent["current_version_no"])), {}
            )
            agent["version_label"] = version.get("version_name")
            agent["version_create_time"] = version.get("create_time")
    if include_repository_info:
        for scope_tenant_id in tenant_ids:
            scoped_agents = [
                agent
                for scope, agent in paged_scoped_agents
                if scope == scope_tenant_id
            ]
            if not scoped_agents:
                continue
            scoped_agent_ids = [int(agent["agent_id"]) for agent in scoped_agents]
            shared_records = list_agent_repository_by_agent_ids(
                scoped_agent_ids,
                statuses=(STATUS_SHARED,),
                publisher_tenant_id=scope_tenant_id,
            )
            publisher_records = []
            if scope_tenant_id == caller_tenant_id and user_role == "ADMIN":
                publisher_records = list_agent_repository_by_agent_ids(
                    scoped_agent_ids,
                    statuses=(STATUS_PENDING_REVIEW, STATUS_REJECTED, STATUS_SHARED),
                    publisher_tenant_id=scope_tenant_id,
                )
            elif scope_tenant_id == caller_tenant_id and user_role == "DEV":
                publisher_records = list_agent_repository_by_agent_ids(
                    scoped_agent_ids,
                    statuses=(STATUS_PENDING_REVIEW, STATUS_REJECTED, STATUS_SHARED),
                    publisher_tenant_id=scope_tenant_id,
                    publisher_user_id=user_id,
                )
            records_by_id = {
                int(record["agent_repository_id"]): (record, False)
                for record in shared_records
                if record["status"] == STATUS_SHARED
            }
            records_by_id.update(
                {
                    int(record["agent_repository_id"]): (record, True)
                    for record in publisher_records
                }
            )
            repository_by_agent_id: dict[int, list[dict]] = {}
            for record, is_publisher in records_by_id.values():
                created_at = record.get("create_time")
                repository_by_agent_id.setdefault(int(record["agent_id"]), []).append(
                    {
                        "agent_repository_id": record["agent_repository_id"],
                        "status": record["status"],
                        "version_no": record["version_no"],
                        "version_label": record.get("version_name"),
                        "create_time": (
                            created_at.isoformat()
                            if hasattr(created_at, "isoformat")
                            else created_at
                        ),
                        "content": record.get("content") if is_publisher else None,
                    }
                )
            for records in repository_by_agent_id.values():
                records.sort(
                    key=lambda item: (
                        str(item["create_time"] or ""),
                        int(item["agent_repository_id"]),
                    ),
                    reverse=True,
                )
            for agent in scoped_agents:
                agent["repository_info"] = repository_by_agent_id.get(
                    int(agent["agent_id"]), []
                )
    paged_agents = [agent for _, agent in paged_scoped_agents]
    return {
        "items": paged_agents,
        "creator_counts": creator_counts,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        },
    }


def get_agent_by_name_impl(agent_name: str, tenant_id: str) -> dict:
    """
    Resolve agent id and latest published version by agent name.

    Returns:
        dict with agent_id and latest_version_no (may be None)
    """
    if not agent_name:
        raise Exception("agent_name required")
    agent_id = search_agent_id_by_agent_name(agent_name, tenant_id)
    versions = query_version_list(agent_id, tenant_id)
    latest_version = versions[0]["version_no"] if versions else None
    return {"agent_id": agent_id, "latest_version_no": latest_version}


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

        tool_info = search_tools_for_sub_agent(agent_id=agent_id, tenant_id=tenant_id)
        tools = []
        for tool in tool_info:
            tool_name = (
                tool.get("name") or tool.get("tool_name") or str(tool["tool_id"])
            )
            tool_source = tool.get("source", ToolSourceEnum.LOCAL.value)
            tool_type = _normalize_tool_type(tool_source)

            tools.append(
                {"tool_id": tool["tool_id"], "name": tool_name, "type": tool_type}
            )

        def get_sub_agents_recursive(
            parent_agent_id: int, depth: int = 0, max_depth: int = 5
        ) -> list:
            if depth >= max_depth:
                return []

            sub_agent_id_list = query_sub_agents_id_list(
                main_agent_id=parent_agent_id, tenant_id=tenant_id
            )
            sub_agents = []

            for sub_agent_id in sub_agent_id_list:
                try:
                    sub_agent_info = search_agent_info_by_agent_id(
                        sub_agent_id, tenant_id
                    )
                    if sub_agent_info:
                        sub_tool_info = search_tools_for_sub_agent(
                            agent_id=sub_agent_id, tenant_id=tenant_id
                        )
                        sub_tools = []
                        for tool in sub_tool_info:
                            tool_name = (
                                tool.get("name")
                                or tool.get("tool_name")
                                or str(tool["tool_id"])
                            )
                            tool_source = tool.get("source", ToolSourceEnum.LOCAL.value)
                            tool_type = _normalize_tool_type(tool_source)

                            sub_tools.append(
                                {
                                    "tool_id": tool["tool_id"],
                                    "name": tool_name,
                                    "type": tool_type,
                                }
                            )

                        deeper_sub_agents = get_sub_agents_recursive(
                            sub_agent_id, depth + 1, max_depth
                        )

                        sub_agents.append(
                            {
                                "agent_id": str(sub_agent_id),
                                "name": sub_agent_info.get("display_name")
                                or sub_agent_info.get("name", f"Agent {sub_agent_id}"),
                                "tools": sub_tools,
                                "sub_agents": deeper_sub_agents,
                                "depth": depth + 1,
                            }
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to get sub-agent {sub_agent_id} info: {str(e)}"
                    )
                    continue

            return sub_agents

        sub_agents = get_sub_agents_recursive(agent_id)

        return {
            "agent_id": str(agent_id),
            "name": agent_info.get("display_name")
            or agent_info.get("name", f"Agent {agent_id}"),
            "tools": tools,
            "sub_agents": sub_agents,
        }

    except Exception as e:
        logger.exception(
            f"Failed to get agent call relationship for agent {agent_id}: {str(e)}"
        )
        raise ValueError(f"Failed to get agent call relationship: {str(e)}")
