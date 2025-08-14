import os
import json
import logging
from collections import deque

from fastapi import Header
from fastapi.responses import JSONResponse
from agents.create_agent_info import create_tool_config_list
from consts.model import AgentInfoRequest, ExportAndImportAgentInfo, ExportAndImportDataFormat, ToolInstanceInfoRequest
from database.agent_db import create_agent, query_all_enabled_tool_instances, \
     search_blank_sub_agent_by_main_agent_id, \
    search_tools_for_sub_agent, search_agent_info_by_agent_id, update_agent, delete_agent_by_id, query_all_tools, \
    create_or_update_tool_by_tool_info, check_tool_is_available, query_all_agent_info_by_tenant_id, \
    query_sub_agents_id_list, insert_related_agent, delete_all_related_agent

from utils.auth_utils import get_current_user_id
from utils.memory_utils import build_memory_config
from nexent.memory.memory_service import clear_memory


logger = logging.getLogger("agent_service")

def get_enable_tool_id_by_agent_id(agent_id: int, tenant_id: str, user_id: str = None):
    # now only admin can modify the tool, user_id is not used
    all_tool_instance = query_all_enabled_tool_instances(agent_id=agent_id, tenant_id=tenant_id, user_id=None)
    enable_tool_id_set = set()
    for tool_instance in all_tool_instance:
        if tool_instance["enabled"]:
            enable_tool_id_set.add(tool_instance["tool_id"])
    return list(enable_tool_id_set)

def get_creating_sub_agent_id_service(tenant_id: str, user_id: str = None) -> int:
    """
        first find the blank sub agent, if it exists, it means the agent was created before, but exited prematurely;
                                  if it does not exist, create a new one
    """
    sub_agent_id = search_blank_sub_agent_by_main_agent_id(tenant_id=tenant_id)
    if sub_agent_id:
        return sub_agent_id
    else:
        return create_agent(agent_info={"enabled": False}, tenant_id=tenant_id, user_id=user_id)["agent_id"]


def get_agent_info_impl(agent_id: int, tenant_id: str):
    try:    
        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Failed to get agent info: {str(e)}")
        raise ValueError(f"Failed to get agent info: {str(e)}")

    try:
        tool_info = search_tools_for_sub_agent(agent_id=agent_id, tenant_id=tenant_id)
        agent_info["tools"] = tool_info
    except Exception as e:
        logger.error(f"Failed to get agent tools: {str(e)}")
        agent_info["tools"] = []

    try:
        sub_agent_id_list = query_sub_agents_id_list(main_agent_id=agent_id, tenant_id=tenant_id)
        agent_info["sub_agent_id_list"] = sub_agent_id_list
    except Exception as e:
        logger.error(f"Failed to get sub agent id list: {str(e)}")
        agent_info["sub_agent_id_list"] = []

    return agent_info


def get_creating_sub_agent_info_impl(authorization: str = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    
    try:
        sub_agent_id = get_creating_sub_agent_id_service(tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get creating sub agent id: {str(e)}")
        raise ValueError(f"Failed to get creating sub agent id: {str(e)}")

    try:
        agent_info = search_agent_info_by_agent_id(agent_id=sub_agent_id, tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"Failed to get sub agent info: {str(e)}")
        raise ValueError(f"Failed to get sub agent info: {str(e)}")
    
    try:
        enable_tool_id_list = get_enable_tool_id_by_agent_id(sub_agent_id, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get sub agent enable tool id list: {str(e)}")
        raise ValueError(f"Failed to get sub agent enable tool id list: {str(e)}")
    
    return {"agent_id": sub_agent_id,
            "enable_tool_id_list": enable_tool_id_list,
            "model_name": agent_info["model_name"],
            "max_steps": agent_info["max_steps"],
            "business_description": agent_info["business_description"],
            "duty_prompt": agent_info.get("duty_prompt"),
            "constraint_prompt": agent_info.get("constraint_prompt"),
            "few_shots_prompt": agent_info.get("few_shots_prompt"),
            "sub_agent_id_list": query_sub_agents_id_list(main_agent_id=sub_agent_id, tenant_id=tenant_id)}

def update_agent_info_impl(request: AgentInfoRequest, authorization: str = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    
    try:
        update_agent(request.agent_id, request, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to update agent info: {str(e)}")
        raise ValueError(f"Failed to update agent info: {str(e)}")

async def delete_agent_impl(agent_id: int, authorization: str = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)

    try:
        delete_agent_by_id(agent_id, tenant_id, user_id)
        delete_all_related_agent(agent_id, tenant_id)
        
        # Clean up all memory data related to the agent
        await clear_agent_memory(agent_id, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to delete agent: {str(e)}")
        raise ValueError(f"Failed to delete agent: {str(e)}")


async def clear_agent_memory(agent_id: int, tenant_id: str, user_id: str):
    """
    Purge specified agent's memory data
    
    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        user_id: User ID
    """
    try:
        # Build memory configuration
        memory_config = build_memory_config(tenant_id)
        
        # Clean up agent-level memory
        try:
            agent_memory_result = await clear_memory(
                memory_level="agent",
                memory_config=memory_config,
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=str(agent_id)
            )
            logger.info(f"Cleared agent memory for agent {agent_id}: {agent_memory_result}")
        except Exception as e:
            logger.error(f"Failed to clear agent-level memory for agent {agent_id}: {str(e)}")
        
        # Clean up user_agent-level memory
        try:
            user_agent_memory_result = await clear_memory(
                memory_level="user_agent", 
                memory_config=memory_config,
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=str(agent_id)
            )
            logger.info(f"Cleared user_agent memory for agent {agent_id}: {user_agent_memory_result}")
        except Exception as e:
            logger.error(f"Failed to clear user_agent-level memory for agent {agent_id}: {str(e)}")
        
    except Exception as e:
        logger.error(f"Failed to build memory config for agent {agent_id}: {str(e)}")
        # Silently fail to maintain agent deletion process

async def export_agent_impl(agent_id: int, authorization: str = Header(None)) -> str:
    """
    Export the configuration information of the specified agent and all its sub-agents.

    Args:
        agent_id (int): The ID of the agent to export.
        authorization (str): User authentication information, obtained from the Header.

    Returns:
        str: A formatted JSON string containing the configuration information of the agent and all its sub-agents.

    Data Structure Example:
        model.py  ExportAndImportDataFormat

    Note:
        This function recursively finds all managed sub-agents and exports the detailed configuration of each agent (including tools, prompts, etc.) as a dictionary, and finally returns it as a formatted JSON string for frontend download and backup.
    """

    user_id, tenant_id = get_current_user_id(authorization)

    export_agent_dict = {}
    search_list = deque([agent_id])
    agent_id_set = set()

    while len(search_list):
        left_ele = search_list.popleft()
        if left_ele in agent_id_set:
            continue

        agent_id_set.add(left_ele)
        agent_info = await export_agent_by_agent_id(agent_id=left_ele, tenant_id=tenant_id, user_id=user_id)
        search_list.extend(agent_info.managed_agents)
        export_agent_dict[str(agent_info.agent_id)] = agent_info

    export_data = ExportAndImportDataFormat(agent_id=agent_id, agent_info=export_agent_dict)
    return export_data.model_dump()

async def export_agent_by_agent_id(agent_id: int, tenant_id: str, user_id: str)->ExportAndImportAgentInfo:
    """
    Export a single agent's information based on agent_id
    """
    agent_info = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id)
    agent_relation_in_db = query_sub_agents_id_list(main_agent_id=agent_id, tenant_id=tenant_id)
    tool_list = await create_tool_config_list(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)

    # Check if any tool is KnowledgeBaseSearchTool and set its metadata to empty dict
    for tool in tool_list:
        if tool.class_name == "KnowledgeBaseSearchTool":
            tool.metadata = {}
    
    agent_info = ExportAndImportAgentInfo(agent_id=agent_id,
                                          name=agent_info["name"],
                                          description=agent_info["description"],
                                          business_description=agent_info["business_description"],
                                          model_name=agent_info["model_name"],
                                          max_steps=agent_info["max_steps"],
                                          provide_run_summary=agent_info["provide_run_summary"],
                                          duty_prompt=agent_info.get("duty_prompt"),
                                          constraint_prompt=agent_info.get("constraint_prompt"),
                                          few_shots_prompt=agent_info.get("few_shots_prompt"),
                                          enabled=agent_info["enabled"],
                                          tools=tool_list,
                                          managed_agents=agent_relation_in_db)
    return agent_info


async def import_agent_impl(agent_info: ExportAndImportDataFormat, authorization: str = Header(None)):
    """
    Import agent using DFS
    """
    user_id, tenant_id = get_current_user_id(authorization)
    agent_id = agent_info.agent_id

    agent_stack = deque([agent_id])
    agent_id_set = set()
    mapping_agent_id = {}

    while len(agent_stack):
        need_import_agent_id = agent_stack.pop()
        if need_import_agent_id in agent_id_set:
            continue

        need_import_agent_info = agent_info.agent_info[str(need_import_agent_id)]
        managed_agents = need_import_agent_info.managed_agents

        if agent_id_set.issuperset(managed_agents):
            new_agent_id = await import_agent_by_agent_id(import_agent_info=agent_info.agent_info[str(need_import_agent_id)],
                                     tenant_id=tenant_id,
                                     user_id=user_id)
            mapping_agent_id[need_import_agent_id] = new_agent_id

            agent_id_set.add(need_import_agent_id)
            # Establish relationships with sub-agents
            for sub_agent_id in managed_agents:
                insert_related_agent(parent_agent_id=mapping_agent_id[need_import_agent_id],
                                     child_agent_id=mapping_agent_id[sub_agent_id],
                                     tenant_id=tenant_id)
        else:
            # Current agent still has sub-agents that haven't been imported
            agent_stack.append(need_import_agent_id)
            agent_stack.extend(managed_agents)


async def import_agent_by_agent_id(import_agent_info: ExportAndImportAgentInfo, tenant_id: str, user_id: str):
    tool_list = []

    # query all tools in the current tenant
    tool_info = query_all_tools(tenant_id=tenant_id)
    db_all_tool_info_dict = {f"{tool['class_name']}&{tool['source']}": tool for tool in tool_info}

    for tool in import_agent_info.tools:
        db_tool_info: dict | None = db_all_tool_info_dict.get(f"{tool.class_name}&{tool.source}", None)

        if db_tool_info is None:
            raise ValueError(f"Cannot find tool {tool.class_name} in {tool.source}.")

        db_tool_info_params = db_tool_info["params"]
        db_tool_info_params_name_set = set([param_info["name"] for param_info in db_tool_info_params])

        for tool_param_name in tool.params:
            if tool_param_name not in db_tool_info_params_name_set:
                raise ValueError(f"Parameter {tool_param_name} in tool {tool.class_name} from {tool.source} cannot be found.")

        tool_list.append(ToolInstanceInfoRequest(tool_id=db_tool_info['tool_id'],
                                                 agent_id=-1,
                                                 enabled=True,
                                                 params=tool.params))
    # check the validity of the agent parameters
    if import_agent_info.model_name not in ["main_model", "sub_model"]:
        raise ValueError(f"Invalid model name: {import_agent_info.model_name}. model name must be 'main_model' or 'sub_model'.")
    if import_agent_info.max_steps <= 0 or import_agent_info.max_steps > 20:
        raise ValueError(f"Invalid max steps: {import_agent_info.max_steps}. max steps must be greater than 0 and less than 20.")
    if not import_agent_info.name.isidentifier():
        raise ValueError(f"Invalid agent name: {import_agent_info.name}. agent name must be a valid python variable name.")
    # create a new agent
    new_agent = create_agent(agent_info={"name": import_agent_info.name,
                            "description": import_agent_info.description,
                            "business_description": import_agent_info.business_description,
                            "model_name": import_agent_info.model_name,
                            "max_steps": import_agent_info.max_steps,
                            "provide_run_summary": import_agent_info.provide_run_summary,
                            "duty_prompt": import_agent_info.duty_prompt,
                            "constraint_prompt": import_agent_info.constraint_prompt,
                            "few_shots_prompt": import_agent_info.few_shots_prompt,
                            "enabled": import_agent_info.enabled},
                  tenant_id=tenant_id,
                  user_id=user_id)
    new_agent_id = new_agent["agent_id"]
    # create tool_instance
    for tool in tool_list:
        tool.agent_id = new_agent_id
        create_or_update_tool_by_tool_info(tool_info=tool, tenant_id=tenant_id, user_id=user_id)
    return new_agent_id


def load_default_agents_json_file(default_agent_path):
    # load all json files in the folder
    all_json_files = []
    agent_file_list = os.listdir(default_agent_path)
    for agent_file in agent_file_list:
        if agent_file.endswith(".json"):
            with open(os.path.join(default_agent_path, agent_file), "r", encoding="utf-8") as f:
                agent_json = json.load(f)

            export_agent_info = ExportAndImportAgentInfo.model_validate(agent_json)
            all_json_files.append(export_agent_info)
    return all_json_files


def list_all_agent_info_impl(tenant_id: str, user_id: str) -> list[dict]:
    """
    list all agent info

    Args:
        tenant_id (str): tenant id
        user_id (str): user id

    Raises:
        ValueError: failed to query all agent info

    Returns:
        list: list of agent info
    """
    try:
        agent_list = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)
        
        simple_agent_list = []
        for agent in agent_list:
            # check agent is available
            if not agent["name"]:
                continue
            tool_info = search_tools_for_sub_agent(agent_id=agent["agent_id"], tenant_id=tenant_id)
            tool_id_list = [tool["tool_id"] for tool in tool_info]
            is_available = all(check_tool_is_available(tool_id_list))

            simple_agent_list.append({
                "agent_id": agent["agent_id"],
                "name": agent["name"] if agent["name"] else agent["display_name"],
                "display_name": agent["display_name"] if agent["display_name"] else agent["name"],
                "description": agent["description"],
                "is_available": is_available
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
            content={"message": "There is a circular call in the agent", "status": "error"}
        )
        if left_ele in agent_id_set:
            continue
        else:
            agent_id_set.add(left_ele)
        sub_ids = query_sub_agents_id_list(main_agent_id=left_ele, tenant_id=tenant_id)
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
            content={"message":"Failed to insert relation", "status": "error"}
        )