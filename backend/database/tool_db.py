import re
import json
from typing import Dict, List
from database.agent_db import logger
from database.client import get_db_session, filter_property, as_dict
from database.db_models import ToolInstance, ToolInfo
from consts.model import ToolSourceEnum
from consts.tool_labels import BUILTIN_LABEL_MAP
from utils.tool_utils import get_local_tools_description_zh


def create_tool(tool_info, version_no: int = 0):
    """
    Create ToolInstance in the database.
    Default version_no=0 creates the draft version.

    Args:
        tool_info: Dictionary containing tool information
        version_no: Version number. Default 0 = draft/editing state

    Returns:
        Created ToolInstance object
    """
    tool_info_dict = tool_info.copy()
    tool_info_dict.setdefault("version_no", version_no)

    with get_db_session() as session:
        # Create a new ToolInstance
        new_tool_instance = ToolInstance(
            **filter_property(tool_info_dict, ToolInstance))
        session.add(new_tool_instance)


def create_or_update_tool_by_tool_info(
        tool_info,
        tenant_id: str,
        user_id: str,
        version_no: int = 0,
        db_session=None,
):
    """
    Create or update a ToolInstance in the database.
    Default version_no=0 operates on the draft version.

    Args:
        tool_info: Dictionary containing tool information
        tenant_id: Tenant ID for filtering, mandatory
        user_id: User ID for updating (will be set as the last updater)
        version_no: Version number to filter. Default 0 = draft/editing state
        db_session: Optional caller-owned SQLAlchemy Session for a shared transaction

    Returns:
        Created or updated ToolInstance object
    """
    tool_info_dict = tool_info.__dict__ | {
        "tenant_id": tenant_id, "user_id": user_id, "version_no": version_no}

    # Filter out null values from params to avoid saving nulls to database
    if 'params' in tool_info_dict and tool_info_dict['params'] is not None:
        tool_info_dict['params'] = {
            k: v for k, v in tool_info_dict['params'].items()
            if v is not None
        }

    session_context = get_db_session(db_session) if db_session is not None else get_db_session()
    with session_context as session:
        # Query if there is an existing ToolInstance
        # Note: Do not filter by user_id to avoid creating duplicate instances
        # for the same agent_id and tool_id when different users save
        query = session.query(ToolInstance).filter(
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.agent_id == tool_info_dict['agent_id'],
            ToolInstance.delete_flag != 'Y',
            ToolInstance.tool_id == tool_info_dict['tool_id'],
            ToolInstance.version_no == version_no
        )
        tool_instance = query.first()
        if tool_instance:
            # Update the existing ToolInstance
            for key, value in tool_info_dict.items():
                if hasattr(tool_instance, key):
                    setattr(tool_instance, key, value)
        else:
            # Create a new ToolInstance
            new_tool_instance = ToolInstance(
                **filter_property(tool_info_dict, ToolInstance))
            session.add(new_tool_instance)
            session.flush()  # Flush to get the ID
            tool_instance = new_tool_instance
        return as_dict(tool_instance)


def delete_tool_instances_by_ids(
    agent_id: int,
    tool_ids: List[int],
    tenant_id: str,
    user_id: str,
    version_no: int = 0,
    db_session=None,
) -> None:
    """Soft-delete selected ToolInstances within an optional shared transaction."""
    if not tool_ids:
        return
    session_context = get_db_session(db_session) if db_session is not None else get_db_session()
    with session_context as session:
        session.query(ToolInstance).filter(
            ToolInstance.agent_id == agent_id,
            ToolInstance.tool_id.in_(sorted(set(map(int, tool_ids)))),
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.version_no == version_no,
            ToolInstance.delete_flag != 'Y',
        ).update(
            {"delete_flag": "Y", "updated_by": user_id},
            synchronize_session=False,
        )


def query_all_tools(tenant_id: str):
    """
    Query ToolInfo in the database based on tenant_id and agent_id, optional user_id.
    Filter tools that belong to the specific tenant_id or have tenant_id as "tenant_id"
    :return: List of ToolInfo objects
    """
    with get_db_session() as session:
        query = session.query(ToolInfo).filter(
            ToolInfo.delete_flag != 'Y',
            ToolInfo.author == tenant_id)

        tools = query.all()
        return [as_dict(tool) for tool in tools]


def query_tool_instances_by_id(agent_id: int, tool_id: int, tenant_id: str, version_no: int = 0):
    """
    Query ToolInstance in the database.
    Default version_no=0 queries the draft version.

    Args:
        agent_id: Agent ID for filtering, mandatory
        tool_id: Tool ID for filtering, mandatory
        tenant_id: Tenant ID for filtering, mandatory
        version_no: Version number to filter. Default 0 = draft/editing state

    Returns:
        ToolInstance object or None
    """
    with get_db_session() as session:
        query = session.query(ToolInstance).filter(
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.agent_id == agent_id,
            ToolInstance.tool_id == tool_id,
            ToolInstance.version_no == version_no,
            ToolInstance.delete_flag != 'Y')
        tool_instance = query.first()
        if tool_instance:
            return as_dict(tool_instance)
        else:
            return None


def query_tools_by_ids(tool_id_list: List[int]):
    """
    Query ToolInfo in the database based on tool_id_list.
    :param tool_id_list: List of tool IDs
    :return: List of ToolInfo objects
    """
    with get_db_session() as session:
        tools = session.query(ToolInfo).filter(ToolInfo.tool_id.in_(
            tool_id_list)).filter(ToolInfo.delete_flag != 'Y').all()
        return [as_dict(tool) for tool in tools]


def query_tools_by_ids_for_tenant(tool_id_list: List[int], tenant_id: str):
    """Query active ToolInfo records by ID within one tenant boundary."""
    with get_db_session() as session:
        tools = session.query(ToolInfo).filter(
            ToolInfo.tool_id.in_(tool_id_list),
            ToolInfo.author == tenant_id,
            ToolInfo.delete_flag != 'Y',
        ).all()
        return [as_dict(tool) for tool in tools]


def query_tools_by_labels(tenant_id: str, labels: List[str]):
    """
    Query ToolInfo by labels using OR match (tool has ANY of the requested labels).

    Args:
        tenant_id: Tenant ID for filtering
        labels: List of label strings to filter by

    Returns:
        List of ToolInfo dicts matching any of the given labels
    """
    with get_db_session() as session:
        query = session.query(ToolInfo).filter(
            ToolInfo.delete_flag != 'Y',
            ToolInfo.author == tenant_id,
            ToolInfo.labels.op('?|')(labels)
        )
        tools = query.all()
        return [as_dict(tool) for tool in tools]


def update_tool_labels(tool_id: int, tenant_id: str, labels: List[str], user_id: str) -> bool:
    """
    Update labels for a specific tool. Replaces all existing labels.

    Args:
        tool_id: Tool ID to update
        tenant_id: Tenant ID for access control
        labels: New list of label strings
        user_id: User performing the update

    Returns:
        True if updated, False if tool not found or access denied
    """
    with get_db_session() as session:
        tool = session.query(ToolInfo).filter(
            ToolInfo.tool_id == tool_id,
            ToolInfo.author == tenant_id,
            ToolInfo.delete_flag != 'Y'
        ).first()
        if not tool:
            return False
        tool.labels = labels
        tool.updated_by = user_id
        session.flush()
        return True


def query_all_enabled_tool_instances(agent_id: int, tenant_id: str, version_no: int = 0):
    """
    Query enabled ToolInstance in the database.
    Default version_no=0 queries the draft version.

    Args:
        agent_id: Agent ID for filtering, mandatory
        tenant_id: Tenant ID for filtering, mandatory
        version_no: Version number to filter. Default 0 = draft/editing state

    Returns:
        List of ToolInstance objects
    """
    with get_db_session() as session:
        query = session.query(ToolInstance).filter(
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.version_no == version_no,
            ToolInstance.delete_flag != 'Y',
            ToolInstance.enabled,
            ToolInstance.agent_id == agent_id)
        tools = query.all()
        return [as_dict(tool) for tool in tools]


def query_tool_instances_by_agent_id(agent_id: int, tenant_id: str, version_no: int = 0):
    """
    Query all ToolInstance for an agent (regardless of enabled status).
    Default version_no=0 queries the draft version.

    Args:
        agent_id: Agent ID for filtering, mandatory
        tenant_id: Tenant ID for filtering, mandatory
        version_no: Version number to filter. Default 0 = draft/editing state

    Returns:
        List of ToolInstance objects
    """
    with get_db_session() as session:
        query = session.query(ToolInstance).filter(
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.agent_id == agent_id,
            ToolInstance.version_no == version_no,
            ToolInstance.delete_flag != 'Y')
        tools = query.all()
        return [as_dict(tool) for tool in tools]


def check_tool_list_initialized(tenant_id: str) -> bool:
    """
    Check if tool list has been initialized for the tenant.

    Args:
        tenant_id: Tenant ID to check

    Returns:
        True if tools have been initialized, False otherwise
    """
    with get_db_session() as session:
        # Check if any tools exist for this tenant
        count = session.query(ToolInfo).filter(
            ToolInfo.delete_flag != 'Y',
            ToolInfo.author == tenant_id
        ).count()
        return count > 0


def update_tool_table_from_scan_tool_list(tenant_id: str, user_id: str, tool_list: List[ToolInfo]):
    """
    scan all tools and update the tool table in PG database, remove the duplicate tools
    For MCP tools, use name&source&usage as unique key to allow same tool name from different MCP servers
    """
    with get_db_session() as session:
        # get all existing tools (including complete information)
        existing_tools = session.query(ToolInfo).filter(ToolInfo.delete_flag != 'Y',
                                                        ToolInfo.author == tenant_id).all()
        # Build existing_tool_dict with different keys for MCP vs non-MCP tools
        existing_tool_dict = {}
        for tool in existing_tools:
            if tool.source == ToolSourceEnum.MCP.value:
                # For MCP tools, use name + source + usage (MCP server name) as unique key
                key = f"{tool.name}&{tool.source}&{tool.usage or ''}"
            else:
                # For other tools, use name + source as unique key
                key = f"{tool.name}&{tool.source}"
            existing_tool_dict[key] = tool

        # set all tools to unavailable
        for tool in existing_tools:
            tool.is_available = False

        for tool in tool_list:
            filtered_tool_data = filter_property(tool.__dict__, ToolInfo)

            # check if the tool name is valid
            is_available = True if re.match(
                r'^[a-zA-Z_][a-zA-Z0-9_]*$', tool.name) is not None else False

            # Build key for lookup - same logic as existing_tool_dict
            if tool.source == ToolSourceEnum.MCP.value:
                key = f"{tool.name}&{tool.source}&{tool.usage or ''}"
            else:
                key = f"{tool.name}&{tool.source}"

            if key in existing_tool_dict:
                # by tool name and source to update the existing tool
                existing_tool = existing_tool_dict[key]
                for key, value in filtered_tool_data.items():
                    # Preserve user-set labels; only overwrite if new labels are explicitly provided
                    if key == "labels" and not value:
                        continue
                    setattr(existing_tool, key, value)
                existing_tool.updated_by = user_id
                existing_tool.is_available = is_available
            else:
                # create new tool — apply built-in labels for fresh installs
                builtin_labels = BUILTIN_LABEL_MAP.get(tool.name, [])
                if builtin_labels:
                    filtered_tool_data["labels"] = builtin_labels
                filtered_tool_data.update(
                    {"created_by": user_id, "updated_by": user_id, "author": tenant_id, "is_available": is_available})
                new_tool = ToolInfo(**filtered_tool_data)
                session.add(new_tool)
    logger.info("Updated tool table in PG database")


def upsert_discovered_mcp_tools(
    tenant_id: str, user_id: str, tool_list: List[ToolInfo]
) -> List[Dict]:
    """Upsert tools discovered from one MCP without changing other tools."""
    result = []
    with get_db_session() as session:
        for tool in tool_list:
            row = session.query(ToolInfo).filter(
                ToolInfo.name == tool.name,
                ToolInfo.source == ToolSourceEnum.MCP.value,
                ToolInfo.usage == tool.usage,
                ToolInfo.author == tenant_id,
                ToolInfo.delete_flag != 'Y',
            ).first()
            data = filter_property(tool.__dict__, ToolInfo)
            if row is None:
                data.update({
                    "author": tenant_id,
                    "created_by": user_id,
                    "updated_by": user_id,
                    "is_available": True,
                })
                row = ToolInfo(**data)
                session.add(row)
            else:
                for key, value in data.items():
                    setattr(row, key, value)
                row.updated_by = user_id
                row.is_available = True
            session.flush()
            result.append(as_dict(row))
    return result


def add_tool_field(tool_info):
    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInfo).filter(
            ToolInfo.tool_id == tool_info["tool_id"])
        tool = query.first()
        # add tool params
        tool_params = tool.params
        for ele in tool_params:
            param_name = ele["name"]
            instance_value = tool_info["params"].get(param_name)
            # Only set default if instance value is not None
            # This prevents null values from being saved to database and returned as defaults
            if instance_value is not None:
                ele["default"] = instance_value
        tool_dict = as_dict(tool)
        tool_dict["params"] = tool_params
        
        # Merge description_zh from SDK for local tools
        tool_name = tool_dict.get("name")
        if tool_dict.get("source") == "local":
            local_tool_descriptions = get_local_tools_description_zh()
            if tool_name in local_tool_descriptions:
                sdk_info = local_tool_descriptions[tool_name]
                tool_dict["description_zh"] = sdk_info.get("description_zh")
                
                # Merge params description_zh from SDK
                for param in tool_params:
                    if not param.get("description_zh"):
                        for sdk_param in sdk_info.get("params", []):
                            if sdk_param.get("name") == param.get("name"):
                                param["description_zh"] = sdk_param.get("description_zh")
                                break
                
                # Merge inputs description_zh from SDK
                inputs_str = tool_dict.get("inputs", "{}")
                try:
                    inputs = json.loads(inputs_str) if isinstance(inputs_str, str) else inputs_str
                    if isinstance(inputs, dict):
                        for key, value in inputs.items():
                            if isinstance(value, dict) and not value.get("description_zh"):
                                sdk_inputs = sdk_info.get("inputs", {})
                                if key in sdk_inputs:
                                    value["description_zh"] = sdk_inputs[key].get("description_zh")
                        tool_dict["inputs"] = json.dumps(inputs, ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    pass
        
        # combine tool_info and tool_dict
        tool_info.update(tool_dict)
        return tool_info


def search_tools_for_sub_agent(agent_id, tenant_id, version_no: int = 0):
    """
    Query enabled tools for a sub-agent.
    Default version_no=0 queries the draft version.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number to filter. Default 0 = draft/editing state

    Returns:
        List of tool instance dictionaries
    """
    with get_db_session() as session:
        # query if there is an existing ToolInstance
        query = session.query(ToolInstance).filter(
            ToolInstance.agent_id == agent_id,
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.version_no == version_no,
            ToolInstance.delete_flag != 'Y',
            ToolInstance.enabled
        )

        tool_instances = query.all()
        tools_list = []
        for tool_instance in tool_instances:
            tool_instance_dict = as_dict(tool_instance)
            new_tool_instance_dict = add_tool_field(tool_instance_dict)

            tools_list.append(new_tool_instance_dict)
        return tools_list


def check_tool_is_available(tool_id_list: List[int]):
    """
    Check if the tool is available
    """
    with get_db_session() as session:
        tools = session.query(ToolInfo).filter(ToolInfo.tool_id.in_(
            tool_id_list), ToolInfo.delete_flag != 'Y').all()
        return [tool.is_available for tool in tools]


def delete_tools_by_agent_id(agent_id, tenant_id, user_id, version_no: int = 0):
    """
    Delete all tool instances for an agent.
    Default version_no=0 deletes the draft version.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        user_id: User ID
        version_no: Version number to filter. Default 0 = draft/editing state
    """
    with get_db_session() as session:
        session.query(ToolInstance).filter(
            ToolInstance.agent_id == agent_id,
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.version_no == version_no
        ).update({
            ToolInstance.delete_flag: 'Y', 'updated_by': user_id
        })

def search_last_tool_instance_by_tool_id(tool_id: int, tenant_id: str, user_id: str, version_no: int = 0):
    """
    Query the latest ToolInstance by tool_id.
    Default version_no=0 queries the draft version.

    Args:
        tool_id: Tool ID
        tenant_id: Tenant ID
        user_id: User ID
        version_no: Version number to filter. Default 0 = draft/editing state

    Returns:
        ToolInstance object or None
    """
    with get_db_session() as session:
        query = session.query(ToolInstance).filter(
            ToolInstance.tool_id == tool_id,
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.user_id == user_id,
            ToolInstance.version_no == version_no,
            ToolInstance.delete_flag != 'Y'
        ).order_by(ToolInstance.update_time.desc())
        tool_instance = query.first()
        return as_dict(tool_instance) if tool_instance else None


# ---------------------------------------------------------------------------
# NL2AGENT builtin tool catalog seeding
# ---------------------------------------------------------------------------

# Catalog definitions for the 6 NL2AGENT builtin tools. These are inserted
# idempotently into ag_tool_info_t so the NL2AGENT default agent can reference
# them via enabled_tool_ids. The `class_name` is the stable key used by
# NexentAgent.create_builtin_tool to dispatch the tool.
NL2AGENT_BUILTIN_TOOL_DEFINITIONS = [
    {
        "name": "nl2agent_search_local_resources",
        "origin_name": "search_local_resources",
        "class_name": "NL2AgentSearchLocalResourcesTool",
        "description": "Search local tools (SDK + locally-installed MCP + LangChain) and local skills matching the user's intent. Returns a JSON object with `tools` and `skills` arrays, each containing up to 5 items with score (0-1) and reason.",
        "source": ToolSourceEnum.BUILTIN.value,
        "category": "nl2agent",
        "usage": "",
        "params": [],
        "inputs": '{"query": "string"}',
        "output_type": "string",
        "labels": ["nl2agent"],
    },
    {
        "name": "nl2agent_search_web_mcps",
        "origin_name": "search_web_mcps",
        "class_name": "NL2AgentSearchWebMcpsTool",
        "description": "Search web MCP marketplaces (official registry + community) for servers matching the user's intent. Returns a JSON array of up to 5 MCP server cards with score (0-1) and reason. Each card is rendered individually with an Install button.",
        "source": ToolSourceEnum.BUILTIN.value,
        "category": "nl2agent",
        "usage": "",
        "params": [],
        "inputs": '{"query": "string"}',
        "output_type": "string",
        "labels": ["nl2agent"],
    },
    {
        "name": "nl2agent_search_web_skills",
        "origin_name": "search_web_skills",
        "class_name": "NL2AgentSearchWebSkillsTool",
        "description": "Search the official/web skills marketplace for skills matching the user's intent. Returns a JSON array of up to 5 skill cards with score (0-1) and reason. Each card is rendered individually with an Install button.",
        "source": ToolSourceEnum.BUILTIN.value,
        "category": "nl2agent",
        "usage": "",
        "params": [],
        "inputs": '{"query": "string"}',
        "output_type": "string",
        "labels": ["nl2agent"],
    },
]


def seed_nl2agent_builtin_tools(tenant_id: str, user_id: str) -> List[int]:
    """Idempotently insert the 3 NL2AGENT builtin tool catalog rows for a tenant.

    Matches existing rows by (name, source). If a row exists, it is updated in
    place (preserving tool_id). If not, a new row is inserted. Returns the
    list of tool_ids for the 3 NL2AGENT builtin tools in definition order.

    Args:
        tenant_id: Tenant ID to scope the catalog rows.
        user_id: User ID for created_by/updated_by audit fields.

    Returns:
        List of 3 tool_ids corresponding to NL2AGENT_BUILTIN_TOOL_DEFINITIONS.
    """
    tool_ids: List[int] = []
    with get_db_session() as session:
        existing = session.query(ToolInfo).filter(
            ToolInfo.delete_flag != 'Y',
            ToolInfo.author == tenant_id,
            ToolInfo.source == ToolSourceEnum.BUILTIN.value,
            ToolInfo.category == "nl2agent",
        ).all()
        existing_by_name = {t.name: t for t in existing}

        for defn in NL2AGENT_BUILTIN_TOOL_DEFINITIONS:
            row = existing_by_name.get(defn["name"])
            if row is None:
                data = dict(defn)
                data.update({
                    "created_by": user_id,
                    "updated_by": user_id,
                    "author": tenant_id,
                    "is_available": True,
                })
                row = ToolInfo(**filter_property(data, ToolInfo))
                session.add(row)
                session.flush()
            else:
                for key, value in defn.items():
                    if hasattr(row, key):
                        setattr(row, key, value)
                row.updated_by = user_id
                row.is_available = True
            tool_ids.append(row.tool_id)

        logger.info(
            f"Seeded {len(tool_ids)} NL2AGENT builtin tools for tenant {tenant_id}"
        )
    return tool_ids
