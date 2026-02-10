import logging
from typing import Optional, Tuple, List, Dict, Any
from sqlalchemy import update

from database.client import get_db_session, as_dict
from database.db_models import AgentInfo, ToolInstance, AgentRelation
from database.agent_version_db import (
    search_version_by_version_no,
    query_version_list,
    query_current_version_no,
    query_agent_snapshot,
    query_agent_draft,
    insert_version,
    update_version_status,
    update_agent_current_version,
    insert_agent_snapshot,
    insert_tool_snapshot,
    insert_relation_snapshot,
    delete_agent_snapshot,
    delete_tool_snapshot,
    delete_relation_snapshot,
    get_next_version_no,
    delete_version,
    SOURCE_TYPE_NORMAL,
    SOURCE_TYPE_ROLLBACK,
    STATUS_RELEASED,
    STATUS_DISABLED,
    STATUS_ARCHIVED,
)
from database.model_management_db import get_model_by_model_id
from utils.str_utils import convert_string_to_list

logger = logging.getLogger("agent_version_service")


def _remove_audit_fields_for_insert(data: dict) -> None:
    """
    Remove audit fields that should not be copied during snapshot
    """
    data.pop('create_time', None)
    data.pop('update_time', None)
    data.pop('created_by', None)
    data.pop('updated_by', None)
    data.pop('delete_flag', None)


def publish_version_impl(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_name: Optional[str] = None,
    release_note: Optional[str] = None,
    source_type: str = SOURCE_TYPE_NORMAL,
    source_version_no: Optional[int] = None,
) -> dict:
    """
    Publish a new version
    1. Copy draft data (version_no=0) to new version
    2. Create version metadata record
    3. Update current_version_no
    """
    # Get draft data
    agent_draft, tools_draft, relations_draft = query_agent_draft(agent_id, tenant_id)
    if not agent_draft:
        raise ValueError("Agent draft not found")

    # Calculate new version number
    new_version_no = get_next_version_no(agent_id, tenant_id)

    # Prepare agent snapshot data
    agent_snapshot = agent_draft.copy()
    agent_snapshot.pop('version_no', None)
    agent_snapshot.pop('current_version_no', None)
    agent_snapshot['version_no'] = new_version_no
    _remove_audit_fields_for_insert(agent_snapshot)

    # Insert agent snapshot
    insert_agent_snapshot(agent_snapshot)

    # Insert tool snapshots
    for tool in tools_draft:
        tool_snapshot = tool.copy()
        tool_snapshot.pop('version_no', None)
        tool_snapshot['version_no'] = new_version_no
        _remove_audit_fields_for_insert(tool_snapshot)
        insert_tool_snapshot(tool_snapshot)

    # Insert relation snapshots
    for rel in relations_draft:
        rel_snapshot = rel.copy()
        rel_snapshot.pop('version_no', None)
        rel_snapshot['version_no'] = new_version_no
        _remove_audit_fields_for_insert(rel_snapshot)
        insert_relation_snapshot(rel_snapshot)

    # Create version metadata
    version_data = {
        'tenant_id': tenant_id,
        'agent_id': agent_id,
        'version_no': new_version_no,
        'version_name': version_name,
        'release_note': release_note,
        'source_type': source_type,
        'source_version_no': source_version_no,
        'status': STATUS_RELEASED,
        'created_by': user_id,
    }
    version_id = insert_version(version_data)

    # Update current_version_no in draft
    update_agent_current_version(agent_id, tenant_id, new_version_no)

    return {
        "id": version_id,
        "version_no": new_version_no,
        "message": "Version published successfully",
    }


def get_version_list_impl(
    agent_id: int,
    tenant_id: str,
) -> dict:
    """
    Get version list for an agent
    """
    items = query_version_list(
        agent_id=agent_id,
        tenant_id=tenant_id,
    )
    total = len(items)
    return {
        "items": items,
        "total": total,
    }


def get_version_impl(
    agent_id: int,
    tenant_id: str,
    version_no: int,
) -> dict:
    """
    Get version
    """
    return search_version_by_version_no(agent_id, tenant_id, version_no)


def get_version_detail_impl(
    agent_id: int,
    tenant_id: str,
    version_no: int,
) -> dict:
    """
    Get version detail including snapshot data, structured like agent info.
    Returns agent info with tools, sub_agents, availability, etc.
    """
    result: Dict[str, Any] = {}

    # Get version metadata first
    version = search_version_by_version_no(agent_id, tenant_id, version_no)
    if not version:
        raise ValueError(f"Version {version_no} not found")

    # Add version metadata as a nested object
    result['version'] = {
        'version_name': version.get('version_name'),
        'version_status': version.get('status'),
        'release_note': version.get('release_note'),
        'source_type': version.get('source_type'),
        'source_version_no': version.get('source_version_no'),
    }

    # Get snapshot data
    agent_snapshot, tools_snapshot, relations_snapshot = query_agent_snapshot(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
    )

    if not agent_snapshot:
        raise ValueError(f"Agent snapshot for version {version_no} not found")

    # Copy all fields from agent_snapshot (excluding current_version_no as it has no meaning for version snapshot)
    for key, value in agent_snapshot.items():
        if key != 'current_version_no':
            result[key] = value

    # Add tools
    result['tools'] = tools_snapshot

    # Extract sub_agent_id_list from relations
    result['sub_agent_id_list'] = [r['selected_agent_id'] for r in relations_snapshot]

    # Get model name from model_id
    if result.get('model_id') is not None and result['model_id'] != 0:
        model_info = get_model_by_model_id(result['model_id'])
        result['model_name'] = model_info.get('display_name', None) if model_info else None
    else:
        result['model_name'] = None

    # Get business logic model name
    if result.get('business_logic_model_id') is not None and result['business_logic_model_id'] != 0:
        business_logic_model_info = get_model_by_model_id(result['business_logic_model_id'])
        result['business_logic_model_name'] = business_logic_model_info.get('display_name', None) if business_logic_model_info else None
    else:
        result['business_logic_model_name'] = None

    # Convert group_ids string to list
    if result.get('group_ids') is not None:
        result['group_ids'] = convert_string_to_list(result.get('group_ids', ''))
    else:
        result['group_ids'] = []

    # Build tool instances list for availability check
    tool_instances_for_check = []
    for tool in tools_snapshot:
        tool_instance = {
            'id': tool.get('tool_id'),
            'enabled': tool.get('enabled', True),
            'tool_id': tool.get('tool_id'),
        }
        tool_instances_for_check.append(tool_instance)

    # Check agent availability
    is_available, unavailable_reasons = _check_version_snapshot_availability(
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_info=result,
        tool_instances=tool_instances_for_check,
    )
    result['is_available'] = is_available
    result['unavailable_reasons'] = unavailable_reasons

    return result


def _check_version_snapshot_availability(
    agent_id: int,
    tenant_id: str,
    agent_info: dict,
    tool_instances: List[dict],
) -> Tuple[bool, List[str]]:
    """
    Check if a version snapshot agent is available.
    Simplified version of check_agent_availability for snapshots.
    """
    unavailable_reasons: List[str] = []

    # Check if agent info exists
    if not agent_info:
        return False, ["agent_not_found"]

    # Check model availability
    model_id = agent_info.get('model_id')
    if model_id is None or model_id == 0:
        unavailable_reasons.append("model_not_configured")

    # Check tools availability
    if not tool_instances:
        unavailable_reasons.append("no_tools")
    else:
        # Check if at least one tool is enabled
        has_enabled_tool = any(t.get('enabled', True) for t in tool_instances)
        if not has_enabled_tool:
            unavailable_reasons.append("all_tools_disabled")

    return len(unavailable_reasons) == 0, unavailable_reasons


def rollback_version_impl(
    agent_id: int,
    tenant_id: str,
    target_version_no: int,
) -> dict:
    """
    Rollback to a specific version by updating current_version_no only.
    This does NOT create a new version - it simply points the draft to an existing version.
    The actual version creation happens when user clicks "publish".

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        target_version_no: The version number to rollback to

    Returns:
        Success message with target version info
    """
    # Verify the target version exists
    version = search_version_by_version_no(agent_id, tenant_id, target_version_no)
    if not version:
        raise ValueError(f"Version {target_version_no} not found")

    # Update current_version_no in draft to point to target version
    rows_affected = update_agent_current_version(
        agent_id=agent_id,
        tenant_id=tenant_id,
        current_version_no=target_version_no,
    )

    if rows_affected == 0:
        raise ValueError("Agent draft not found")

    return {
        "message": f"Successfully rolled back to version {target_version_no}",
        "version_no": target_version_no,
        "version_name": version.get("version_name"),
    }


def update_version_status_impl(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int,
    status: str,
) -> dict:
    """
    Update version status (DISABLED / ARCHIVED)
    """
    valid_statuses = [STATUS_DISABLED, STATUS_ARCHIVED]
    if status not in valid_statuses:
        raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")

    rows_affected = update_version_status(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
        status=status,
        updated_by=user_id,
    )

    if rows_affected == 0:
        raise ValueError(f"Version {version_no} not found")

    return {"message": "Status updated successfully"}


def delete_version_impl(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int,
) -> dict:
    """
    Soft delete a version by setting delete_flag='Y'
    Also soft deletes all related snapshot data (agent, tools, relations) for this version
    """
    # Check if version exists
    version = search_version_by_version_no(agent_id, tenant_id, version_no)
    if not version:
        raise ValueError(f"Version {version_no} not found")

    # Prevent deleting the current published version
    current_version_no = query_current_version_no(agent_id, tenant_id)
    if current_version_no == version_no:
        raise ValueError("Cannot delete the current published version")

    # Prevent deleting draft version (version_no=0)
    if version_no == 0:
        raise ValueError("Cannot delete draft version")

    # Soft delete version metadata
    rows_affected = delete_version(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
        deleted_by=user_id,
    )

    if rows_affected == 0:
        raise ValueError(f"Version {version_no} not found")

    # Soft delete all related snapshot data for this version
    # 1. Delete agent snapshot
    delete_agent_snapshot(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
        deleted_by=user_id,
    )

    # 2. Delete tool snapshots
    delete_tool_snapshot(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
        deleted_by=user_id,
    )

    # 3. Delete relation snapshots
    delete_relation_snapshot(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
        deleted_by=user_id,
    )

    logger.info(f"Successfully deleted version {version_no} and all related snapshots for agent_id={agent_id}, tenant_id={tenant_id}")

    return {"message": f"Version {version_no} deleted successfully"}


def get_current_version_impl(
    agent_id: int,
    tenant_id: str,
) -> dict:
    """
    Get current published version
    """
    current_version_no = query_current_version_no(agent_id, tenant_id)
    if current_version_no is None:
        raise ValueError("No published version")

    version = search_version_by_version_no(agent_id, tenant_id, current_version_no)
    if not version:
        raise ValueError(f"Version {current_version_no} not found")

    return {
        "version_no": current_version_no,
        "version_name": version.get('version_name'),
        "status": version.get('status'),
        "source_type": version.get('source_type'),
        "source_version_no": version.get('source_version_no'),
        "release_note": version.get('release_note'),
        "created_by": version.get('created_by'),
        "create_time": version.get('create_time'),
    }


def compare_versions_impl(
    agent_id: int,
    tenant_id: str,
    version_no_a: int,
    version_no_b: int,
) -> dict:
    """
    Compare two versions and return their differences.
    Returns detailed comparison data for both versions.
    Handles version 0 as draft data.
    """
    # Get version A detail (handles version 0 as draft)
    version_a = _get_version_detail_or_draft(agent_id, tenant_id, version_no_a)
    # Get version B detail (handles version 0 as draft)
    version_b = _get_version_detail_or_draft(agent_id, tenant_id, version_no_b)

    # Calculate differences
    differences = []

    # Compare name
    if version_a.get('name') != version_b.get('name'):
        differences.append({
            'field': 'name',
            'label': 'Name',
            'value_a': version_a.get('name'),
            'value_b': version_b.get('name'),
        })

    # Compare model_name
    if version_a.get('model_name') != version_b.get('model_name'):
        differences.append({
            'field': 'model_name',
            'label': 'Model',
            'value_a': version_a.get('model_name'),
            'value_b': version_b.get('model_name'),
        })

    # Compare max_steps
    if version_a.get('max_steps') != version_b.get('max_steps'):
        differences.append({
            'field': 'max_steps',
            'label': 'Max Steps',
            'value_a': version_a.get('max_steps'),
            'value_b': version_b.get('max_steps'),
        })

    # Compare description
    if version_a.get('description') != version_b.get('description'):
        differences.append({
            'field': 'description',
            'label': 'Description',
            'value_a': version_a.get('description'),
            'value_b': version_b.get('description'),
        })

    # Compare duty_prompt
    if version_a.get('duty_prompt') != version_b.get('duty_prompt'):
        differences.append({
            'field': 'duty_prompt',
            'label': 'Duty Prompt',
            'value_a': version_a.get('duty_prompt'),
            'value_b': version_b.get('duty_prompt'),
        })

    # Compare tools count
    tools_a_count = len(version_a.get('tools', []))
    tools_b_count = len(version_b.get('tools', []))
    if tools_a_count != tools_b_count:
        differences.append({
            'field': 'tools_count',
            'label': 'Tools Count',
            'value_a': tools_a_count,
            'value_b': tools_b_count,
        })

    # Compare sub_agents count
    sub_agents_a_count = len(version_a.get('sub_agent_id_list', []))
    sub_agents_b_count = len(version_b.get('sub_agent_id_list', []))
    if sub_agents_a_count != sub_agents_b_count:
        differences.append({
            'field': 'sub_agents_count',
            'label': 'Sub Agents Count',
            'value_a': sub_agents_a_count,
            'value_b': sub_agents_b_count,
        })

    return {
        'version_a': version_a,
        'version_b': version_b,
        'differences': differences,
    }


def _get_version_detail_or_draft(
    agent_id: int,
    tenant_id: str,
    version_no: int,
) -> dict:
    """
    Get version detail for published versions, or draft data for version 0.
    Returns structured agent info similar to get_version_detail_impl.
    """
    result: Dict[str, Any] = {}

    if version_no == 0:
        # Get draft data for version 0
        agent_draft, tools_draft, relations_draft = query_agent_draft(agent_id, tenant_id)
        if not agent_draft:
            raise ValueError(f"Draft version not found")

        # Copy draft data
        for key, value in agent_draft.items():
            if key != 'current_version_no':
                result[key] = value

        result['tools'] = tools_draft
        result['sub_agent_id_list'] = [r['selected_agent_id'] for r in relations_draft]
        result['version'] = {
            'version_name': 'Draft',
            'version_status': 'DRAFT',
            'release_note': '',
            'source_type': 'DRAFT',
            'source_version_no': 0,
        }
    else:
        # Get published version detail
        result = get_version_detail_impl(agent_id, tenant_id, version_no)

    # Get model name from model_id
    if result.get('model_id') is not None and result['model_id'] != 0:
        model_info = get_model_by_model_id(result['model_id'])
        result['model_name'] = model_info.get('display_name', None) if model_info else None
    else:
        result['model_name'] = None

    # Get business logic model name
    if result.get('business_logic_model_id') is not None and result['business_logic_model_id'] != 0:
        business_logic_model_info = get_model_by_model_id(result['business_logic_model_id'])
        result['business_logic_model_name'] = business_logic_model_info.get('display_name', None) if business_logic_model_info else None
    else:
        result['business_logic_model_name'] = None

    # Convert group_ids string to list (only if it's not already a list)
    group_ids = result.get('group_ids')
    if group_ids is not None:
        # If already a list, keep it as is; otherwise convert from string
        if isinstance(group_ids, list):
            result['group_ids'] = group_ids
        else:
            result['group_ids'] = convert_string_to_list(str(group_ids))
    else:
        result['group_ids'] = []

    return result


async def list_published_agents_impl(
    tenant_id: str,
    user_id: str,
) -> list[dict]:
    """
    List all published agents with their current published version information.
    1. Query all agents with version_no=0 (draft versions)
    2. For each agent with current_version_no > 0, get the published version snapshot
    3. Return the list of published agents

    Args:
        tenant_id (str): Tenant ID
        user_id (str): User ID (for permission calculation and filtering)

    Returns:
        list[dict]: List of published agent info
    """
    try:
        from database.agent_db import (
            query_all_agent_info_by_tenant_id,
        )
        from services.agent_service import (
            CAN_EDIT_ALL_USER_ROLES,
            get_user_tenant_by_user_id,
            query_group_ids_by_user,
            PERMISSION_EDIT,
            PERMISSION_READ,
            get_model_by_model_id,
            check_agent_availability,
            _apply_duplicate_name_availability_rules,
        )
        from database.agent_version_db import query_agent_snapshot

        # Get user role for permission check
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()
        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

        # Get user's group IDs for filtering
        user_group_ids: set[int] = set()
        if not can_edit_all:
            try:
                user_group_ids = set(query_group_ids_by_user(user_id) or [])
            except Exception as e:
                logger.warning(
                    f"Failed to query user group ids for filtering: user_id={user_id}, err={str(e)}"
                )
                user_group_ids = set()

        # Get all draft agents (version_no=0)
        agent_list = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)

        model_cache: Dict[int, Optional[dict]] = {}
        enriched_agents: list[dict] = []

        for agent in agent_list:
            # Filter out disabled agents
            if not agent.get("enabled"):
                continue

            # Apply visibility filter for DEV/USER based on group overlap
            if not can_edit_all:
                agent_group_ids = set(convert_string_to_list(agent.get("group_ids")))
                if len(user_group_ids.intersection(agent_group_ids)) == 0:
                    continue

            agent_id = agent.get("agent_id")
            current_version_no = agent.get("current_version_no")

            # Only include agents that have a published version (current_version_no > 0)
            if not current_version_no or current_version_no <= 0:
                continue

            # Get the published version snapshot
            agent_snapshot, tools_snapshot, relations_snapshot = query_agent_snapshot(
                agent_id=agent_id,
                tenant_id=tenant_id,
                version_no=current_version_no,
            )

            if not agent_snapshot:
                logger.warning(
                    f"Published version snapshot not found for agent_id={agent_id}, version_no={current_version_no}"
                )
                continue

            # Build the agent info from snapshot
            agent_info: Dict[str, Any] = {}

            # Copy all fields from snapshot (excluding current_version_no as it's not meaningful for version)
            for key, value in agent_snapshot.items():
                if key != 'current_version_no':
                    agent_info[key] = value

            # Add tools
            agent_info['tools'] = tools_snapshot

            # Extract sub_agent_id_list from relations
            agent_info['sub_agent_id_list'] = [r['selected_agent_id'] for r in relations_snapshot]

            # Add published version info
            agent_info['published_version_no'] = current_version_no

            # Check agent availability using the shared function
            _, unavailable_reasons = check_agent_availability(
                agent_id=agent_id,
                tenant_id=tenant_id,
                agent_info=agent_info,
                model_cache=model_cache
            )

            # Preserve the raw data so we can adjust availability for duplicates
            enriched_agents.append({
                "raw_agent": agent_info,
                "unavailable_reasons": unavailable_reasons,
            })

        # Handle duplicate name/display_name: keep the earliest created agent available,
        # mark later ones as unavailable due to duplication.
        _apply_duplicate_name_availability_rules(enriched_agents)

        # Build the final simple agent list
        simple_agent_list: list[dict] = []
        for entry in enriched_agents:
            agent = entry["raw_agent"]
            unavailable_reasons = list(dict.fromkeys(entry["unavailable_reasons"]))

            model_id = agent.get("model_id")
            model_info = None
            if model_id is not None:
                if model_id not in model_cache:
                    model_cache[model_id] = get_model_by_model_id(model_id, tenant_id)
                model_info = model_cache.get(model_id)

            permission = PERMISSION_EDIT if can_edit_all or str(agent.get("created_by")) == str(user_id) else PERMISSION_READ

            simple_agent_list.append({
                "agent_id": agent.get("agent_id"),
                "name": agent.get("name") if agent.get("name") else agent.get("display_name"),
                "display_name": agent.get("display_name") if agent.get("display_name") else agent.get("name"),
                "description": agent.get("description"),
                "author": agent.get("author"),
                "model_id": model_id,
                "model_name": model_info.get("model_name") if model_info is not None else agent.get("model_name"),
                "model_display_name": model_info.get("display_name") if model_info is not None else None,
                "is_available": len(unavailable_reasons) == 0,
                "unavailable_reasons": unavailable_reasons,
                "is_new": agent.get("is_new", False),
                "group_ids": agent.get("group_ids", []),
                "permission": permission,
                "published_version_no": agent.get("published_version_no"),
            })

        return simple_agent_list

    except Exception as e:
        logger.error(f"Failed to list published agents: {str(e)}")
        raise ValueError(f"Failed to list published agents: {str(e)}")
