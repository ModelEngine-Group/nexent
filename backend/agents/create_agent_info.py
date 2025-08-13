import threading
import yaml
import logging
from urllib.parse import urljoin
from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_model import AgentRunInfo, ModelConfig, AgentConfig, ToolConfig
from services.remote_mcp_service import get_remote_mcp_server_list
from utils.auth_utils import get_current_user_id

from database.agent_db import search_agent_info_by_agent_id, search_tools_for_sub_agent, \
    query_or_create_main_agent_id, query_sub_agents_id_list
from services.elasticsearch_service import ElasticSearchService, elastic_core, get_embedding_model
from services.tenant_config_service import get_selected_knowledge_list
from utils.prompt_template_utils import get_agent_prompt_template
from utils.config_utils import config_manager, tenant_config_manager, get_model_name_from_config
from smolagents.utils import BASE_BUILTIN_MODULES
from services.memory_config_service import build_memory_context
from jinja2 import Template, StrictUndefined

from nexent.memory.memory_service import search_memory_in_levels


logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.DEBUG)

async def create_model_config_list(tenant_id):
    main_model_config = tenant_config_manager.get_model_config(key="LLM_ID", tenant_id=tenant_id)
    sub_model_config = tenant_config_manager.get_model_config(key="LLM_SECONDARY_ID", tenant_id=tenant_id)

    return [ModelConfig(cite_name="main_model",
                        api_key=main_model_config.get("api_key", ""),
                        model_name=get_model_name_from_config(main_model_config) if main_model_config.get(
                            "model_name") else "",
                        url=main_model_config.get("base_url", "")),
            ModelConfig(cite_name="sub_model",
                        api_key=sub_model_config.get("api_key", ""),
                        model_name=get_model_name_from_config(sub_model_config) if sub_model_config.get(
                            "model_name") else "",
                        url=sub_model_config.get("base_url", ""))]


async def create_agent_config(agent_id, tenant_id, user_id, language: str = 'zh', last_user_query: str = None):
    agent_info = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id)

    # create sub agent
    sub_agent_id_list = query_sub_agents_id_list(main_agent_id=agent_id, tenant_id=tenant_id)
    managed_agents = []
    for sub_agent_id in sub_agent_id_list:
        sub_agent_config = await create_agent_config(
            agent_id=sub_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            language=language,
            last_user_query=last_user_query)
        managed_agents.append(sub_agent_config)

    tool_list = await create_tool_config_list(agent_id, tenant_id, user_id)
    
    # Build system prompt: prioritize segmented fields, fallback to original prompt field if not available
    duty_prompt = agent_info.get("duty_prompt", "")
    constraint_prompt = agent_info.get("constraint_prompt", "")
    few_shots_prompt = agent_info.get("few_shots_prompt", "")
    
    # Get template content
    prompt_template = get_agent_prompt_template(is_manager=len(managed_agents) > 0, language=language)

    # Get app information
    default_app_description = 'Nexent 是一个开源智能体SDK和平台' if language == 'zh' else 'Nexent is an open-source agent SDK and platform'
    app_name = tenant_config_manager.get_app_config('APP_NAME', tenant_id=tenant_id) or "Nexent"
    app_description = tenant_config_manager.get_app_config('APP_DESCRIPTION', tenant_id=tenant_id) or default_app_description

    # Get memory list
    memory_context = build_memory_context(user_id, tenant_id, agent_id)
    memory_list = []
    if memory_context.user_config.memory_switch:
        # TODO: 前端展示"回忆中..." Tag
        logger.debug("Retrieving memory list...")
        memory_levels = ["tenant", "agent", "user", "user_agent"]
        if memory_context.user_config.agent_share_option == "never":
            memory_levels.remove("agent")
        if memory_context.agent_id in memory_context.user_config.disable_agent_ids:
            memory_levels.remove("agent")
        if memory_context.agent_id in memory_context.user_config.disable_user_agent_ids:
            memory_levels.remove("user_agent")

        search_res = await search_memory_in_levels(
            query_text=last_user_query if last_user_query else agent_info.get("name"),
            memory_config=memory_context.memory_config,
            tenant_id=memory_context.tenant_id,
            user_id=memory_context.user_id,
            agent_id=memory_context.agent_id,
            memory_levels=memory_levels,
        )
        memory_list = search_res.get("results", [])
        logger.debug(f"Retrieved memory list: {memory_list}")
        # TODO: 前端展示"已抽取 xx 条回忆"

    # Build knowledge base summary
    knowledge_base_summary = ""
    try:
        for tool in tool_list:
            if "KnowledgeBaseSearchTool" == tool.class_name:
                knowledge_info_list = get_selected_knowledge_list(tenant_id=tenant_id, user_id=user_id)
                if knowledge_info_list:
                    for knowledge_info in knowledge_info_list:
                        knowledge_name = knowledge_info.get("index_name")
                        try:
                            message = ElasticSearchService().get_summary(index_name=knowledge_name)
                            summary = message.get("summary", "")
                            knowledge_base_summary += f"**{knowledge_name}**: {summary}\n\n"
                        except Exception as e:
                            logger.warning(f"Failed to get summary for knowledge base {knowledge_name}: {e}")
                else:
                    knowledge_base_summary = "当前没有可用的知识库索引。\n" if language == 'zh' else "No knowledge base indexes are currently available.\n"
                break  # Only process the first KnowledgeBaseSearchTool found
    except Exception as e:
        logger.error(f"Failed to build knowledge base summary: {e}")
    
    # Assemble system_prompt
    if (duty_prompt or constraint_prompt or few_shots_prompt):
        system_prompt = Template(prompt_template["system_prompt"], undefined=StrictUndefined).render({
            "duty": duty_prompt,
            "constraint": constraint_prompt,
            "few_shots": few_shots_prompt,
            "tools": {tool.name: tool for tool in tool_list},
            "managed_agents": {agent.name: agent for agent in managed_agents},
            "authorized_imports": str(BASE_BUILTIN_MODULES),
            "APP_NAME": app_name,
            "APP_DESCRIPTION": app_description,
            "memory_list": memory_list,
            "knowledge_base_summary": knowledge_base_summary
        })
    else:
        system_prompt = agent_info.get("prompt", "")
    
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
    tools_list = search_tools_for_sub_agent(agent_id, tenant_id)
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
    prompt_templates = get_agent_prompt_template(is_manager, language)
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


def filter_mcp_servers_and_tools(agent_run_info, default_mcp_url, remote_mcp_list):
    """
    过滤 MCP 服务器和工具，只保留实际用到的 MCP 服务器
    支持多级 agent，递归检查所有子 agent 的工具

    Args:
        agent_run_info: AgentRunInfo 对象
        default_mcp_url: 默认 MCP 服务器 URL
        remote_mcp_list: 远程 MCP 服务器列表

    Returns:
        None (直接修改 agent_run_info 对象)
    """
    used_mcp_urls = set()
    has_mcp_tools = False

    # 递归检查所有 agent 的工具
    def check_agent_tools(agent_config):
        nonlocal has_mcp_tools
        # 检查当前 agent 的工具
        for tool in getattr(agent_config, "tools", []):
            if hasattr(tool, "source") and tool.source == "mcp":
                has_mcp_tools = True
                # 对于 MCP 工具，从 usage 字段获取 MCP 服务器名称
                if hasattr(tool, "usage") and tool.usage:
                    mcp_server_name = tool.usage
                    # 从远程 MCP 列表中查找对应的 URL
                    for remote_mcp_info in remote_mcp_list:
                        if (remote_mcp_info["remote_mcp_server_name"] == mcp_server_name and
                            remote_mcp_info["status"]):
                            used_mcp_urls.add(remote_mcp_info["remote_mcp_server"])
                            break

        # 递归检查子 agent
        for sub_agent_config in getattr(agent_config, "managed_agents", []):
            check_agent_tools(sub_agent_config)

    # 检查所有 agent 的工具
    check_agent_tools(agent_run_info.agent_config)

    # 如果有 MCP 工具但没有找到对应的服务器，使用默认服务器
    if has_mcp_tools and not used_mcp_urls:
        used_mcp_urls.add(default_mcp_url)

    # 直接设置 mcp_host 为找到的 URL 列表
    agent_run_info.mcp_host = list(used_mcp_urls)


async def create_agent_run_info(agent_id, minio_files, query, history, authorization, language: str = 'zh'):
    user_id, tenant_id = get_current_user_id(authorization)

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
                                               language=language, last_user_query=final_query),
        mcp_host=mcp_host,
        history=history,
        stop_event=threading.Event()
    )

    return agent_run_info
