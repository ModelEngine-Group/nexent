import re
from typing import List

from database.agent_db import logger
from database.client import get_db_session, filter_property, as_dict
from database.db_models import ToolInstance, ToolInfo


def create_tool(tool_info):
    """
    Create ToolInstance in the database based on tenant_id and agent_id, optional user_id.
    :param tool_info: Dictionary containing tool information

    :return: Created or updated ToolInstance object
    """
    with get_db_session() as session:
        # Create a new ToolInstance
        new_tool_instance = ToolInstance(
            **filter_property(tool_info, ToolInstance))
        session.add(new_tool_instance)


def create_or_update_tool_by_tool_info(tool_info, tenant_id: str, user_id: str):
    """
    Create or update a ToolInstance in the database based on tenant_id and agent_id, optional user_id.

    :param tool_info: Dictionary containing tool information
    :param tenant_id: Tenant ID for filtering, mandatory
    :param user_id: Optional user ID for filtering
    :return: Created or updated ToolInstance object
    """

    tool_info_dict = tool_info.__dict__ | {
        "tenant_id": tenant_id, "user_id": user_id}

    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInstance).filter(
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.user_id == user_id,
            ToolInstance.agent_id == tool_info_dict['agent_id'],
            ToolInstance.delete_flag != 'Y',
            ToolInstance.tool_id == tool_info_dict['tool_id']
        )

        tool_instance = query.first()

        if tool_instance:
            # Update the existing ToolInstance
            for key, value in tool_info_dict.items():
                if hasattr(tool_instance, key):
                    setattr(tool_instance, key, value)
        else:
            create_tool(tool_info_dict)

        session.flush()
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


def query_tool_instances_by_id(agent_id: int, tool_id: int, tenant_id: str):
    """
    Query ToolInstance in the database based on tenant_id and agent_id, optional user_id.
    :param agent_id: Agent ID for filtering, mandatory
    :param tool_id: Tool ID for filtering, mandatory
    :param tenant_id: Tenant ID for filtering, mandatory
    :return: List of ToolInstance objects
    """
    with get_db_session() as session:
        query = session.query(ToolInstance).filter(
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.agent_id == agent_id,
            ToolInstance.tool_id == tool_id,
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


def query_all_enabled_tool_instances(agent_id: int, tenant_id: str):
    """
    Query ToolInstance in the database based on tenant_id and agent_id, optional user_id.
    :param tenant_id: Tenant ID for filtering, mandatory
    :param agent_id: Optional agent ID for filtering
    :return: List of ToolInstance objects
    """
    with get_db_session() as session:
        query = session.query(ToolInstance).filter(
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.delete_flag != 'Y',
            ToolInstance.enabled,
            ToolInstance.agent_id == agent_id)
        tools = query.all()
        return [as_dict(tool) for tool in tools]


def update_tool_table_from_scan_tool_list(tenant_id: str, user_id: str, tool_list: List[ToolInfo]):
    """
    scan all tools and update the tool table in PG database, remove the duplicate tools
    """
    try:
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
            session.flush()
        logger.info("Updated tool table in PG database")
    except Exception as e:
        logger.error(f"Updated tool table failed due to {e}")


def add_tool_field(tool_info):
    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInfo).filter(
            ToolInfo.tool_id == tool_info["tool_id"])
        tool = query.first()

        # add tool params
        tool_params = tool.params
        for ele in tool_params:
            ele["default"] = tool_info["params"][ele["name"]]

        tool_dict = as_dict(tool)
        tool_dict["params"] = tool_params

        # 合并tool_info和tool_dict
        tool_info.update(tool_dict)
        return tool_info


def search_tools_for_sub_agent(agent_id, tenant_id):
    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInstance).filter(
            ToolInstance.agent_id == agent_id,
            ToolInstance.tenant_id == tenant_id,
            ToolInstance.delete_flag != 'Y',
            ToolInstance.enabled == True
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


def delete_tools_by_agent_id(agent_id, tenant_id, user_id):
    with get_db_session() as session:
        session.query(ToolInstance).filter(
            ToolInstance.agent_id == agent_id,
            ToolInstance.tenant_id == tenant_id
        ).update({
            ToolInstance.delete_flag: 'Y', 'updated_by': user_id
        })
        session.commit()
