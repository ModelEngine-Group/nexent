import re
import json
from typing import List
from database.agent_db import logger
from database.client import get_db_session, filter_property, as_dict
from database.db_models import ToolInstance, ToolInfo


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


def create_or_update_tool_by_tool_info(tool_info, tenant_id: str, user_id: str, version_no: int = 0):
    """
    Create or update a ToolInstance in the database.
    Default version_no=0 operates on the draft version.

    Args:
        tool_info: Dictionary containing tool information
        tenant_id: Tenant ID for filtering, mandatory
        user_id: Optional user ID for filtering
        version_no: Version number to filter. Default 0 = draft/editing state

    Returns:
        Created or updated ToolInstance object
    """
    tool_info_dict = tool_info.__dict__ | {
        "tenant_id": tenant_id, "user_id": user_id, "version_no": version_no}

    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInstance).filter(
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.user_id == user_id,
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
            create_tool(tool_info_dict, version_no)
        return tool_instance


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
    """
    with get_db_session() as session:
        # get all existing tools (including complete information)
        existing_tools = session.query(ToolInfo).filter(ToolInfo.delete_flag != 'Y',
                                                        ToolInfo.author == tenant_id).all()
        existing_tool_dict = {
            f"{tool.name}&{tool.source}": tool for tool in existing_tools}
        # set all tools to unavailable
        for tool in existing_tools:
            tool.is_available = False

        for tool in tool_list:
            filtered_tool_data = filter_property(tool.__dict__, ToolInfo)

            # check if the tool name is valid
            is_available = True if re.match(
                r'^[a-zA-Z_][a-zA-Z0-9_]*$', tool.name) is not None else False

            if f"{tool.name}&{tool.source}" in existing_tool_dict:
                # by tool name and source to update the existing tool
                existing_tool = existing_tool_dict[f"{tool.name}&{tool.source}"]
                for key, value in filtered_tool_data.items():
                    setattr(existing_tool, key, value)
                existing_tool.updated_by = user_id
                existing_tool.is_available = is_available
            else:
                # create new tool
                filtered_tool_data.update(
                    {"created_by": user_id, "updated_by": user_id, "author": tenant_id, "is_available": is_available})
                new_tool = ToolInfo(**filtered_tool_data)
                session.add(new_tool)
    logger.info("Updated tool table in PG database")


def add_tool_field(tool_info):
    from services.tool_configuration_service import get_local_tools_description_zh
    
    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInfo).filter(
            ToolInfo.tool_id == tool_info["tool_id"])
        tool = query.first()
        # add tool params
        tool_params = tool.params
        for ele in tool_params:
            param_name = ele["name"]
            ele["default"] = tool_info["params"].get(param_name)
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