import threading
import yaml
import logging
from urllib.parse import urljoin
from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_model import AgentRunInfo, ModelConfig, AgentConfig, ToolConfig

from services.remote_mcp_service import get_remote_mcp_server_list
from utils.auth_utils import get_current_user_id

from database.agent_db import search_agent_info_by_agent_id, search_tools_for_sub_agent, query_sub_agents, \
    query_or_create_main_agent_id
from services.elasticsearch_service import ElasticSearchService, elastic_core, get_embedding_model
from services.tenant_config_service import get_selected_knowledge_list
from utils.prompt_template_utils import get_prompt_template_path
from utils.config_utils import config_manager, tenant_config_manager, get_model_name_from_config
from smolagents.agents import populate_template
from smolagents.utils import BASE_BUILTIN_MODULES

logger = logging.getLogger("create_agent_info")

async def create_model_config_list(tenant_id):
    main_model_config = tenant_config_manager.get_model_config(key="LLM_ID", tenant_id=tenant_id)
    sub_model_config = tenant_config_manager.get_model_config(key="LLM_SECONDARY_ID", tenant_id=tenant_id)

    return [ModelConfig(cite_name="main_model",
                        api_key=main_model_config.get("api_key", ""),
                        model_name=get_model_name_from_config(main_model_config) if main_model_config.get(
                            "model_name") else "",
                        url=main_model_config.get("base_url", ""),
                        is_deep_thinking=main_model_config.get("is_deep_thinking", False)),
            ModelConfig(cite_name="sub_model",
                        api_key=sub_model_config.get("api_key", ""),
                        model_name=get_model_name_from_config(sub_model_config) if sub_model_config.get(
                            "model_name") else "",
                        url=sub_model_config.get("base_url", ""),
                        is_deep_thinking=main_model_config.get("is_deep_thinking", False))]


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
    
    # Build system prompt: prioritize segmented fields, fallback to original prompt field if not available
    duty_prompt = agent_info.get("duty_prompt", "")
    constraint_prompt = agent_info.get("constraint_prompt", "")
    few_shots_prompt = agent_info.get("few_shots_prompt", "")
    
    # Get template path
    prompt_template_path = get_prompt_template_path(is_manager=len(managed_agents) > 0, language=language)
    with open(prompt_template_path, "r", encoding="utf-8") as file:
        prompt_template = yaml.safe_load(file)

    # Get app information
    default_app_description = 'Nexent 是一个开源智能体SDK和平台' if language == 'zh' else 'Nexent is an open-source agent SDK and platform'
    app_name = tenant_config_manager.get_app_config('APP_NAME', tenant_id=tenant_id) or "Nexent"
    app_description = tenant_config_manager.get_app_config('APP_DESCRIPTION', tenant_id=tenant_id) or default_app_description

    # Assemble system_prompt
    system_prompt = populate_template(
        prompt_template["system_prompt"],
        variables={
            "duty": duty_prompt,
            "constraint": constraint_prompt,
            "few_shots": few_shots_prompt,
            "tools": {tool.name: tool for tool in tool_list},
            "managed_agents": {agent.name: agent for agent in managed_agents},
            "authorized_imports": str(BASE_BUILTIN_MODULES),
            "APP_NAME": app_name,
            "APP_DESCRIPTION": app_description
        },
    ) if (duty_prompt or constraint_prompt or few_shots_prompt) else agent_info.get("prompt", "")

    # special logic
    try:
        for tool in tool_list:
            if "KnowledgeBaseSearchTool" == tool.class_name:
                # TODO: use prompt template
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
        name="undefined" if agent_info["name"] is None else agent_info["name"],
        description="undefined" if agent_info["description"] is None else agent_info["description"],
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
    langchain_tools = await discover_langchain_tools()

    # now only admin can modify the agent, user_id is not used
    tools_list = search_tools_for_sub_agent(agent_id, tenant_id, user_id=None)
    for tool in tools_list:
        param_dict = {}
        for param in tool.get("params", []):
            param_dict[param["name"]] = param.get("default")
        tool_config = ToolConfig(
            class_name=tool.get("class_name"),
            name=tool.get("name"),
            description=tool.get("description"),
            inputs=tool.get("inputs"),
            output_type=tool.get("output_type"),
            params=param_dict,
            source=tool.get("source")
        )

        if tool.get("source") == "langchain":
            tool_class_name = tool.get("class_name")
            for langchain_tool in langchain_tools:
                if langchain_tool.name == tool_class_name:
                    tool_config.metadata = langchain_tool
                    break

        # special logic for knowledge base search tool
        if tool_config.class_name == "KnowledgeBaseSearchTool":
            knowledge_info_list = get_selected_knowledge_list(tenant_id=tenant_id, user_id=user_id)
            index_names = [knowledge_info.get("index_name") for knowledge_info in knowledge_info_list]
            tool_config.metadata = {"index_names": index_names,
                                    "es_core": elastic_core,
                                    "embedding_model": get_embedding_model(tenant_id=tenant_id)}
        tool_config_list.append(tool_config)
    
    return tool_config_list


async def discover_langchain_tools():
    """
    Discover LangChain tools implemented with the `@tool` decorator.
    
    Returns:
        list: List of discovered LangChain tool instances
    """
    from utils.langchain_utils import discover_langchain_modules
    
    langchain_tools = []

    # ----------------------------------------------
    # Discover LangChain tools implemented with the
    # `@tool` decorator and convert them to ToolConfig
    # ----------------------------------------------
    try:
        # Use the utility function to discover all BaseTool objects
        discovered_tools = discover_langchain_modules()
        
        for obj, filename in discovered_tools:
            try:
                # Log successful tool discovery
                logger.info(f"Loaded LangChain tool '{obj.name}' from {filename}")
                langchain_tools.append(obj)
            except Exception as e:
                logger.error(f"Error processing LangChain tool from {filename}: {e}")
                
    except Exception as e:
        logger.error(f"Unexpected error scanning LangChain tools directory: {e}")
    
    return langchain_tools


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

    remote_mcp_list = await get_remote_mcp_server_list(tenant_id=tenant_id)
    default_mcp_url = urljoin(config_manager.get_config("NEXENT_MCP_SERVER"), "sse")
    mcp_host = [default_mcp_url]
    for remote_mcp_info in remote_mcp_list:
        if remote_mcp_info["status"]:
            mcp_host.append(remote_mcp_info["remote_mcp_server"])

    agent_run_info = AgentRunInfo(
        query=final_query,
        model_config_list=model_list,
        observer=MessageObserver(lang=language),
        agent_config=await create_agent_config(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id,
                                               language=language),
        mcp_host=mcp_host,
        history=history,
        stop_event=threading.Event()
    )
    return agent_run_info
