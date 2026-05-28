import threading
import logging
from typing import List, Optional
from urllib.parse import urljoin
from datetime import datetime

from jinja2 import Template, StrictUndefined
from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_model import AgentRunInfo, ModelConfig, AgentConfig, ToolConfig, ExternalA2AAgentConfig, AgentHistory
from nexent.core.agents.agent_context import ContextManagerConfig
from nexent.memory.memory_service import search_memory_in_levels

from services.file_management_service import get_llm_model, validate_urls_access
from services.vectordatabase_service import (
    ElasticSearchService,
    get_vector_db_core,
    get_embedding_model_by_index_name,
    get_rerank_model,
)
from services.remote_mcp_service import get_remote_mcp_server_list

from database.a2a_agent_db import PROTOCOL_JSONRPC
from services.memory_config_service import build_memory_context
from services.image_service import get_video_understanding_model, get_vlm_model
from database.agent_db import search_agent_info_by_agent_id, query_sub_agents_id_list
from database.agent_version_db import query_current_version_no
from database.tool_db import search_tools_for_sub_agent
from database.model_management_db import get_model_records, get_model_by_model_id
from database.knowledge_db import get_knowledge_name_map_by_index_names
from database.client import minio_client
from utils.model_name_utils import add_repo_to_name
from utils.prompt_template_utils import get_agent_prompt_template
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.context_utils import build_context_components
from consts.const import LOCAL_MCP_SERVER, MODEL_CONFIG_MAPPING, LANGUAGE, DATA_PROCESS_SERVICE, MINIO_DEFAULT_BUCKET
from consts.exceptions import ValidationError

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.DEBUG)


def _build_internal_s3_url(file: dict) -> str:
    """Build a valid S3 URL for internal tools from uploaded file metadata."""
    if not isinstance(file, dict):
        return ""

    object_name = str(file.get("object_name") or "").strip().lstrip("/")
    if object_name:
        bucket = MINIO_DEFAULT_BUCKET or "nexent"
        return f"s3://{bucket}/{object_name}"

    url = str(file.get("url") or "").strip()
    if not url or url.startswith("blob:") or url.startswith("s3:/blob:"):
        return ""

    if url.startswith("s3://"):
        return url

    if url.startswith("s3:/"):
        return "s3://" + url.replace("s3:/", "", 1).lstrip("/")

    return "s3:/" + url


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


def _extract_url_from_card(raw_card: Optional[dict]) -> str:
    """Extract http-json-rpc URL from Agent Card supportedInterfaces."""
    if not raw_card:
        return ""

    supported_interfaces = raw_card.get("supportedInterfaces", [])
    if not supported_interfaces:
        return raw_card.get("url", "")

    # Prefer http-json-rpc protocol
    for iface in supported_interfaces:
        protocol_binding = iface.get("protocolBinding", "").lower()
        if protocol_binding in ("http-json-rpc", "jsonrpc", "httpjsonrpc"):
            url = iface.get("url", "")
            if url:
                return url

    # Fallback to first interface with a URL
    for iface in supported_interfaces:
        url = iface.get("url", "")
        if url:
            return url

    return raw_card.get("url", "")


def _build_external_agent_config(agent: dict, agent_url: str) -> ExternalA2AAgentConfig:
    """Build an ExternalA2AAgentConfig from agent data."""
    return ExternalA2AAgentConfig(
        agent_id=str(agent.get("external_agent_id", "")),
        name=agent.get("name", "Unknown"),
        description=agent.get("description", "External A2A agent"),
        url=agent_url,
        api_key=None,
        transport_type=agent.get("transport_type", "http-streaming"),
        protocol_version=agent.get("protocol_version", "1.0"),
        protocol_type=agent.get("protocol_type", PROTOCOL_JSONRPC),
        timeout=300.0,
        raw_card=agent.get("raw_card"),
    )


def _get_external_a2a_agents(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0
) -> List[ExternalA2AAgentConfig]:
    """Get external A2A agent configurations for an agent.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number

    Returns:
        List of ExternalA2AAgentConfig for external A2A sub-agents
    """
    logger.info(f"[_get_external_a2a_agents] START - agent_id={agent_id}, tenant_id={tenant_id}")
    try:
        from database import a2a_agent_db

        external_agents = a2a_agent_db.query_external_sub_agents(
            local_agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        logger.info(f"[_get_external_a2a_agents] DB query returned {len(external_agents)} agents")
        logger.debug(f"[_get_external_a2a_agents] agent details: {external_agents}")

        result = []
        for agent in external_agents:
            agent_url = agent.get("agent_url", "") or _extract_url_from_card(agent.get("raw_card"))
            if not agent_url:
                logger.warning(
                    f"[_get_external_a2a_agents] Skipping agent '{agent.get('name')}' - no URL available"
                )
                continue

            result.append(_build_external_agent_config(agent, agent_url))

        logger.info(f"[_get_external_a2a_agents] returning {len(result)} ExternalA2AAgentConfig")
        for i, config in enumerate(result):
            logger.info(f"  [{i}] name={config.name}, description={config.description}")
        return result
    except Exception as e:
        logger.error(f"[_get_external_a2a_agents] FAILED: {e}", exc_info=True)
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
                        model_factory=record.get("model_factory"),
                        timeout_seconds=record.get("timeout_seconds"),
                        concurrency_limit=record.get("concurrency_limit")))
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
                    model_factory=main_model_config.get("model_factory"),
                    timeout_seconds=main_model_config.get("timeout_seconds"),
                    concurrency_limit=main_model_config.get("concurrency_limit")))
    model_list.append(
        ModelConfig(cite_name="sub_model",
                    api_key=main_model_config.get("api_key", ""),
                    model_name=get_model_name_from_config(main_model_config) if main_model_config.get(
                        "model_name") else "",
                    url=main_model_config.get("base_url", ""),
                    ssl_verify=main_model_config.get("ssl_verify", True),
                    model_factory=main_model_config.get("model_factory"),
                    timeout_seconds=main_model_config.get("timeout_seconds"),
                    concurrency_limit=main_model_config.get("concurrency_limit")))

    return model_list


async def create_agent_config(
    agent_id,
    tenant_id,
    user_id,
    language: str = LANGUAGE["ZH"],
    last_user_query: str = None,
    allow_memory_search: bool = True,
    version_no: int = 0,
    override_model_id: int | None = None,
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
            override_model_id=None,
        )
        managed_agents.append(sub_agent_config)

    # create external A2A agents (synchronous function, no await needed)
    external_a2a_agents = _get_external_a2a_agents(agent_id, tenant_id, version_no)

    tool_list = await create_tool_config_list(agent_id, tenant_id, user_id, version_no=version_no)

    # Build system prompt: prioritize segmented fields, fallback to original prompt field if not available
    duty_prompt = agent_info.get("duty_prompt", "")
    constraint_prompt = agent_info.get("constraint_prompt", "")
    few_shots_prompt = agent_info.get("few_shots_prompt", "")

    # Get template content (use manager template if has any sub-agents)
    is_manager = len(managed_agents) > 0 or len(external_a2a_agents) > 0
    prompt_template = get_agent_prompt_template(is_manager=is_manager, language=language)

    # Get app information
    default_app_description = 'Nexent 是一个开源智能体SDK和平台' if language == 'zh' else 'Nexent is an open-source agent SDK and platform'
    app_name = tenant_config_manager.get_app_config(
        'APP_NAME', tenant_id=tenant_id) or "Nexent"
    app_description = tenant_config_manager.get_app_config(
        'APP_DESCRIPTION', tenant_id=tenant_id) or default_app_description

    # Get memory list
    memory_context = build_memory_context(user_id, tenant_id, agent_id, skip_query=not allow_memory_search)
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
                    # Reuse the index_name -> display_name mapping from tool.metadata
                    # (already computed in create_tool_config_list to avoid redundant DB query)
                    index_name_to_display_map = tool.metadata.get("index_name_to_display_map", {}) if tool.metadata else {}
                    for index_name in index_names:
                        try:
                            display_name = index_name_to_display_map.get(index_name, index_name)
                            message = ElasticSearchService().get_summary(index_name=index_name)
                            summary = message.get("summary", "")
                            knowledge_base_summary += f"**{display_name}**: {summary}\n\n"
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

    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_manager = len(managed_agents) > 0 or len(external_a2a_agents) > 0

    render_kwargs = {
        "duty": duty_prompt,
        "constraint": constraint_prompt,
        "few_shots": few_shots_prompt,
        "tools": {tool.name: tool for tool in tool_list},
        "skills": skills,
        "managed_agents": {agent.name: agent for agent in managed_agents},
        "external_a2a_agents": {agent.agent_id: agent for agent in external_a2a_agents},
        "APP_NAME": app_name,
        "APP_DESCRIPTION": app_description,
        "memory_list": memory_list,
        "knowledge_base_summary": knowledge_base_summary,
        "time": time_str,
        "user_id": user_id,
    }
    system_prompt = Template(prompt_template["system_prompt"], undefined=StrictUndefined).render(render_kwargs)

    context_components = build_context_components(
        duty=duty_prompt,
        constraint=constraint_prompt,
        few_shots=few_shots_prompt,
        app_name=app_name,
        app_description=app_description,
        time_str=time_str,
        user_id=user_id,
        language=language,
        is_manager=is_manager,
        tools=render_kwargs["tools"],
        skills=skills,
        managed_agents=render_kwargs["managed_agents"],
        external_a2a_agents=render_kwargs["external_a2a_agents"],
        memory_list=memory_list,
        memory_search_query=last_user_query,
        knowledge_base_summary=knowledge_base_summary,
    )

    model_id_to_use = override_model_id if override_model_id else agent_info.get("model_id")
    model_max_tokens = 10000
    if model_id_to_use is not None:
        model_info = get_model_by_model_id(model_id_to_use, tenant_id=tenant_id)
        model_name = model_info["display_name"] if model_info is not None else "main_model"
        if model_info is not None and model_info.get("max_tokens"):
            model_max_tokens = model_info["max_tokens"]
    else:
        model_name = "main_model"
    # Use agent-level setting for context management, default to False
    enable_context_manager = agent_info.get("enable_context_manager", False)
    cm_config = ContextManagerConfig(
        enabled=enable_context_manager,
        token_threshold=model_max_tokens,
    )
    agent_config = AgentConfig(
        name="undefined" if agent_info["name"] is None else agent_info["name"],
        description="undefined" if agent_info["description"] is None else agent_info["description"],
        prompt_templates=await prepare_prompt_templates(
            is_manager=len(managed_agents) > 0 or len(external_a2a_agents) > 0,
            system_prompt=system_prompt,
            language=language,
            agent_id=agent_id
        ),
        tools=tool_list + _get_skill_script_tools(agent_id, tenant_id, version_no),
        max_steps=agent_info.get("max_steps", 15),
        model_name=model_name,
        provide_run_summary=agent_info.get("provide_run_summary", False),
        managed_agents=managed_agents,
        external_a2a_agents=external_a2a_agents,
        context_manager_config=cm_config,
        context_components=context_components,
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
            is_multimodal = bool(tool_config.params.pop("multimodal", False))
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            # Build display_name to index_name mapping for LLM parameter conversion
            # Also build reverse mapping (index_name -> display_name) for knowledge_base_summary
            index_names = param_dict.get("index_names", [])
            display_name_to_index_map = {}
            index_name_to_display_map = {}
            if index_names:
                knowledge_name_map = get_knowledge_name_map_by_index_names(index_names)
                # Reverse the mapping: display_name (knowledge_name) -> index_name
                for idx_name, kb_name in knowledge_name_map.items():
                    display_name_to_index_map[kb_name] = idx_name
                    index_name_to_display_map[idx_name] = kb_name

            tool_config.metadata = {
                "vdb_core": get_vector_db_core(),
                "embedding_model": None,
                "rerank_model": rerank_model,
                "display_name_to_index_map": display_name_to_index_map,
                "index_name_to_display_map": index_name_to_display_map,
            }

            # Must have embedding model for knowledge base search
            if not index_names:
                raise ValidationError(
                    "Embedding model is required for knowledge_base_search but index_names is empty")

            embedding_model, _, _ = get_embedding_model_by_index_name(tenant_id, index_names[0])
            if not embedding_model:
                raise ValidationError(
                    f"No embedding model found for index '{index_names[0]}'. "
                    f"Please configure an embedding model for this knowledge base.")
            tool_config.metadata["embedding_model"] = embedding_model
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
                "data_process_service_url": DATA_PROCESS_SERVICE,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id)
            }
        elif tool_config.class_name == "AnalyzeImageTool":
            tool_config.metadata = {
                # get_vlm_model reads the first multimodal slot, now shown as image understanding.
                "vlm_model": get_vlm_model(tenant_id=tenant_id),
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id)
            }
        elif tool_config.class_name in ["AnalyzeAudioTool", "AnalyzeVideoTool"]:
            tool_config.metadata = {
                "vlm_model": get_video_understanding_model(tenant_id=tenant_id),
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id)
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


async def join_minio_file_description_to_query(
    minio_files,
    query,
    history=None,
    max_files: int = 50,
    max_chars: int = 10000,
):
    """
    Join MinIO file descriptions to the user query.

    This function formats uploaded file information into a structured description
    that includes both S3 URL (for internal tools) and presigned_url (for external MCP tools).
    It processes files from both the current message and historical messages.

    De-duplication is performed using the file URL as the unique key. A maximum
    file count and total character limit are enforced to prevent prompt bloat.

    Args:
        minio_files: List of file info dicts from current message upload
        query: Original user query
        history: Optional list of historical message dicts, each may contain minio_files
        max_files: Maximum number of files to include (default 50)
        max_chars: Maximum total characters for file descriptions (default 10000)

    Returns:
        Modified query with file descriptions appended
    """
    final_query = query
    seen_urls: set[str] = set()
    all_files: list[dict] = []

    # Collect files from current message first (higher priority)
    if minio_files and isinstance(minio_files, list):
        for file in minio_files:
            if isinstance(file, dict) and file.get("name") and (file.get("url") or file.get("object_name")):
                s3_url = _build_internal_s3_url(file)
                if not s3_url:
                    continue
                if s3_url not in seen_urls:
                    seen_urls.add(s3_url)
                    all_files.append(file)

    # Collect files from historical messages (lower priority, already-deduped)
    if history and isinstance(history, list):
        for msg in history:
            if isinstance(msg, dict) and msg.get("minio_files"):
                for file in msg["minio_files"]:
                    if isinstance(file, dict) and file.get("name") and (file.get("url") or file.get("object_name")):
                        s3_url = _build_internal_s3_url(file)
                        if not s3_url:
                            continue
                        if s3_url not in seen_urls:
                            seen_urls.add(s3_url)
                            all_files.append(file)

    # Enforce file count limit (keep most recent files by truncating from the end)
    if len(all_files) > max_files:
        all_files = all_files[:max_files]
        logger.debug(f"File list truncated from {len(all_files)} to {max_files} files")

    if all_files:
        file_descriptions: list[str] = []
        # Calculate fixed overhead that is added only once
        prefix = "User uploaded files. The file information is as follows:\n"
        suffix = f"\n\nUser wants to answer questions based on the information in the above files: {query}"
        fixed_overhead = len(prefix) + len(suffix)

        for i, file in enumerate(all_files):
            s3_url = _build_internal_s3_url(file)
            presigned_url = file.get("presigned_url", "")

            # Build description with both URLs
            if presigned_url:
                desc = (
                    f"File name: {file['name']}\n"
                    f"- S3 URL: {s3_url}  [for tools WITHOUT [MCP] prefix, like analyze_text_file]\n"
                    f"- presigned_url: {presigned_url}  [for tools WITH [MCP] prefix]"
                )
            else:
                desc = f"File name: {file['name']}, S3 URL: {s3_url}  [permanent]"

            # Calculate total length if we include this description
            # Each description after the first adds 2 chars for \n\n separator
            separator_chars = 2 if i > 0 else 0
            total_len = sum(len(d) for d in file_descriptions) + len(desc) + separator_chars + fixed_overhead

            # Check if adding this description would exceed the character limit
            if total_len > max_chars:
                logger.debug(
                    f"File descriptions truncated at {len(file_descriptions)} files "
                    f"to stay within {max_chars} character limit"
                )
                break

            file_descriptions.append(desc)

        if file_descriptions:
            final_query = prefix + "\n\n".join(file_descriptions) + suffix

    return final_query


def _format_minio_files_for_content(minio_files: Optional[List[dict]], max_files: int = 20) -> str:
    """Format minio_files into a string for embedding in history content.

    Args:
        minio_files: List of file info dicts
        max_files: Maximum number of files to include per message

    Returns:
        Formatted string describing the files, or empty string if no files
    """
    if not minio_files or not isinstance(minio_files, list):
        return ""

    file_lines = []
    for i, file in enumerate(minio_files):
        if i >= max_files:
            file_lines.append(f"  - ... (and {len(minio_files) - max_files} more files)")
            break
        if isinstance(file, dict) and file.get("name") and (file.get("url") or file.get("object_name")):
            s3_url = _build_internal_s3_url(file)
            if not s3_url:
                continue
            presigned_url = file.get("presigned_url", "")
            if presigned_url:
                file_lines.append(
                    f"  - {file['name']}: {s3_url} (for non-MCP tools), presigned_url: {presigned_url} (for [MCP] tools)"
                )
            else:
                file_lines.append(f"  - {file['name']}: {s3_url}")

    if not file_lines:
        return ""

    return "\n[Attached files]:\n" + "\n".join(file_lines)


def _convert_history_with_minio_files(history: List) -> Optional[List[AgentHistory]]:
    """Convert HistoryItem list to AgentHistory list, embedding minio_files into content.

    Args:
        history: List of HistoryItem from API

    Returns:
        List of AgentHistory with file info embedded in content, or None if history is None
    """
    if history is None:
        return None

    result = []
    for item in history:
        content = item.content
        if item.minio_files:
            file_info = _format_minio_files_for_content(item.minio_files)
            if file_info:
                content = content + file_info if content else file_info
        result.append(AgentHistory(role=item.role, content=content))
    return result


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

        # Recursively check sub-agents (only internal AgentConfig, not external A2A)
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
    override_version_no: int | None = None,
    override_model_id: int | None = None,
):
    # Determine which version_no to use based on is_debug flag
    # If is_debug=false, use the current published version (current_version_no)
    # If is_debug=true, use version 0 (draft/editing state)
    if override_version_no is not None:
        version_no = override_version_no
    elif is_debug:
        version_no = 0
    else:
        version_no = query_current_version_no(agent_id=agent_id, tenant_id=tenant_id)
        if version_no is None:
            version_no = 0
            logger.info(f"Agent {agent_id} has no published version, using draft version 0")

    final_query = await join_minio_file_description_to_query(
        minio_files=minio_files,
        query=query,
        history=history
    )
    model_list = await create_model_config_list(tenant_id)
    create_config_kwargs = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "language": language,
        "last_user_query": final_query,
        "allow_memory_search": allow_memory_search,
        "version_no": version_no,
    }
    if override_model_id is not None:
        create_config_kwargs["override_model_id"] = override_model_id

    agent_config = await create_agent_config(**create_config_kwargs)

    remote_mcp_list = await get_remote_mcp_server_list(tenant_id=tenant_id, is_need_auth=True)
    default_mcp_url = urljoin(LOCAL_MCP_SERVER, "sse")
    remote_mcp_list.append({
        "remote_mcp_server_name": "outer-apis",
        "remote_mcp_server": default_mcp_url,
        "status": True,
        "authorization_token": None
    })
    remote_mcp_dict = {record["remote_mcp_server_name"]: record for record in remote_mcp_list if record["status"]}

    # Filter MCP servers and tools, and build mcp_host with authorization
    used_mcp_urls = filter_mcp_servers_and_tools(agent_config, remote_mcp_dict)

    # Build mcp_host list with authorization tokens and custom headers
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
            headers = {}
            auth_token = mcp_record.get("authorization_token")
            if auth_token:
                headers["Authorization"] = auth_token
            custom_headers = mcp_record.get("custom_headers")
            if custom_headers and isinstance(custom_headers, dict):
                headers.update(custom_headers)
            if headers:
                mcp_config["headers"] = headers
            mcp_host.append(mcp_config)
        else:
            # Fallback to string format if record not found
            mcp_host.append(url)

    # Convert HistoryItem (from API) to AgentHistory (expected by SDK)
    converted_history = _convert_history_with_minio_files(history)

    agent_run_info = AgentRunInfo(
        query=final_query,
        model_config_list=model_list,
        observer=MessageObserver(lang=language),
        agent_config=agent_config,
        mcp_host=mcp_host,
        history=converted_history,
        stop_event=threading.Event()
    )
    return agent_run_info
