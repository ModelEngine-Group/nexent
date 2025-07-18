import os
import json
import logging

from fastapi import Header
from agents.create_agent_info import create_tool_config_list
from consts.model import AgentInfoRequest, ExportAndImportAgentInfo, ToolInstanceInfoRequest
from database.agent_db import create_agent, query_all_enabled_tool_instances, \
    query_or_create_main_agent_id, query_sub_agents, search_blank_sub_agent_by_main_agent_id, \
    search_tools_for_sub_agent, search_agent_info_by_agent_id, update_agent, delete_agent_by_id, query_all_tools, \
    create_or_update_tool_by_tool_info, check_tool_is_available

from utils.auth_utils import get_current_user_id
from typing import Optional


logger = logging.getLogger("agent_service")

def get_enable_tool_id_by_agent_id(agent_id: int, tenant_id: str, user_id: str = None):
    # now only admin can modify the tool, user_id is not used
    all_tool_instance = query_all_enabled_tool_instances(agent_id=agent_id, tenant_id=tenant_id, user_id=None)
    enable_tool_id_set = set()
    for tool_instance in all_tool_instance:
        if tool_instance["enabled"]:
            enable_tool_id_set.add(tool_instance["tool_id"])
    return list(enable_tool_id_set)

def get_enable_sub_agent_id_by_agent_id(agent_id: int, tenant_id: str, user_id: str):
    sub_agents = query_sub_agents(main_agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)
    sub_agents_list = []
    for sub_agent in sub_agents:
        if sub_agent["enabled"]:
            sub_agents_list.append(sub_agent["agent_id"])

    return sub_agents_list

def get_creating_sub_agent_id_service(main_agent_id: int, tenant_id: str, user_id: str = None) -> int:
    """
        first find the blank sub agent, if it exists, it means the agent was created before, but exited prematurely;
                                  if it does not exist, create a new one
    """
    sub_agent_id = search_blank_sub_agent_by_main_agent_id(main_agent_id, tenant_id)
    if sub_agent_id:
        return sub_agent_id
    else:
        return create_agent(agent_info={"enabled": False,
                                        "parent_agent_id": main_agent_id}, tenant_id=tenant_id, user_id=user_id)["agent_id"]


def query_sub_agents_api(main_agent_id: int, tenant_id: str = None, user_id: str = None):
    sub_agents = query_sub_agents(main_agent_id, tenant_id, user_id)

    for sub_agent in sub_agents:
        # search the tools used by each sub agent, here use the tools configured by admin, not use user_id
        tool_info = search_tools_for_sub_agent(agent_id=sub_agent["agent_id"], tenant_id=tenant_id, user_id=None)
        sub_agent["tools"] = tool_info

        tool_id_list = [tool["tool_id"] for tool in tool_info]
        if all(check_tool_is_available(tool_id_list)):
            sub_agent["is_available"] = True
        else:
            sub_agent["is_available"] = False
    return sub_agents


def list_main_agent_info_impl(authorization: Optional[str] = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)

    try:
        main_agent_id = query_or_create_main_agent_id(tenant_id=tenant_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Failed to get main agent id: {str(e)}")
        raise ValueError(f"Failed to get main agent id: {str(e)}")
        
    try:
        main_agent_info = search_agent_info_by_agent_id(agent_id=main_agent_id, tenant_id=tenant_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Failed to get main agent info: {str(e)}")
        raise ValueError(f"Failed to get main agent info: {str(e)}")

    try:
        sub_agent_list = query_sub_agents_api(main_agent_id, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get sub agent list: {str(e)}")
        raise ValueError(f"Failed to get sub agent list: {str(e)}")

    try:
        enable_tool_id_list = get_enable_tool_id_by_agent_id(main_agent_id, tenant_id, user_id)
        enable_agent_id_list = get_enable_sub_agent_id_by_agent_id(main_agent_id, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get enable tool id list: {str(e)}")
        raise ValueError(f"Failed to get enable tool id list: {str(e)}")

    return {
        "main_agent_id": main_agent_id,
        "sub_agent_list": sub_agent_list,
        "enable_tool_id_list": enable_tool_id_list,
        "enable_agent_id_list": enable_agent_id_list,
        "model_name": main_agent_info["model_name"],
        "max_steps": main_agent_info["max_steps"],
        "business_description": main_agent_info["business_description"],
        "prompt": main_agent_info["prompt"]
    }


def get_agent_info_impl(agent_id: int, authorization: str = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    
    try:    
        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get agent info: {str(e)}")
        raise ValueError(f"Failed to get agent info: {str(e)}")

    try:
        # now only admin can modify the agent, user_id is not used
        tool_info = search_tools_for_sub_agent(agent_id=agent_id, tenant_id=tenant_id, user_id=None)
        agent_info["tools"] = tool_info
    except Exception as e:
        logger.error(f"Failed to get agent tools: {str(e)}")
        agent_info["tools"] = []

    return agent_info

def get_creating_sub_agent_info_impl(agent_id: int, authorization: str = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    
    try:
        sub_agent_id = get_creating_sub_agent_id_service(agent_id, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get creating sub agent id: {str(e)}")
        raise ValueError(f"Failed to get creating sub agent id: {str(e)}")

    try:
        agent_info = search_agent_info_by_agent_id(agent_id=sub_agent_id, tenant_id=tenant_id, user_id=user_id)
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
            "prompt": agent_info["prompt"]}

def update_agent_info_impl(request: AgentInfoRequest, authorization: str = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)
    
    try:
        update_agent(request.agent_id, request, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to update agent info: {str(e)}")
        raise ValueError(f"Failed to update agent info: {str(e)}")

def delete_agent_impl(agent_id: int, authorization: str = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)

    try:
        delete_agent_by_id(agent_id, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to delete agent: {str(e)}")
        raise ValueError(f"Failed to delete agent: {str(e)}")

async def export_agent_impl(agent_id: int, authorization: str = Header(None)):
    user_id, tenant_id = get_current_user_id(authorization)

    tool_list = await create_tool_config_list(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)

    # Check if any tool is KnowledgeBaseSearchTool and set its metadata to empty dict
    for tool in tool_list:
        if tool.class_name == "KnowledgeBaseSearchTool":
            tool.metadata = {}
    
    agent_info_in_db = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)

    agent_info = ExportAndImportAgentInfo(name=agent_info_in_db["name"],
                                          description=agent_info_in_db["description"],
                                          business_description=agent_info_in_db["business_description"],
                                          model_name=agent_info_in_db["model_name"],
                                          max_steps=agent_info_in_db["max_steps"],
                                          provide_run_summary=agent_info_in_db["provide_run_summary"],
                                          prompt=agent_info_in_db["prompt"],
                                          enabled=agent_info_in_db["enabled"],
                                          tools=tool_list,
                                          managed_agents=[])

    agent_info_str = agent_info.model_dump_json()
    return agent_info_str

def import_agent_impl(parent_agent_id: int, agent_info: ExportAndImportAgentInfo, authorization: str = Header(None)):
    # check the validity and completeness of the tool parameters
    user_id, tenant_id = get_current_user_id(authorization)
    tool_list = []
    
    # query all tools in the current tenant
    tool_info = query_all_tools(tenant_id=tenant_id)
    db_all_tool_info_dict = {f"{tool['class_name']}&{tool['source']}": tool for tool in tool_info}

    for tool in agent_info.tools:
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
    if agent_info.model_name not in ["main_model", "sub_model"]:
        raise ValueError(f"Invalid model name: {agent_info.model_name}. model name must be 'main_model' or 'sub_model'.")
    if agent_info.max_steps <= 0 or agent_info.max_steps > 20:
        raise ValueError(f"Invalid max steps: {agent_info.max_steps}. max steps must be greater than 0 and less than 20.")
    if agent_info.name == "main":
        raise ValueError(f"Invalid agent name: {agent_info.name}. agent name cannot be 'main'.")
    # create a new agent
    user_id, tenant_id = get_current_user_id()
    new_agent = create_agent(agent_info={"name": agent_info.name,
                            "description": agent_info.description,
                            "business_description": agent_info.business_description,
                            "model_name": agent_info.model_name,
                            "max_steps": agent_info.max_steps,
                            "provide_run_summary": agent_info.provide_run_summary,
                            "prompt": agent_info.prompt,
                            "enabled": agent_info.enabled,
                            "parent_agent_id": parent_agent_id},
                  tenant_id=tenant_id,
                  user_id=user_id)
    new_agent_id = new_agent["agent_id"]
    # create tool_instance
    for tool in tool_list:
        tool.agent_id = new_agent_id
        create_or_update_tool_by_tool_info(tool_info=tool, tenant_id=tenant_id, user_id=user_id)

def search_sub_agents():
    user_id, tenant_id = get_current_user_id()
    logger.info(f"user_id: {user_id}, tenant_id: {tenant_id}")
    try:
        main_agent_id = query_or_create_main_agent_id(tenant_id=tenant_id, user_id=user_id)
    except Exception as e:
        logger.error(f"Failed to get main agent id: {str(e)}")
        raise ValueError(f"Failed to get main agent id: {str(e)}")

    try:
        sub_agent_list = query_sub_agents(main_agent_id, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get sub agent list: {str(e)}")
        raise ValueError(f"Failed to get sub agent list: {str(e)}")

    return main_agent_id, sub_agent_list

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

def import_default_agents_to_pg():
    try:
        main_agent_id, sub_agent_list = search_sub_agents()
        sub_agent_name_list = [sub_agent["name"] for sub_agent in sub_agent_list]

        try:
            default_agents = load_default_agents_json_file(default_agent_path = "backend/agents/default_agents/")
        except Exception as e:
            logger.error(f"Failed to load default agents: {str(e)}")
            raise ValueError(f"Failed to load default agents: {str(e)}")

        for agent in default_agents:
            if agent.name in sub_agent_name_list:
                continue
            else:
                try:
                    import_agent_impl(parent_agent_id=main_agent_id, agent_info=agent)
                except Exception as e:
                    logger.error(f"agent name: {agent.name}, error: {str(e)}")
                    raise ValueError(f"agent name: {agent.name}, error: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to import default agents: {str(e)}")
        raise ValueError(f"Failed to import default agents: {str(e)}")
