import re
import logging
from typing import List

from fastapi import HTTPException

from database.client import get_db_session, as_dict, filter_property
from database.db_models import ToolInfo, AgentInfo, UserAgent, ToolInstance
from utils.auth_utils import get_current_user_id

from sqlalchemy import or_
from consts.const import DEFAULT_USER_ID, DEFAULT_TENANT_ID


def search_agent_info_by_agent_id(agent_id: int, tenant_id: str, user_id: str = None):
    """
    Search agent info by agent_id
    """
    with get_db_session() as session:
        agent = session.query(AgentInfo).filter(
            AgentInfo.agent_id == agent_id,
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.delete_flag != 'Y'
        ).first()

        if not agent:
            raise ValueError("agent not found")

        agent_dict = as_dict(agent)
        if not user_id:
            return agent_dict

        user_agent_info = session.query(UserAgent).filter(
            UserAgent.agent_id == agent_id,
            UserAgent.tenant_id == tenant_id,
            UserAgent.user_id == user_id,
            UserAgent.delete_flag != 'Y'
        ).first()
        if user_agent_info:
            # update agent_dict with user_agent_info
            agent_dict.update(as_dict(user_agent_info))
            return agent_dict
        else:
            return agent_dict

def search_sub_agent_by_main_agent_id(main_agent_id: int, tenant_id: str = None):
    """
    Search sub agent by main agent id， if the sub agent is not created, then create a blank placeholder
    """
    with get_db_session() as session:
        sub_agent = session.query(AgentInfo).filter(
            AgentInfo.parent_agent_id == main_agent_id,
            AgentInfo.tenant_id == tenant_id,
            AgentInfo.delete_flag != 'Y',
            AgentInfo.name.is_(None)
        ).first()
        if sub_agent:
            return sub_agent.agent_id
        else:
            return None

def query_or_create_main_agent_id(tenant_id, user_id: str = None) -> int:
    """
    obtain the main_agent id, create a blank placeholder if it does not exist
    """
    with get_db_session() as session:
        query = session.query(AgentInfo).filter(AgentInfo.delete_flag != 'Y').filter(AgentInfo.parent_agent_id.is_(None))
        if tenant_id:
            query = query.filter(AgentInfo.tenant_id == tenant_id)
        main_agent = query.first()

        if main_agent is None:
            main_agent = create_agent(agent_info={"name": "main",
                                                  "description": "",
                                                  "enabled": True}, tenant_id=tenant_id, user_id=user_id)

            return main_agent["agent_id"]
        else:
            return main_agent.agent_id

def query_sub_agents(main_agent_id: int, tenant_id: str = None, user_id: str = None):
    """
    Query the TenantAgent list based on the optional tenant_id.
    Filter out records with delete_flag set to 'Y'.

    :param main_agent_id: Optional main agent ID for filtering
    :param tenant_id: Optional tenant ID for filtering
    :param user_id: Optional user ID for merging
    :return: List of TenantAgent objects that meet the criteria
    """
    with get_db_session() as session:
        query = session.query(AgentInfo).filter(AgentInfo.delete_flag != 'Y',
                                                AgentInfo.parent_agent_id == main_agent_id,
                                                AgentInfo.name.isnot(None),
                                                AgentInfo.description.isnot(None),
                                                AgentInfo.model_name.isnot(None))
        if tenant_id:
            query = query.filter(AgentInfo.tenant_id == tenant_id)
        
        # Order by create_time desc
        agents = query.order_by(AgentInfo.create_time.desc()).all()

        if not user_id:
            return [as_dict(agent) for agent in agents]

        user_agents = session.query(UserAgent).filter(
            UserAgent.tenant_id == tenant_id,
            UserAgent.user_id == user_id,
            UserAgent.delete_flag != 'Y'
        ).all()

        agent_dict = {str(agent.agent_id): agent for agent in agents}

        for user_agent in user_agents:
            agent_id = str(user_agent.agent_id)
            if agent_id in agent_dict:
                agent_info = agent_dict[agent_id]
                for key, value in user_agent.__dict__.items():
                    if key not in ['_sa_instance_state', 'agent_id'] and hasattr(agent_info, key):
                        setattr(agent_info, key, value)

        return [as_dict(agent) for agent in agents]

def create_agent(agent_info, tenant_id: str, user_id:str = None):
    """
    Create a new agent in the database.
    :param agent_info: Dictionary containing agent information
    :param tenant_id:
    :param user_id:
    :return: Created agent object
    """
    agent_info.update({"tenant_id": tenant_id,
                        "created_by": tenant_id,
                        "updated_by": tenant_id,
                        "model_name": "main_model",
                        "max_steps": 5})
    with get_db_session() as session:
        new_agent = AgentInfo(**filter_property(agent_info, AgentInfo))
        new_agent.delete_flag = 'N'
        session.add(new_agent)
        session.flush()

        if user_id:
            new_user_agent = UserAgent(**filter_property(agent_info | {"agent_id": new_agent.agent_id,
                                                                       "delete_flag": "N",
                                                                       "user_id": user_id,
                                                                       "created_by": user_id,
                                                                       "update_by": user_id}, UserAgent))
            session.add(new_user_agent)

        return as_dict(new_agent)

def update_agent(agent_id, agent_info, tenant_id, user_id=None):
    """
    Update an existing agent in the database.
    :param agent_id: ID of the agent to update
    :param agent_info: Dictionary containing updated agent information
    :param tenant_id: tenant ID
    :param user_id: Optional user ID
    :return: Updated agent object
    """
    with (get_db_session() as session):
        # update ag_user_agent_t
        if user_id:
            user_agent = session.query(UserAgent).filter(UserAgent.agent_id == agent_id,
                                                         UserAgent.tenant_id == tenant_id,
                                                         UserAgent.user_id == user_id
                                                        ).first()
            if not user_agent:
                raise ValueError("ag_user_agent_t Agent not found")
            for key, value in filter_property(agent_info.__dict__, UserAgent).items():
                if value is None:
                    continue
                setattr(user_agent, key, value)
            user_agent.updated_by = user_id

        # update ag_tenant_agent_t
        agent = session.query(AgentInfo).filter(AgentInfo.agent_id == agent_id,
                                                AgentInfo.tenant_id == tenant_id
                                                ).first()
        if not agent:
            raise ValueError("ag_tenant_agent_t Agent not found")

        for key, value in filter_property(agent_info.__dict__, AgentInfo).items():
            if value is None:
                continue
            setattr(agent, key, value)
        agent.updated_by = user_id

def create_tool(tool_info):
    """
    Create ToolInstance in the database based on tenant_id and agent_id, optional user_id.
    :param tool_info: Dictionary containing tool information

    :return: Created or updated ToolInstance object
    """
    with get_db_session() as session:
        # Create a new ToolInstance
        new_tool_instance = ToolInstance(**filter_property(tool_info, ToolInstance))
        session.add(new_tool_instance)

def create_or_update_tool_by_tool_info(tool_info, tenant_id: str, user_id: str = None):
    """
    Create or update a ToolInstance in the database based on tenant_id and agent_id, optional user_id.

    :param tool_info: Dictionary containing tool information
    :param tenant_id: Tenant ID for filtering, mandatory
    :param user_id: Optional user ID for filtering
    :return: Created or updated ToolInstance object
    """

    tool_info_dict = tool_info.__dict__ | {"tenant_id": tenant_id, "user_id": user_id}

    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInstance).filter(
            or_(ToolInstance.tenant_id == tenant_id, ToolInstance.tenant_id == DEFAULT_TENANT_ID),
            ToolInstance.agent_id == tool_info_dict['agent_id'],
            ToolInstance.delete_flag != 'Y',
            ToolInstance.tool_id == tool_info_dict['tool_id'])

        if user_id:
            query = query.filter(or_(ToolInstance.user_id == user_id, ToolInstance.user_id == DEFAULT_USER_ID))

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
        # Filter tools with two conditions:
        # 1. Tools that belong to the specific tenant (ToolInfo.tenant_id == tenant_id)
        # 2. Tools with default tenant_id value "tenant_id" which are shared across all tenants
        tools = session.query(ToolInfo).filter(
            ToolInfo.delete_flag != 'Y'
        ).filter(
            (ToolInfo.author == tenant_id) | (ToolInfo.author == DEFAULT_TENANT_ID)
        ).all()
        return [as_dict(tool) for tool in tools]

def query_tool_instances_by_id(agent_id: int, tool_id: int, tenant_id: str, user_id: str = None):
    """
    Query ToolInstance in the database based on tenant_id and agent_id, optional user_id.
    :param agent_id: Agent ID for filtering, mandatory
    :param tool_id: Tool ID for filtering, mandatory
    :param tenant_id: Tenant ID for filtering, mandatory
    :param user_id: Optional user ID for filtering
    :return: List of ToolInstance objects
    """
    with get_db_session() as session:
        query = session.query(ToolInstance).filter(
            or_(ToolInstance.tenant_id == tenant_id, ToolInstance.tenant_id == DEFAULT_TENANT_ID),
            ToolInstance.agent_id == agent_id,
            ToolInstance.tool_id == tool_id,
            ToolInstance.delete_flag != 'Y')
        if user_id:
            query = query.filter(or_(ToolInstance.user_id == user_id, ToolInstance.user_id == DEFAULT_USER_ID))
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
        tools = session.query(ToolInfo).filter(ToolInfo.tool_id.in_(tool_id_list)).filter(ToolInfo.delete_flag != 'Y').all()
        return [as_dict(tool) for tool in tools]

def query_all_enabled_tool_instances(tenant_id: str, user_id: str = None, agent_id: int = None):
    """
    Query ToolInstance in the database based on tenant_id and agent_id, optional user_id.
    :param tenant_id: Tenant ID for filtering, mandatory
    :param user_id: Optional user ID for filtering
    :param agent_id: Optional agent ID for filtering
    :return: List of ToolInstance objects
    """
    with get_db_session() as session:
        query = session.query(ToolInstance).filter(
            or_(ToolInstance.tenant_id == tenant_id, ToolInstance.tenant_id == DEFAULT_TENANT_ID)).filter(
            ToolInstance.delete_flag != 'Y').filter(ToolInstance.enabled)
        if user_id:
            query = query.filter(ToolInstance.user_id == user_id or ToolInstance.user_id == DEFAULT_USER_ID)
        if agent_id:
            query = query.filter(ToolInstance.agent_id == agent_id)
        tools = query.all()
        return [as_dict(tool) for tool in tools]

def delete_agent_by_id(agent_id, tenant_id: str = None, user_id: str = None):
    """
    Delete an agent in the database.
    :param agent_id: ID of the agent to delete
    :param tenant_id: Tenant ID for filtering, mandatory
    :param user_id: Optional user ID for filtering
    :return: None
    """
    with get_db_session() as session:
        session.query(AgentInfo).filter(AgentInfo.agent_id == agent_id,
                                        AgentInfo.tenant_id == tenant_id).update(
            {'delete_flag': 'Y', 'updated_by': user_id})
        session.query(ToolInstance).filter(ToolInstance.agent_id == agent_id,
                                           AgentInfo.tenant_id == tenant_id).update(
            {ToolInstance.delete_flag: 'Y', 'updated_by': user_id})
        if user_id:
            session.query(UserAgent).filter(UserAgent.agent_id == agent_id,
                                            UserAgent.user_id == user_id).update(
            {'delete_flag': 'Y', 'updated_by': user_id})

def update_tool_table_from_scan_tool_list(tenant_id: str, user_id: str, tool_list: List[ToolInfo]):
    """
    scan all tools and update the tool table in PG database, remove the duplicate tools
    """
    try:
        with get_db_session() as session:
            # get all existing tools (including complete information)
            existing_tools = session.query(ToolInfo).filter(ToolInfo.delete_flag != 'Y').all()
            existing_tool_dict = {f"{tool.name}&{tool.source}": tool for tool in existing_tools}
            # set all tools to unavailable
            for tool in existing_tools:
                tool.is_available = False

            for tool in tool_list:
                filtered_tool_data = filter_property(tool.__dict__, ToolInfo)

                # check if the tool name is valid
                is_available = True if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', tool.name) is not None else False

                if f"{tool.name}&{tool.source}" in existing_tool_dict:
                    # by tool name and source to update the existing tool
                    existing_tool = existing_tool_dict[f"{tool.name}&{tool.source}"]
                    for key, value in filtered_tool_data.items():
                        setattr(existing_tool, key, value)
                    existing_tool.updated_by = user_id
                    existing_tool.is_available = is_available
                else:
                    # create new tool
                    filtered_tool_data.update({"created_by": tenant_id, "updated_by": tenant_id, "author": tenant_id, "is_available": is_available})
                    new_tool = ToolInfo(**filtered_tool_data)
                    session.add(new_tool)
            session.flush()
        logging.info("Updated tool table in PG database")
    except Exception as e:
        logging.error(f"Updated tool table failed due to {e}")


def save_agent_prompt(agent_id: int, prompt: str, tenant_id: str = None, user_id: str = None):
    """
    Save or update the prompt for an agent in the database.
    :param agent_id: ID of the agent to update
    :param prompt: The prompt to save
    :param tenant_id: Optional tenant ID
    :param user_id: Optional user ID
    :return: Updated agent object
    """
    with get_db_session() as session:
        agent = session.query(AgentInfo).filter(
            AgentInfo.agent_id == agent_id,
            AgentInfo.delete_flag != 'Y'
        )
        if tenant_id:
            agent = agent.filter(AgentInfo.tenant_id == tenant_id)
        agent = agent.first()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent.prompt = prompt
        agent.updated_by = user_id
        session.flush()
        return as_dict(agent)

def add_tool_field(tool_info):
    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInfo).filter(ToolInfo.tool_id == tool_info["tool_id"])
        tool = query.first()

        # add tool params
        tool_params = tool.params
        for ele in tool_params:
            ele["default"] = tool_info["params"][ele["name"]]

        tool_info["params"] =tool_params
        tool_info["name"] = tool.name
        tool_info["description"] = tool.description
        tool_info["source"] = tool.source
        tool_info["class_name"] = tool.class_name
        tool_info["is_available"] = tool.is_available
        return tool_info

def search_tools_for_sub_agent(agent_id, tenant_id, user_id: str = None):
    with get_db_session() as session:
        # Query if there is an existing ToolInstance
        query = session.query(ToolInstance).filter(ToolInstance.agent_id == agent_id,
                                                   ToolInstance.tenant_id == tenant_id,
                                                   ToolInstance.delete_flag != 'Y',
                                                   ToolInstance.enabled == True)
        if user_id:
            query = query.filter(ToolInstance.user_id == user_id)

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
        tools = session.query(ToolInfo).filter(ToolInfo.tool_id.in_(tool_id_list), ToolInfo.delete_flag != 'Y').all()
        return [tool.is_available for tool in tools]
    
    