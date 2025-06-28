import threading

import json
import yaml
import logging
from typing import Optional
from fastapi import Header
from urllib.parse import urljoin
from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_model import AgentRunInfo, ModelConfig, AgentConfig, ToolConfig
from utils.auth_utils import get_current_user_id

from database.agent_db import search_agent_info_by_agent_id, search_tools_for_sub_agent, query_sub_agents, \
    query_or_create_main_agent_id
from services.elasticsearch_service import ElasticSearchService
from services.tenant_config_service import get_selected_knowledge_list
from utils.config_utils import config_manager, tenant_config_manager, get_model_name_from_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("build agent")

async def create_model_config_list(tenant_id):
     main_model_config = tenant_config_manager.get_model_config(key="LLM_ID", tenant_id=tenant_id)
     sub_model_config = tenant_config_manager.get_model_config(key="LLM_SECONDARY_ID", tenant_id=tenant_id)

     return [ModelConfig(cite_name="main_model",
                         api_key=main_model_config.get("api_key", ""),
                         model_name=get_model_name_from_config(main_model_config) if main_model_config.get("model_name") else "",
                         url=main_model_config.get("base_url", "")),
            ModelConfig(cite_name="sub_model",
                        api_key=sub_model_config.get("api_key", ""),
                        model_name=get_model_name_from_config(sub_model_config) if sub_model_config.get("model_name") else "",
                        url=sub_model_config.get("base_url", ""))]


async def create_agent_config(agent_id, tenant_id, user_id, language: str = 'zh'):
    agent_info = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)

    # create sub agent
    sub_agents_info = query_sub_agents(agent_id, tenant_id, user_id)
    managed_agents = []
    for sub_agent_info in sub_agents_info:
        if not sub_agent_info.get("enabled"):
            continue
        sub_agent_config = await create_agent_config(
            agent_id=sub_agent_info["agent_id"],
            tenant_id=tenant_id,
            user_id=user_id,
            language=language)
        managed_agents.append(sub_agent_config)

    tool_list = await create_tool_config_list(agent_id, tenant_id, user_id)
    system_prompt = agent_info.get("prompt")

    # special logic
    try:
        for tool in tool_list:
            if "KnowledgeBaseSearchTool" == tool.class_name:
                knowledge_base_summary = "\n\n### 本地知识库信息 ###\n" if language == 'zh' else "\n\n### Local Knowledge Base Information ###\n"

                knowledge_info_list = get_selected_knowledge_list(tenant_id=tenant_id, user_id=user_id)
                for knowledge_info in knowledge_info_list:
                    knowledge_name = knowledge_info.get("index_name")
                    message = ElasticSearchService().get_summary(index_name=knowledge_name)
                    knowledge_base_summary += f"{knowledge_name}:{message['summary']}\n"
                system_prompt += knowledge_base_summary
    except Exception as e:
        logger.error(f"add knowledge base summary to system prompt failed, error: {e}")

    agent_config = AgentConfig(
        name="" if agent_info["name"] is None else agent_info["name"],
        description="" if agent_info["description"] is None else agent_info["description"],
        prompt_templates=await prepare_prompt_templates(is_manager=len(managed_agents)>0, system_prompt=system_prompt, language=language),
        tools=tool_list,
        max_steps=agent_info.get("max_steps", 10),
        model_name=agent_info.get("model_name"),
        provide_run_summary=agent_info.get("provide_run_summary", False),
        managed_agents=managed_agents
    )
    return agent_config


async def create_tool_config_list(agent_id, tenant_id, user_id):
    # create tool
    tool_config_list = []
    tools_list = search_tools_for_sub_agent(agent_id, tenant_id, user_id)
    for tool in tools_list:
        param_dict = {}
        for param in tool.get("params", []):
            param_dict[param["name"]] = param.get("default")
        tool_config = ToolConfig(
            class_name=tool.get("class_name"),
            params=param_dict,
            source=tool.get("source")
        )

        # special logic for knowledge base search tool
        if tool_config.class_name == "KnowledgeBaseSearchTool":
            knowledge_info_list = get_selected_knowledge_list(tenant_id=tenant_id, user_id=user_id)
            index_names = [knowledge_info.get("index_name") for knowledge_info in knowledge_info_list]
            tool_config.metadata = {"index_names": index_names}
        tool_config_list.append(tool_config)
    return tool_config_list


async def prepare_prompt_templates(is_manager: bool, system_prompt: str, language: str = 'zh'):
    """
    Prepare prompt templates, support multiple languages
    
    Args:
        is_manager: Whether it is a manager mode
        system_prompt: System prompt content
        language: Language code ('zh' or 'en')
        
    Returns:
        dict: Prompt template configuration
    """
    def get_template_path(is_manager: bool, language: str) -> str:
        if language == 'en':
            return "backend/prompts/manager_system_prompt_template_en.yaml" if is_manager else "backend/prompts/managed_system_prompt_template_en.yaml"
        else:  # Default to Chinese
            return "backend/prompts/manager_system_prompt_template.yaml" if is_manager else "backend/prompts/managed_system_prompt_template.yaml"

    prompt_template_path = get_template_path(is_manager, language)
    with open(prompt_template_path, "r", encoding="utf-8") as f:
        prompt_templates = yaml.safe_load(f)
    prompt_templates["system_prompt"] = system_prompt
    return prompt_templates


async def join_minio_file_description_to_query(minio_files, query):
    final_query = query
    if minio_files and isinstance(minio_files, list):
        file_descriptions = []
        for file in minio_files:
            if isinstance(file, dict) and "description" in file and file["description"]:
                file_descriptions.append(file["description"])

        if file_descriptions:
            final_query = "User provided some reference files:\n"
            final_query += "\n".join(file_descriptions) + "\n\n"
            final_query += f"User wants to answer questions based on the above information: {query}"
    return final_query


async def create_agent_run_info(agent_id, minio_files, query, history, authorization, language: str = 'zh'):
    user_id, tenant_id = get_current_user_id(authorization)
    if not agent_id:
        agent_id = query_or_create_main_agent_id(tenant_id=tenant_id, user_id=user_id)
    final_query = await join_minio_file_description_to_query(minio_files=minio_files, query=query)

    model_list = await create_model_config_list(tenant_id)
    agent_run_info = AgentRunInfo(
        query=final_query,
        model_config_list= model_list,
        observer=MessageObserver(),
        agent_config=await create_agent_config(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id, language=language),
        mcp_host=urljoin(config_manager.get_config("NEXENT_MCP_SERVER"), "sse"),
        history=history,
        stop_event=threading.Event()
    )
    return agent_run_info
