import threading
import logging
from typing import List
from urllib.parse import urljoin
from datetime import datetime

from jinja2 import Template, StrictUndefined
from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_model import AgentRunInfo, ModelConfig, AgentConfig, ToolConfig
from nexent.memory.memory_service import search_memory_in_levels

from services.file_management_service import get_llm_model
from services.vectordatabase_service import (
    ElasticSearchService,
    get_vector_db_core,
    get_embedding_model,
    get_rerank_model,
)
from services.remote_mcp_service import get_remote_mcp_server_list
from services.memory_config_service import build_memory_context
from services.image_service import get_vlm_model
from database.agent_db import search_agent_info_by_agent_id, query_sub_agents_id_list
from database.agent_version_db import query_current_version_no
from database.tool_db import search_tools_for_sub_agent
from database.model_management_db import get_model_records, get_model_by_model_id
from database.client import minio_client
from utils.model_name_utils import add_repo_to_name
from utils.prompt_template_utils import get_agent_prompt_template
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from consts.const import LOCAL_MCP_SERVER, MODEL_CONFIG_MAPPING, LANGUAGE, DATA_PROCESS_SERVICE
import re

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.DEBUG)


def _get_skills_for_template(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0
) -> List[dict]:
    """Get skills list for prompt template injection.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number

    Returns:
        List of skill dicts with name and description
    """
    try:
        from services.skill_service import SkillService
        skill_service = SkillService()
        enabled_skills = skill_service.get_enabled_skills_for_agent(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no
        )
        return [
            {"name": s.get("name", ""), "description": s.get("description", "")}
            for s in enabled_skills
        ]
    except Exception as e:
        logger.warning(f"Failed to get skills for template: {e}")
        return []


def _get_skill_script_tools(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0
) -> List[ToolConfig]:
    """Get tool config for skill script execution and skill reading.

    Args:
        agent_id: Agent ID for filtering available skills in error messages.
        tenant_id: Tenant ID for filtering available skills in error messages.
        version_no: Version number for filtering available skills.

    Returns:
        List of ToolConfig for skill execution and reading tools
    """
    from consts.const import CONTAINER_SKILLS_PATH

    skill_context = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "version_no": version_no,
    }

    try:
        return [
            ToolConfig(
                class_name="RunSkillScriptTool",
                name="run_skill_script",
                description="Execute a skill script with given parameters. Use this to run Python or shell scripts that are part of a skill.",
                inputs='{"skill_name": "str", "script_path": "str", "params": "dict"}',
                output_type="string",
                params={"local_skills_dir": CONTAINER_SKILLS_PATH},
                source="builtin",
                usage="builtin",
                metadata=skill_context,
            ),
            ToolConfig(
                class_name="ReadSkillMdTool",
                name="read_skill_md",
                description="Read skill execution guide and optional additional files. Always reads SKILL.md first, then optionally reads additional files.",
                inputs='{"skill_name": "str", "additional_files": "list[str]"}',
                output_type="string",
                params={"local_skills_dir": CONTAINER_SKILLS_PATH},
                source="builtin",
                usage="builtin",
                metadata=skill_context,
            ),
            ToolConfig(
                class_name="ReadSkillConfigTool",
                name="read_skill_config",
                description="Read the config.yaml file from a skill directory. Returns JSON containing configuration variables needed for skill workflows.",
                inputs='{"skill_name": "str"}',
                output_type="string",
                params={"local_skills_dir": CONTAINER_SKILLS_PATH},
                source="builtin",
                usage="builtin",
                metadata=skill_context,
            ),
            ToolConfig(
                class_name="WriteSkillFileTool",
                name="write_skill_file",
                description="Write content to a file within a skill directory. Creates parent directories if they do not exist.",
                inputs='{"skill_name": "str", "file_path": "str", "content": "str"}',
                output_type="string",
                params={"local_skills_dir": CONTAINER_SKILLS_PATH},
                source="builtin",
                usage="builtin",
                metadata=skill_context,
            )
        ]
    except Exception as e:
        logger.warning(f"Failed to load skill script tool: {e}")
        return []


async def create_model_config_list(tenant_id):
    records = get_model_records({"model_type": "llm"}, tenant_id)
    model_list = []
    for record in records:
        model_list.append(
            ModelConfig(cite_name=record["display_name"],
                        api_key=record.get("api_key", ""),
                        model_name=add_repo_to_name(
                                model_repo=record["model_repo"],
                                model_name=record["model_name"],
                            ),
                        url=record["base_url"],
                        ssl_verify=record.get("ssl_verify", True),
                        model_factory=record.get("model_factory")))
    # fit for old version, main_model and sub_model use default model
    main_model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
    model_list.append(
        ModelConfig(cite_name="main_model",
                    api_key=main_model_config.get("api_key", ""),
                    model_name=get_model_name_from_config(main_model_config) if main_model_config.get(
                        "model_name") else "",
                    url=main_model_config.get("base_url", ""),
                    ssl_verify=main_model_config.get("ssl_verify", True),
                    model_factory=main_model_config.get("model_factory")))
    model_list.append(
        ModelConfig(cite_name="sub_model",
                    api_key=main_model_config.get("api_key", ""),
                    model_name=get_model_name_from_config(main_model_config) if main_model_config.get(
                        "model_name") else "",
                    url=main_model_config.get("base_url", ""),
                    ssl_verify=main_model_config.get("ssl_verify", True),
                    model_factory=main_model_config.get("model_factory")))

    return model_list


async def create_agent_config(
    agent_id,
    tenant_id,
    user_id,
    language: str = LANGUAGE["ZH"],
    last_user_query: str = None,
    allow_memory_search: bool = True,
    version_no: int = 0,
):
    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)

    # create sub agent
    sub_agent_id_list = query_sub_agents_id_list(
        main_agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)
    managed_agents = []
    for sub_agent_id in sub_agent_id_list:
        # Get the current published version for this sub-agent (from draft version 0)
        sub_agent_version_no = query_current_version_no(
            agent_id=sub_agent_id, tenant_id=tenant_id) or 0
        sub_agent_config = await create_agent_config(
            agent_id=sub_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            language=language,
            last_user_query=last_user_query,
            allow_memory_search=allow_memory_search,
            version_no=sub_agent_version_no,
        )
        managed_agents.append(sub_agent_config)

    tool_list = await create_tool_config_list(agent_id, tenant_id, user_id, version_no=version_no)

    # Build system prompt: prioritize segmented fields, fallback to original prompt field if not available
    duty_prompt = agent_info.get("duty_prompt", "")
    constraint_prompt = agent_info.get("constraint_prompt", "")
    few_shots_prompt = agent_info.get("few_shots_prompt", "")

    # Get template content
    prompt_template = get_agent_prompt_template(
        is_manager=len(managed_agents) > 0, language=language)

    # Get app information
    default_app_description = 'Nexent 是一个开源智能体SDK和平台' if language == 'zh' else 'Nexent is an open-source agent SDK and platform'
    app_name = tenant_config_manager.get_app_config(
        'APP_NAME', tenant_id=tenant_id) or "Nexent"
    app_description = tenant_config_manager.get_app_config(
        'APP_DESCRIPTION', tenant_id=tenant_id) or default_app_description

    # Get memory list
    memory_context = build_memory_context(user_id, tenant_id, agent_id)
    memory_list = []
    if allow_memory_search and memory_context.user_config.memory_switch:
        logger.debug("Retrieving memory list...")
        memory_levels = ["tenant", "agent", "user", "user_agent"]
        if memory_context.user_config.agent_share_option == "never":
            memory_levels.remove("agent")
        if memory_context.agent_id in memory_context.user_config.disable_agent_ids:
            memory_levels.remove("agent")
        if memory_context.agent_id in memory_context.user_config.disable_user_agent_ids:
            memory_levels.remove("user_agent")

        try:
            search_res = await search_memory_in_levels(
                query_text=last_user_query,
                memory_config=memory_context.memory_config,
                tenant_id=memory_context.tenant_id,
                user_id=memory_context.user_id,
                agent_id=memory_context.agent_id,
                memory_levels=memory_levels,
            )
            memory_list = search_res.get("results", [])
            logger.debug(f"Retrieved memory list: {memory_list}")
        except Exception as e:
            # Bubble up to streaming layer so it can emit <MEM_FAILED> and fall back
            raise Exception(f"Failed to retrieve memory list: {e}")

    # Build knowledge base summary
    knowledge_base_summary = ""
    try:
        for tool in tool_list:
            if "KnowledgeBaseSearchTool" == tool.class_name:
                index_names = tool.params.get("index_names")
                if index_names:
                    for index_name in index_names:
                        try:
                            message = ElasticSearchService().get_summary(index_name=index_name)
                            summary = message.get("summary", "")
                            knowledge_base_summary += f"**{index_name}**: {summary}\n\n"
                        except Exception as e:
                            logger.warning(
                                f"Failed to get summary for knowledge base {index_name}: {e}")
                else:
                    # TODO: Prompt should be refactored to yaml file
                    knowledge_base_summary = "当前没有可用的知识库索引。\n" if language == 'zh' else "No knowledge base indexes are currently available.\n"
                break  # Only process the first KnowledgeBaseSearchTool found
    except Exception as e:
        logger.error(f"Failed to build knowledge base summary: {e}")

    # Assemble system_prompt
    # Get skills list for prompt template
    skills = _get_skills_for_template(agent_id, tenant_id, version_no)

    render_kwargs = {
        "duty": duty_prompt,
        "constraint": constraint_prompt,
        "few_shots": few_shots_prompt,
        "tools": {tool.name: tool for tool in tool_list},
        "skills": skills,
        "managed_agents": {agent.name: agent for agent in managed_agents},
        "APP_NAME": app_name,
        "APP_DESCRIPTION": app_description,
        "memory_list": memory_list,
        "knowledge_base_summary": knowledge_base_summary,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user_id,
    }
    system_prompt = Template(prompt_template["system_prompt"], undefined=StrictUndefined).render(render_kwargs)

    if agent_info.get("model_id") is not None:
        model_info = get_model_by_model_id(agent_info.get("model_id"))
        model_name = model_info["display_name"] if model_info is not None else "main_model"
    else:
        model_name = "main_model"
    agent_config = AgentConfig(
        name="undefined" if agent_info["name"] is None else agent_info["name"],
        description="undefined" if agent_info["description"] is None else agent_info["description"],
        prompt_templates=await prepare_prompt_templates(
            is_manager=len(managed_agents) > 0,
            system_prompt=system_prompt,
            language=language,
            agent_id=agent_id
        ),
        tools=tool_list + _get_skill_script_tools(agent_id, tenant_id, version_no),
        max_steps=agent_info.get("max_steps", 10),
        model_name=model_name,
        provide_run_summary=agent_info.get("provide_run_summary", False),
        managed_agents=managed_agents
    )
    return agent_config


async def create_tool_config_list(agent_id, tenant_id, user_id, version_no: int = 0):
    # create tool
    tool_config_list = []
    langchain_tools = await discover_langchain_tools()

    # now only admin can modify the agent, user_id is not used
    tools_list = search_tools_for_sub_agent(agent_id, tenant_id, version_no=version_no)
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
            source=tool.get("source"),
            usage=tool.get("usage")
        )

        if tool.get("source") == "langchain":
            tool_class_name = tool.get("class_name")
            for langchain_tool in langchain_tools:
                if langchain_tool.name == tool_class_name:
                    tool_config.metadata = langchain_tool
                    break

        # special logic for search tools that may use reranking models
        if tool_config.class_name == "KnowledgeBaseSearchTool":
            rerank = param_dict.get("rerank", False)
            rerank_model_name = param_dict.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            tool_config.metadata = {
                "vdb_core": get_vector_db_core(),
                "embedding_model": get_embedding_model(tenant_id=tenant_id),
                "rerank_model": rerank_model,
            }
        elif tool_config.class_name in ["DifySearchTool", "DataMateSearchTool"]:
            rerank = param_dict.get("rerank", False)
            rerank_model_name = param_dict.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            tool_config.metadata = {
                "rerank_model": rerank_model,
            }
        elif tool_config.class_name == "AnalyzeTextFileTool":
            tool_config.metadata = {
                "llm_model": get_llm_model(tenant_id=tenant_id),
                "storage_client": minio_client,
                "data_process_service_url": DATA_PROCESS_SERVICE
            }
        elif tool_config.class_name == "AnalyzeImageTool":
            tool_config.metadata = {
                "vlm_model": get_vlm_model(tenant_id=tenant_id),
                "storage_client": minio_client,
            }

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
                logger.info(
                    f"Loaded LangChain tool '{obj.name}' from {filename}")
                langchain_tools.append(obj)
            except Exception as e:
                logger.error(
                    f"Error processing LangChain tool from {filename}: {e}")

    except Exception as e:
        logger.error(
            f"Unexpected error scanning LangChain tools directory: {e}")

    return langchain_tools


async def prepare_prompt_templates(
    is_manager: bool,
    system_prompt: str,
    language: str = 'zh',
    agent_id: int = None,
):
    """
    Prepare prompt templates, support multiple languages

    Args:
        is_manager: Whether it is a manager mode
        system_prompt: System prompt content
        language: Language code ('zh' or 'en')
        agent_id: Agent ID for fetching skill instances

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
            if isinstance(file, dict) and "url" in file and file["url"] and "name" in file and file["name"]:
                file_descriptions.append(f"File name: {file['name']}, S3 URL: s3:/{file['url']}")
        if file_descriptions:
            final_query = "User uploaded files. The file information is as follows:\n"
            final_query += "\n".join(file_descriptions) + "\n\n"
            final_query += f"User wants to answer questions based on the information in the above files: {query}"
    return final_query


def filter_mcp_servers_and_tools(input_agent_config: AgentConfig, mcp_info_dict) -> list:
    """
    Filter mcp servers and tools, only keep the actual used mcp servers
    Support multi-level agent, recursively check all sub-agent tools
    """
    used_mcp_urls = set()

    # Recursively check all agent tools
    def check_agent_tools(agent_config: AgentConfig):
        # Check current agent tools
        for tool in agent_config.tools:
            if tool.source == "mcp" and tool.usage in mcp_info_dict:
                used_mcp_urls.add(
                    mcp_info_dict[tool.usage]["remote_mcp_server"])

        # Recursively check sub-agent
        for sub_agent_config in agent_config.managed_agents:
            check_agent_tools(sub_agent_config)

    # Check all agent tools
    check_agent_tools(input_agent_config)

    return list(used_mcp_urls)


async def create_agent_run_info(
    agent_id,
    minio_files,
    query,
    history,
    tenant_id: str,
    user_id: str,
    language: str = "zh",
    allow_memory_search: bool = True,
    is_debug: bool = False,
):
    # Determine which version_no to use based on is_debug flag
    # If is_debug=false, use the current published version (current_version_no)
    # If is_debug=true, use version 0 (draft/editing state)
    if is_debug:
        version_no = 0
    else:
        # Get current published version number
        version_no = query_current_version_no(agent_id=agent_id, tenant_id=tenant_id)
        # Fallback to 0 if no published version exists
        if version_no is None:
            version_no = 0
            logger.info(f"Agent {agent_id} has no published version, using draft version 0")

    final_query = await join_minio_file_description_to_query(minio_files=minio_files, query=query)
    model_list = await create_model_config_list(tenant_id)
    agent_config = await create_agent_config(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        language=language,
        last_user_query=final_query,
        allow_memory_search=allow_memory_search,
        version_no=version_no,
    )

    remote_mcp_list = await get_remote_mcp_server_list(tenant_id=tenant_id, is_need_auth=True)
    default_mcp_url = urljoin(LOCAL_MCP_SERVER, "sse")
    remote_mcp_list.append({
        "remote_mcp_server_name": "nexent",
        "remote_mcp_server": default_mcp_url,
        "status": True,
        "authorization_token": None
    })
    remote_mcp_dict = {record["remote_mcp_server_name"]: record for record in remote_mcp_list if record["status"]}

    # Filter MCP servers and tools, and build mcp_host with authorization
    used_mcp_urls = filter_mcp_servers_and_tools(agent_config, remote_mcp_dict)

    # Build mcp_host list with authorization tokens
    mcp_host = []
    for url in used_mcp_urls:
        # Find the MCP record for this URL
        mcp_record = None
        for record in remote_mcp_list:
            if record.get("remote_mcp_server") == url and record.get("status"):
                mcp_record = record
                break

        if mcp_record:
            mcp_config = {
                "url": url,
                "transport": "sse" if url.endswith("/sse") else "streamable-http"
            }
            # Add authorization if present
            auth_token = mcp_record.get("authorization_token")
            if auth_token:
                mcp_config["authorization"] = auth_token
            mcp_host.append(mcp_config)
        else:
            # Fallback to string format if record not found
            mcp_host.append(url)

    agent_run_info = AgentRunInfo(
        query=final_query,
        model_config_list=model_list,
        observer=MessageObserver(lang=language),
        agent_config=agent_config,
        mcp_host=mcp_host,
        history=history,
        stop_event=threading.Event()
    )
    return agent_run_info
