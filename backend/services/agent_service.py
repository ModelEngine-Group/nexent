import asyncio
import json
import logging
import os
import uuid
from collections import deque

from fastapi import Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from nexent.core.agents.run_agent import agent_run
from nexent.memory.memory_service import clear_memory, add_memory_in_levels

from agents.agent_run_manager import agent_run_manager
from agents.create_agent_info import create_agent_run_info, create_tool_config_list
from agents.preprocess_manager import preprocess_manager
from consts.const import MEMORY_SEARCH_START_MSG, MEMORY_SEARCH_DONE_MSG, MEMORY_SEARCH_FAIL_MSG, TOOL_TYPE_MAPPING, LANGUAGE, MESSAGE_ROLE
from consts.exceptions import MemoryPreparationException
from consts.model import (
    AgentInfoRequest,
    AgentRequest,
    ExportAndImportAgentInfo,
    ExportAndImportDataFormat,
    MCPInfo,
    ToolInstanceInfoRequest,
    ToolSourceEnum
)
from database.agent_db import (
    create_agent,
    delete_agent_by_id,
    delete_agent_relationship,
    delete_related_agent,
    insert_related_agent,
    query_all_agent_info_by_tenant_id,
    query_sub_agents_id_list,
    search_agent_id_by_agent_name,
    search_agent_info_by_agent_id,
    search_blank_sub_agent_by_main_agent_id,
    update_agent
)
from database.remote_mcp_db import check_mcp_name_exists, get_mcp_server_by_name_and_tenant
from database.tool_db import (
    check_tool_is_available,
    create_or_update_tool_by_tool_info,
    delete_tools_by_agent_id,
    query_all_enabled_tool_instances,
    query_all_tools,
    search_tools_for_sub_agent
)
from services.conversation_management_service import save_conversation_assistant, save_conversation_user
from services.memory_config_service import build_memory_context
from services.remote_mcp_service import add_remote_mcp_server_list
from services.tool_configuration_service import update_tool_list
from utils.auth_utils import get_current_user_info, get_user_language
from utils.memory_utils import build_memory_config
from utils.thread_utils import submit

logger = logging.getLogger(__name__)


# -------------------------------------------------------------
# Internal helper functions
# -------------------------------------------------------------


def _resolve_user_tenant_language(
    authorization: str,
    http_request: Request | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
):
    """Resolve user_id, tenant_id, language with optional overrides.

    If user_id and tenant_id are provided, do not parse from authorization again.
    """
    if user_id is None or tenant_id is None:
        return get_current_user_info(authorization, http_request)
    else:
        return user_id, tenant_id, get_user_language(http_request)


async def _stream_agent_chunks(
    agent_request: "AgentRequest",
    user_id: str,
    tenant_id: str,
    agent_run_info,
    memory_ctx,
):
    """Yield SSE chunks from agent_run while persisting messages & cleanup.

    This utility centralizes the common streaming logic used by both
    generate_stream_with_memory and generate_stream_no_memory so that the code
    is easier to maintain and less error-prone.
    """

    local_messages = []
    captured_final_answer = None
    try:
        async for chunk in agent_run(agent_run_info):
            local_messages.append(chunk)
            # Try to capture the final answer as it streams by in order to start memory addition
            try:
                data = json.loads(chunk)
                if data.get("type") == "final_answer":
                    captured_final_answer = data.get("content")
            except Exception:
                pass
            yield f"data: {chunk}\n\n"
    except Exception as run_exc:
        logger.error(f"Agent run error: {str(run_exc)}")
        # Emit an error chunk and terminate the stream immediately
        try:
            error_payload = json.dumps(
                {"type": "error", "content": str(run_exc)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"
        finally:
            return
    finally:
        # Persist assistant messages for non-debug runs
        if not agent_request.is_debug:
            save_messages(
                agent_request,
                target=MESSAGE_ROLE["ASSISTANT"],
                messages=local_messages,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        # Always unregister the run to release resources
        agent_run_manager.unregister_agent_run(agent_request.conversation_id, user_id)

        # Schedule memory addition in background to avoid blocking SSE termination
        async def _add_memory_background():
            try:
                # Skip if memory recording is disabled
                if not getattr(memory_ctx.user_config, "memory_switch", False):
                    return
                # Use the captured final answer during streaming; observer queue was drained
                final_answer_local = captured_final_answer
                if not final_answer_local:
                    return

                # Determine allowed memory levels
                levels_local = {"agent", "user_agent"}
                if memory_ctx.user_config.agent_share_option == "never":
                    levels_local.discard("agent")
                if memory_ctx.agent_id in getattr(memory_ctx.user_config, "disable_agent_ids", []):
                    levels_local.discard("agent")
                if memory_ctx.agent_id in getattr(memory_ctx.user_config, "disable_user_agent_ids", []):
                    levels_local.discard("user_agent")
                if not levels_local:
                    return

                mem_messages_local = [
                    {"role": MESSAGE_ROLE["USER"], "content": agent_run_info.query},
                    {"role": MESSAGE_ROLE["ASSISTANT"], "content": final_answer_local},
                ]

                add_result_local = await add_memory_in_levels(
                    messages=mem_messages_local,
                    memory_config=memory_ctx.memory_config,
                    tenant_id=memory_ctx.tenant_id,
                    user_id=memory_ctx.user_id,
                    agent_id=memory_ctx.agent_id,
                    memory_levels=list(levels_local),
                )
                items_local = add_result_local.get("results", [])
                logger.info(f"Memory addition completed: {items_local}")
            except Exception as bg_e:
                logger.error(
                    f"Unexpected error during background memory addition: {bg_e}")

        try:
            asyncio.create_task(_add_memory_background())
        except Exception as schedule_err:
            logger.error(
                f"Failed to schedule background memory addition: {schedule_err}")


def get_enable_tool_id_by_agent_id(agent_id: int, tenant_id: str):
    all_tool_instance = query_all_enabled_tool_instances(
        agent_id=agent_id, tenant_id=tenant_id)
    enable_tool_id_set = set()
    for tool_instance in all_tool_instance:
        if tool_instance["enabled"]:
            enable_tool_id_set.add(tool_instance["tool_id"])
    return list(enable_tool_id_set)


async def get_creating_sub_agent_id_service(tenant_id: str, user_id: str = None) -> int:
    """
        first find the blank sub agent, if it exists, it means the agent was created before, but exited prematurely;
                                  if it does not exist, create a new one
    """
    sub_agent_id = search_blank_sub_agent_by_main_agent_id(tenant_id=tenant_id)
    if sub_agent_id:
        return sub_agent_id
    else:
        return create_agent(agent_info={"enabled": False}, tenant_id=tenant_id, user_id=user_id)["agent_id"]


async def get_agent_info_impl(agent_id: int, tenant_id: str):
    try:
        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Failed to get agent info: {str(e)}")
        raise ValueError(f"Failed to get agent info: {str(e)}")

    try:
        tool_info = search_tools_for_sub_agent(
            agent_id=agent_id, tenant_id=tenant_id)
        agent_info["tools"] = tool_info
    except Exception as e:
        logger.error(f"Failed to get agent tools: {str(e)}")
        agent_info["tools"] = []

    try:
        sub_agent_id_list = query_sub_agents_id_list(
            main_agent_id=agent_id, tenant_id=tenant_id)
        agent_info["sub_agent_id_list"] = sub_agent_id_list
    except Exception as e:
        logger.error(f"Failed to get sub agent id list: {str(e)}")
        agent_info["sub_agent_id_list"] = []

    return agent_info


async def get_creating_sub_agent_info_impl(authorization: str = Header(None)):
    user_id, tenant_id, _ = get_current_user_info(authorization)

    try:
        sub_agent_id = await get_creating_sub_agent_id_service(tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to get creating sub agent id: {str(e)}")
        raise ValueError(f"Failed to get creating sub agent id: {str(e)}")

    try:
        agent_info = search_agent_info_by_agent_id(
            agent_id=sub_agent_id, tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"Failed to get sub agent info: {str(e)}")
        raise ValueError(f"Failed to get sub agent info: {str(e)}")

    try:
        enable_tool_id_list = get_enable_tool_id_by_agent_id(
            sub_agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Failed to get sub agent enable tool id list: {str(e)}")
        raise ValueError(
            f"Failed to get sub agent enable tool id list: {str(e)}")

    return {"agent_id": sub_agent_id,
            "name": agent_info.get("name"),
            "display_name": agent_info.get("display_name"),
            "description": agent_info.get("description"),
            "enable_tool_id_list": enable_tool_id_list,
            "model_name": agent_info["model_name"],
            "max_steps": agent_info["max_steps"],
            "business_description": agent_info["business_description"],
            "duty_prompt": agent_info.get("duty_prompt"),
            "constraint_prompt": agent_info.get("constraint_prompt"),
            "few_shots_prompt": agent_info.get("few_shots_prompt"),
            "sub_agent_id_list": query_sub_agents_id_list(main_agent_id=sub_agent_id, tenant_id=tenant_id)}


async def update_agent_info_impl(request: AgentInfoRequest, authorization: str = Header(None)):
    user_id, tenant_id, _ = get_current_user_info(authorization)

    try:
        update_agent(request.agent_id, request, tenant_id, user_id)
    except Exception as e:
        logger.error(f"Failed to update agent info: {str(e)}")
        raise ValueError(f"Failed to update agent info: {str(e)}")


async def delete_agent_impl(agent_id: int, authorization: str = Header(None)):
    user_id, tenant_id, _ = get_current_user_info(authorization)

    try:
        delete_agent_by_id(agent_id, tenant_id, user_id)
        delete_agent_relationship(agent_id, tenant_id, user_id)
        delete_tools_by_agent_id(agent_id, tenant_id, user_id)

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
            logger.info(
                f"Cleared agent memory for agent {agent_id}: {agent_memory_result}")
        except Exception as e:
            logger.error(
                f"Failed to clear agent-level memory for agent {agent_id}: {str(e)}")

        # Clean up user_agent-level memory
        try:
            user_agent_memory_result = await clear_memory(
                memory_level="user_agent",
                memory_config=memory_config,
                tenant_id=tenant_id,
                user_id=user_id,
                agent_id=str(agent_id)
            )
            logger.info(
                f"Cleared user_agent memory for agent {agent_id}: {user_agent_memory_result}")
        except Exception as e:
            logger.error(
                f"Failed to clear user_agent-level memory for agent {agent_id}: {str(e)}")

    except Exception as e:
        logger.error(
            f"Failed to build memory config for agent {agent_id}: {str(e)}")
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

    user_id, tenant_id, _ = get_current_user_info(authorization)

    export_agent_dict = {}
    search_list = deque([agent_id])
    agent_id_set = set()

    mcp_info_set = set()

    while len(search_list):
        left_ele = search_list.popleft()
        if left_ele in agent_id_set:
            continue

        agent_id_set.add(left_ele)
        agent_info = await export_agent_by_agent_id(agent_id=left_ele, tenant_id=tenant_id, user_id=user_id)

        # collect mcp name
        for tool in agent_info.tools:
            if tool.source == "mcp" and tool.usage:
                mcp_info_set.add(tool.usage)

        search_list.extend(agent_info.managed_agents)
        export_agent_dict[str(agent_info.agent_id)] = agent_info

    # convert mcp info to MCPInfo list
    mcp_info_list = []
    for mcp_server_name in mcp_info_set:
        # get mcp url by mcp_server_name and tenant_id
        mcp_url = get_mcp_server_by_name_and_tenant(mcp_server_name, tenant_id)
        mcp_info_list.append(
            MCPInfo(mcp_server_name=mcp_server_name, mcp_url=mcp_url))

    export_data = ExportAndImportDataFormat(
        agent_id=agent_id, agent_info=export_agent_dict, mcp_info=mcp_info_list)
    return export_data.model_dump()


async def export_agent_by_agent_id(agent_id: int, tenant_id: str, user_id: str) -> ExportAndImportAgentInfo:
    """
    Export a single agent's information based on agent_id
    """
    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id)
    agent_relation_in_db = query_sub_agents_id_list(
        main_agent_id=agent_id, tenant_id=tenant_id)
    tool_list = await create_tool_config_list(agent_id=agent_id, tenant_id=tenant_id, user_id=user_id)

    # Check if any tool is KnowledgeBaseSearchTool and set its metadata to empty dict
    for tool in tool_list:
        if tool.class_name == "KnowledgeBaseSearchTool":
            tool.metadata = {}

    agent_info = ExportAndImportAgentInfo(agent_id=agent_id,
                                          name=agent_info["name"],
                                          display_name=agent_info["display_name"],
                                          description=agent_info["description"],
                                          business_description=agent_info["business_description"],
                                          model_name=agent_info["model_name"],
                                          max_steps=agent_info["max_steps"],
                                          provide_run_summary=agent_info["provide_run_summary"],
                                          duty_prompt=agent_info.get(
                                              "duty_prompt"),
                                          constraint_prompt=agent_info.get(
                                              "constraint_prompt"),
                                          few_shots_prompt=agent_info.get(
                                              "few_shots_prompt"),
                                          enabled=agent_info["enabled"],
                                          tools=tool_list,
                                          managed_agents=agent_relation_in_db)
    return agent_info


async def import_agent_impl(agent_info: ExportAndImportDataFormat, authorization: str = Header(None)):
    """
    Import agent using DFS
    """
    user_id, tenant_id, _ = get_current_user_info(authorization)
    agent_id = agent_info.agent_id

    # First, add MCP servers if any
    if agent_info.mcp_info:
        for mcp_info in agent_info.mcp_info:
            if mcp_info.mcp_server_name and mcp_info.mcp_url:
                try:
                    # Check if MCP name already exists
                    if check_mcp_name_exists(mcp_name=mcp_info.mcp_server_name, tenant_id=tenant_id):
                        # Get existing MCP server info to compare URLs
                        existing_mcp = get_mcp_server_by_name_and_tenant(mcp_name=mcp_info.mcp_server_name,
                                                                         tenant_id=tenant_id)
                        if existing_mcp and existing_mcp == mcp_info.mcp_url:
                            # Same name and URL, skip
                            logger.info(
                                f"MCP server {mcp_info.mcp_server_name} with same URL already exists, skipping")
                            continue
                        else:
                            # Same name but different URL, add import prefix
                            import_mcp_name = f"import_{mcp_info.mcp_server_name}"
                            logger.info(
                                f"MCP server {mcp_info.mcp_server_name} exists with different URL, using name: {import_mcp_name}")
                            mcp_server_name = import_mcp_name
                    else:
                        # Name doesn't exist, use original name
                        mcp_server_name = mcp_info.mcp_server_name

                    await add_remote_mcp_server_list(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        remote_mcp_server=mcp_info.mcp_url,
                        remote_mcp_server_name=mcp_server_name
                    )
                except Exception as e:
                    raise Exception(
                        f"Failed to add MCP server {mcp_info.mcp_server_name}: {str(e)}")

    # Then, update tool list to include new MCP tools
    try:
        await update_tool_list(tenant_id=tenant_id, user_id=user_id)
    except Exception as e:
        raise Exception(f"Failed to update tool list: {str(e)}")

    agent_stack = deque([agent_id])
    agent_id_set = set()
    mapping_agent_id = {}

    while len(agent_stack):
        need_import_agent_id = agent_stack.pop()
        if need_import_agent_id in agent_id_set:
            continue

        need_import_agent_info = agent_info.agent_info[str(
            need_import_agent_id)]
        managed_agents = need_import_agent_info.managed_agents

        if agent_id_set.issuperset(managed_agents):
            new_agent_id = await import_agent_by_agent_id(
                import_agent_info=agent_info.agent_info[str(
                    need_import_agent_id)],
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
    db_all_tool_info_dict = {
        f"{tool['class_name']}&{tool['source']}": tool for tool in tool_info}

    for tool in import_agent_info.tools:
        db_tool_info: dict | None = db_all_tool_info_dict.get(
            f"{tool.class_name}&{tool.source}", None)

        if db_tool_info is None:
            raise ValueError(
                f"Cannot find tool {tool.class_name} in {tool.source}.")

        db_tool_info_params = db_tool_info["params"]
        db_tool_info_params_name_set = set(
            [param_info["name"] for param_info in db_tool_info_params])

        for tool_param_name in tool.params:
            if tool_param_name not in db_tool_info_params_name_set:
                raise ValueError(
                    f"Parameter {tool_param_name} in tool {tool.class_name} from {tool.source} cannot be found.")

        tool_list.append(ToolInstanceInfoRequest(tool_id=db_tool_info['tool_id'],
                                                 agent_id=-1,
                                                 enabled=True,
                                                 params=tool.params))
    # check the validity of the agent parameters
    if import_agent_info.model_name not in ["main_model", "sub_model"]:
        raise ValueError(
            f"Invalid model name: {import_agent_info.model_name}. model name must be 'main_model' or 'sub_model'.")
    if import_agent_info.max_steps <= 0 or import_agent_info.max_steps > 20:
        raise ValueError(
            f"Invalid max steps: {import_agent_info.max_steps}. max steps must be greater than 0 and less than 20.")
    if not import_agent_info.name.isidentifier():
        raise ValueError(
            f"Invalid agent name: {import_agent_info.name}. agent name must be a valid python variable name.")
    # create a new agent
    new_agent = create_agent(agent_info={"name": import_agent_info.name,
                                         "display_name": import_agent_info.display_name,
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
        create_or_update_tool_by_tool_info(
            tool_info=tool, tenant_id=tenant_id, user_id=user_id)
    return new_agent_id


def load_default_agents_json_file(default_agent_path):
    # load all json files in the folder
    all_json_files = []
    agent_file_list = os.listdir(default_agent_path)
    for agent_file in agent_file_list:
        if agent_file.endswith(".json"):
            with open(os.path.join(default_agent_path, agent_file), "r", encoding="utf-8") as f:
                agent_json = json.load(f)

            export_agent_info = ExportAndImportAgentInfo.model_validate(
                agent_json)
            all_json_files.append(export_agent_info)
    return all_json_files


async def list_all_agent_info_impl(tenant_id: str) -> list[dict]:
    """
    list all agent info

    Args:
        tenant_id (str): tenant id

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
            if not agent["enabled"]:
                continue
            tool_info = search_tools_for_sub_agent(
                agent_id=agent["agent_id"], tenant_id=tenant_id)
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
                content={
                    "message": "There is a circular call in the agent", "status": "error"}
            )
        if left_ele in agent_id_set:
            continue
        else:
            agent_id_set.add(left_ele)
        sub_ids = query_sub_agents_id_list(
            main_agent_id=left_ele, tenant_id=tenant_id)
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
            content={"message": "Failed to insert relation", "status": "error"}
        )


# Helper function for run_agent_stream, used to prepare context for an agent run
async def prepare_agent_run(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str=LANGUAGE["ZH"],
    allow_memory_search: bool = True,
):
    """
    Prepare for an agent run by creating context and run info, and registering the run.
    """

    memory_context = build_memory_context(
        user_id, tenant_id, agent_request.agent_id)
    agent_run_info = await create_agent_run_info(
        agent_id=agent_request.agent_id,
        minio_files=agent_request.minio_files,
        query=agent_request.query,
        history=agent_request.history,
        tenant_id=tenant_id,
        user_id=user_id,
        language=language,
        allow_memory_search=allow_memory_search,
    )
    agent_run_manager.register_agent_run(
        agent_request.conversation_id, agent_run_info, user_id)
    return agent_run_info, memory_context


# Helper function for run_agent_stream, used to save messages for either user or assistant
def save_messages(agent_request, target: str, user_id: str, tenant_id: str, messages=None):
    if target == MESSAGE_ROLE["USER"]:
        if messages is not None:
            raise ValueError("Messages should be None when saving for user.")
        submit(save_conversation_user, agent_request, user_id, tenant_id)
    elif target == MESSAGE_ROLE["ASSISTANT"]:
        if messages is None:
            raise ValueError(
                "Messages cannot be None when saving for assistant.")
        submit(save_conversation_assistant,
               agent_request, messages, user_id, tenant_id)


# Helper function for run_agent_stream, used to generate stream response with memory preprocess tokens
async def generate_stream_with_memory(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
):
    # Prepare preprocess task tracking (simulate preprocess flow)
    task_id = str(uuid.uuid4())
    conversation_id = agent_request.conversation_id
    current_task = asyncio.current_task()
    if current_task:
        preprocess_manager.register_preprocess_task(
            task_id, conversation_id, current_task
        )

    # Helper to emit memory_search token
    def _memory_token(message_text: str) -> str:
        payload = {
            "type": "memory_search",
            "content": json.dumps({"message": message_text}, ensure_ascii=False),
        }
        return json.dumps(payload, ensure_ascii=False)

    # Placeholder messages handled by frontend for i18n
    msg_start = MEMORY_SEARCH_START_MSG
    msg_done = MEMORY_SEARCH_DONE_MSG
    msg_fail = MEMORY_SEARCH_FAIL_MSG

    # ------------------------------------------------------------------
    # Note: the actual streaming happens via `_stream_agent_chunks` helper
    # ------------------------------------------------------------------

    memory_enabled = False
    try:
        memory_context_preview = build_memory_context(
            user_id, tenant_id, agent_request.agent_id
        )
        memory_enabled = bool(memory_context_preview.user_config.memory_switch)

        if memory_enabled:
            # Emit start token before memory retrieval
            yield f"data: {_memory_token(msg_start)}\n\n"

        # Prepare run (will execute memory retrieval inside create_agent_run_info)
        try:
            agent_run_info, memory_context = await prepare_agent_run(
                agent_request=agent_request,
                user_id=user_id,
                tenant_id=tenant_id,
                language=language,
                allow_memory_search=True,
            )
        except Exception as prep_err:
            # Normalize any preparation error to MemoryPreparationException
            raise MemoryPreparationException(str(prep_err)) from prep_err

        if memory_enabled:
            # Emit completion token once memory is ready
            yield f"data: {_memory_token(msg_done)}\n\n"

        async for data_chunk in _stream_agent_chunks(
            agent_request=agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            agent_run_info=agent_run_info,
            memory_ctx=memory_context,
        ):
            yield data_chunk

    except MemoryPreparationException:
        # Memory retrieval failure: emit failure token when memory is enabled, and continue without blocking
        if memory_enabled:
            yield f"data: {_memory_token(msg_fail)}\n\n"

        try:
            # Fallback to the no-memory streaming path, which internally handles
            async for data_chunk in generate_stream_no_memory(
                agent_request,
                user_id=user_id,
                tenant_id=tenant_id,
            ):
                yield data_chunk
        except Exception as run_exc:
            logger.error(f"Agent run error after memory failure: {str(run_exc)}")
            # Emit an error chunk and terminate the stream immediately
            error_payload = json.dumps(
                {"type": "error", "content": str(run_exc)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"
            return
    except Exception as e:
        logger.error(f"Generate stream with memory error: {str(e)}")
        # Emit an error chunk and terminate the stream immediately
        error_payload = json.dumps(
            {"type": "error", "content": str(e)}, ensure_ascii=False)
        yield f"data: {error_payload}\n\n"
        return
    finally:
        # Always unregister preprocess task
        preprocess_manager.unregister_preprocess_task(task_id)


# Helper function for run_agent_stream, used when user memory is disabled (no memory tokens)
async def generate_stream_no_memory(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str=LANGUAGE["ZH"],
):
    """Stream agent responses without any memory preprocessing tokens or fallback logic."""

    # Prepare run info respecting memory disabled (honor provided user_id/tenant_id)
    agent_run_info, memory_context = await prepare_agent_run(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        allow_memory_search=False,
    )

    async for data_chunk in _stream_agent_chunks(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        agent_run_info=agent_run_info,
        memory_ctx=memory_context,
    ):
        yield data_chunk


async def run_agent_stream(
    agent_request: AgentRequest,
    http_request: Request,
    authorization: str,
    user_id: str = None,
    tenant_id: str = None,
    skip_user_save: bool = False,
):
    """
    Start an agent run and stream responses.
    If user_id or tenant_id is provided, authorization will be overridden. (Useful in northbound apis)
    """

    # Choose streaming strategy based on user's memory switch
    resolved_user_id, resolved_tenant_id, language = _resolve_user_tenant_language(
        authorization=authorization,
        http_request=http_request,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    
    # Save user message only if not in debug mode (before streaming starts)
    if not agent_request.is_debug and not skip_user_save:
        save_messages(
            agent_request,
            target=MESSAGE_ROLE["USER"],
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
        )
    
    memory_ctx_preview = build_memory_context(
        resolved_user_id, resolved_tenant_id, agent_request.agent_id
    )

    if memory_ctx_preview.user_config.memory_switch and not agent_request.is_debug:
        stream_gen = generate_stream_with_memory(
            agent_request,
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
            language=language,
        )
    else:
        stream_gen = generate_stream_no_memory(
            agent_request,
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
            language=language,
        )

    return StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def stop_agent_tasks(conversation_id: int, user_id: str):
    """
    Stop agent run and preprocess tasks for the specified conversation_id.
    Matches the behavior of agent_app.agent_stop_api.
    """
    # Stop agent run
    agent_stopped = agent_run_manager.stop_agent_run(conversation_id, user_id)

    # Stop preprocess tasks
    preprocess_stopped = preprocess_manager.stop_preprocess_tasks(
        conversation_id)

    if agent_stopped or preprocess_stopped:
        message_parts = []
        if agent_stopped:
            message_parts.append("agent run")
        if preprocess_stopped:
            message_parts.append("preprocess tasks")

        message = f"successfully stopped {' and '.join(message_parts)} for user_id {user_id}, conversation_id {conversation_id}"
        logging.info(message)
        return {"status": "success", "message": message}
    else:
        message = f"no running agent or preprocess tasks found for user_id {user_id}, conversation_id {conversation_id}"
        logging.error(message)
        return {"status": "error", "message": message}


async def get_agent_id_by_name(agent_name: str, tenant_id: str) -> int:
    """
    Resolve unique agent id by its unique name under the same tenant.
    """
    if not agent_name:
        raise Exception("agent_name required")
    try:
        return search_agent_id_by_agent_name(agent_name, tenant_id)
    except Exception as _:
        logger.error(
            f"Failed to find agent id with '{agent_name}' in tenant {tenant_id}")
        raise Exception("agent not found")


def delete_related_agent_impl(parent_agent_id: int, child_agent_id: int, tenant_id: str):
    """
    Delete the relationship between a parent agent and its child agent

    Args:
        parent_agent_id (int): The ID of the parent agent
        child_agent_id (int): The ID of the child agent to be removed from parent
        tenant_id (str): The tenant ID for data isolation

    Raises:
        ValueError: When deletion operation fails
    """
    try:
        return delete_related_agent(parent_agent_id, child_agent_id, tenant_id)
    except Exception as e:
        logger.error(f"Failed to delete related agent: {str(e)}")
        raise Exception(f"Failed to delete related agent: {str(e)}")


def get_agent_call_relationship_impl(agent_id: int, tenant_id: str) -> dict:
    """
    Get agent call relationship tree including tools and sub-agents

    Args:
        agent_id (int): agent id
        tenant_id (str): tenant id

    Returns:
        dict: agent call relationship tree structure
    """
    def _normalize_tool_type(source: str) -> str:
        """Normalize the source from database to the expected display type for testing."""
        if not source:
            return "UNKNOWN"
        s = str(source)
        ls = s.lower()
        if ls in TOOL_TYPE_MAPPING:
            return TOOL_TYPE_MAPPING[ls]
        # Unknown source: capitalize first letter, keep the rest unchanged (unknown_source -> Unknown_source)
        return s[:1].upper() + s[1:]

    try:

        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id)
        if not agent_info:
            raise ValueError(f"Agent {agent_id} not found")

        tool_info = search_tools_for_sub_agent(
            agent_id=agent_id, tenant_id=tenant_id)
        tools = []
        for tool in tool_info:
            tool_name = tool.get("name") or tool.get(
                "tool_name") or str(tool["tool_id"])
            tool_source = tool.get("source", ToolSourceEnum.LOCAL.value)
            tool_type = _normalize_tool_type(tool_source)

            tools.append({
                "tool_id": tool["tool_id"],
                "name": tool_name,
                "type": tool_type
            })

        def get_sub_agents_recursive(parent_agent_id: int, depth: int = 0, max_depth: int = 5) -> list:
            if depth >= max_depth:
                return []

            sub_agent_id_list = query_sub_agents_id_list(
                main_agent_id=parent_agent_id, tenant_id=tenant_id)
            sub_agents = []

            for sub_agent_id in sub_agent_id_list:
                try:
                    sub_agent_info = search_agent_info_by_agent_id(
                        sub_agent_id, tenant_id)
                    if sub_agent_info:

                        sub_tool_info = search_tools_for_sub_agent(
                            agent_id=sub_agent_id, tenant_id=tenant_id)
                        sub_tools = []
                        for tool in sub_tool_info:
                            tool_name = tool.get("name") or tool.get(
                                "tool_name") or str(tool["tool_id"])
                            tool_source = tool.get(
                                "source", ToolSourceEnum.LOCAL.value)
                            tool_type = _normalize_tool_type(tool_source)

                            sub_tools.append({
                                "tool_id": tool["tool_id"],
                                "name": tool_name,
                                "type": tool_type
                            })

                        deeper_sub_agents = get_sub_agents_recursive(
                            sub_agent_id, depth + 1, max_depth)

                        sub_agents.append({
                            "agent_id": str(sub_agent_id),
                            "name": sub_agent_info.get("display_name") or sub_agent_info.get("name",
                                                                                             f"Agent {sub_agent_id}"),
                            "tools": sub_tools,
                            "sub_agents": deeper_sub_agents,
                            "depth": depth + 1
                        })
                except Exception as e:
                    logger.warning(
                        f"Failed to get sub-agent {sub_agent_id} info: {str(e)}")
                    continue

            return sub_agents

        sub_agents = get_sub_agents_recursive(agent_id)

        return {
            "agent_id": str(agent_id),
            "name": agent_info.get("display_name") or agent_info.get("name", f"Agent {agent_id}"),
            "tools": tools,
            "sub_agents": sub_agents
        }

    except Exception as e:
        logger.exception(
            f"Failed to get agent call relationship for agent {agent_id}: {str(e)}")
        raise ValueError(f"Failed to get agent call relationship: {str(e)}")