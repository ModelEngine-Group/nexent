import asyncio
import json
import logging
import os
import uuid
from collections import deque
from typing import Callable, Optional, Dict

from fastapi import Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from nexent.core.agents.run_agent import agent_run
from nexent.memory.memory_service import clear_memory, add_memory_in_levels
from jinja2 import Template

from agents.agent_run_manager import agent_run_manager
from agents.create_agent_info import create_agent_run_info, create_tool_config_list
from agents.preprocess_manager import preprocess_manager
from services.agent_version_service import publish_version_impl
from consts.const import MEMORY_SEARCH_START_MSG, MEMORY_SEARCH_DONE_MSG, MEMORY_SEARCH_FAIL_MSG, TOOL_TYPE_MAPPING, \
    LANGUAGE, MESSAGE_ROLE, MODEL_CONFIG_MAPPING, CAN_EDIT_ALL_USER_ROLES, PERMISSION_EDIT, PERMISSION_READ
from consts.exceptions import MemoryPreparationException
from consts.model import (
    AgentInfoRequest,
    AgentRequest,
    AgentNameBatchCheckRequest,
    AgentNameBatchRegenerateRequest,
    ExportAndImportAgentInfo,
    ExportAndImportDataFormat,
    MCPInfo,
    ToolInstanceInfoRequest,
    ToolSourceEnum, ModelConnectStatusEnum
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
    update_agent,
    update_related_agents,
    clear_agent_new_mark
)
from database.model_management_db import get_model_by_model_id, get_model_id_by_display_name
from database.remote_mcp_db import get_mcp_server_by_name_and_tenant
from database.tool_db import (
    check_tool_is_available,
    create_or_update_tool_by_tool_info,
    delete_tools_by_agent_id,
    query_all_enabled_tool_instances,
    query_all_tools,
    query_tool_instances_by_id,
    query_tool_instances_by_agent_id,
    search_tools_for_sub_agent
)
from database.group_db import query_group_ids_by_user
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.str_utils import convert_list_to_string, convert_string_to_list
from services.conversation_management_service import save_conversation_assistant, save_conversation_user
from services.memory_config_service import build_memory_context
from utils.auth_utils import get_current_user_info, get_user_language
from utils.config_utils import tenant_config_manager
from utils.memory_utils import build_memory_config
from utils.thread_utils import submit
from utils.prompt_template_utils import get_prompt_generate_prompt_template
from utils.llm_utils import call_llm_for_system_prompt

# Import monitoring utilities
from utils.monitoring import monitoring_manager

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


def _get_user_group_ids(user_id: str, tenant_id: str) -> str:
    """
    Get user's group IDs as a comma-separated string.

    Args:
        user_id: User ID
        tenant_id: Tenant ID

    Returns:
        Comma-separated string of group IDs
    """
    try:
        group_ids = query_group_ids_by_user(user_id)
        return convert_list_to_string(group_ids)
    except Exception as e:
        logger.warning(
            f"Failed to get user groups for user {user_id}: {str(e)}")
        return ""


def _resolve_model_with_fallback(
    model_display_name: str | None,
    exported_model_id: str | None,
    model_label: str,
    tenant_id: str
) -> str | None:
    """
    Resolve model_id from model_display_name with fallback to quick config LLM model.

    Args:
        model_display_name: Display name of the model to lookup
        exported_model_id: Original model_id from export (for logging only)
        model_label: Label for logging (e.g., "Model", "Business logic model")
        tenant_id: Tenant ID for model lookup

    Returns:
        Resolved model_id or None if not found and no fallback available
    """
    if not model_display_name:
        return None

    # Try to find model by display name in current tenant
    resolved_id = get_model_id_by_display_name(model_display_name, tenant_id)

    if resolved_id:
        logger.info(
            f"{model_label} '{model_display_name}' found in tenant {tenant_id}, "
            f"mapped to model_id: {resolved_id} (exported model_id was: {exported_model_id})")
        return resolved_id

    # Model not found, try fallback to quick config LLM model
    logger.warning(
        f"{model_label} '{model_display_name}' (exported model_id: {exported_model_id}) "
        f"not found in tenant {tenant_id}, falling back to quick config LLM model.")

    quick_config_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id
    )

    if quick_config_model:
        fallback_id = quick_config_model.get("model_id")
        logger.info(
            f"Using quick config LLM model for {model_label.lower()}: "
            f"{quick_config_model.get('display_name')} (model_id: {fallback_id})")
        return fallback_id

    logger.warning(f"No quick config LLM model found for tenant {tenant_id}")
    return None


def _normalize_language_key(language: str) -> str:
    normalized = (language or "").lower()
    if normalized.startswith(LANGUAGE["ZH"]):
        return LANGUAGE["ZH"]
    return LANGUAGE["EN"]


def _render_prompt_template(template_str: str, **context) -> str:
    if not template_str:
        return ""
    try:
        return Template(template_str).render(**context).strip()
    except Exception as exc:
        logger.warning(f"Failed to render prompt template: {exc}")
        return template_str


def _format_existing_values(values: set[str], language: str) -> str:
    if not values:
        return "无" if _normalize_language_key(language) == LANGUAGE["ZH"] else "None"
    return ", ".join(sorted(values))


def _check_agent_value_duplicate(
    field_key: str,
    value: str,
    tenant_id: str,
    exclude_agent_id: int | None = None,
    agents_cache: list[dict] | None = None
) -> bool:
    if not value:
        return False
    if agents_cache is None:
        agents_cache = query_all_agent_info_by_tenant_id(tenant_id)
    for agent in agents_cache:
        if exclude_agent_id and agent.get("agent_id") == exclude_agent_id:
            continue
        if agent.get(field_key) == value:
            return True
    return False


def _check_agent_name_duplicate(
    name: str,
    tenant_id: str,
    exclude_agent_id: int | None = None,
    agents_cache: list[dict] | None = None
) -> bool:
    return _check_agent_value_duplicate(
        "name",
        name,
        tenant_id=tenant_id,
        exclude_agent_id=exclude_agent_id,
        agents_cache=agents_cache
    )


def _check_agent_display_name_duplicate(
    display_name: str,
    tenant_id: str,
    exclude_agent_id: int | None = None,
    agents_cache: list[dict] | None = None
) -> bool:
    return _check_agent_value_duplicate(
        "display_name",
        display_name,
        tenant_id=tenant_id,
        exclude_agent_id=exclude_agent_id,
        agents_cache=agents_cache
    )


def _generate_unique_value_with_suffix(
    base_value: str,
    *,
    tenant_id: str,
    duplicate_check_fn: Callable[..., bool],
    agents_cache: list[dict] | None = None,
    exclude_agent_id: int | None = None,
    max_suffix_attempts: int = 100
) -> str:
    counter = 1
    while counter <= max_suffix_attempts:
        candidate = f"{base_value}_{counter}"
        if not duplicate_check_fn(
            candidate,
            tenant_id=tenant_id,
            exclude_agent_id=exclude_agent_id,
            agents_cache=agents_cache
        ):
            return candidate
        counter += 1
    raise ValueError("Failed to generate unique value after max attempts")


def _generate_unique_agent_name_with_suffix(
    base_value: str,
    tenant_id: str,
    agents_cache: list[dict] | None = None,
    exclude_agent_id: int | None = None
) -> str:
    return _generate_unique_value_with_suffix(
        base_value,
        tenant_id=tenant_id,
        duplicate_check_fn=_check_agent_name_duplicate,
        agents_cache=agents_cache,
        exclude_agent_id=exclude_agent_id
    )


def _generate_unique_display_name_with_suffix(
    base_value: str,
    tenant_id: str,
    agents_cache: list[dict] | None = None,
    exclude_agent_id: int | None = None
) -> str:
    return _generate_unique_value_with_suffix(
        base_value,
        tenant_id=tenant_id,
        duplicate_check_fn=_check_agent_display_name_duplicate,
        agents_cache=agents_cache,
        exclude_agent_id=exclude_agent_id
    )


def _regenerate_agent_value_with_llm(
    *,
    original_value: str,
    existing_values: list[str],
    task_description: str,
    model_id: int,
    tenant_id: str,
    language: str,
    system_prompt_key: str,
    user_prompt_key: str,
    default_system_prompt: str,
    default_user_prompt_builder: Callable[[dict], str],
    fallback_fn: Callable[[str], str]
) -> str:
    """
    Shared helper to regenerate agent-related values with an LLM.
    """
    prompt_template = get_prompt_generate_prompt_template(language)
    system_prompt = _render_prompt_template(
        prompt_template.get(system_prompt_key, ""),
        original_value=original_value
    )
    user_prompt_template = prompt_template.get(user_prompt_key, "")

    value_set = {value for value in existing_values if value}
    context = {
        "task_description": task_description or "",
        "original_value": original_value,
        "existing_values": _format_existing_values(value_set, language)
    }
    user_prompt = _render_prompt_template(user_prompt_template, **context)

    if not system_prompt:
        system_prompt = default_system_prompt
    if not user_prompt:
        user_prompt = default_user_prompt_builder(context)

    max_attempts = 5
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            regenerated_value = call_llm_for_system_prompt(
                model_id=model_id,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                callback=None,
                tenant_id=tenant_id
            )
            candidate = (regenerated_value or "").strip().splitlines()[0].strip()
            if candidate in value_set:
                raise ValueError(f"Generated duplicate value '{candidate}'")
            return candidate
        except Exception as exc:
            last_error = exc
            logger.warning(
                f"Attempt {attempt}/{max_attempts} to regenerate value failed: {exc}"
            )

    logger.error(
        "Failed to regenerate agent value with LLM after maximum retries",
        exc_info=last_error
    )
    return fallback_fn(original_value)


def _regenerate_agent_name_with_llm(
    original_name: str,
    existing_names: list[str],
    task_description: str,
    model_id: int,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    agents_cache: list[dict] | None = None,
    exclude_agent_id: int | None = None
) -> str:
    return _regenerate_agent_value_with_llm(
        original_value=original_name,
        existing_values=existing_names,
        task_description=task_description,
        model_id=model_id,
        tenant_id=tenant_id,
        language=language,
        system_prompt_key="AGENT_NAME_REGENERATE_SYSTEM_PROMPT",
        user_prompt_key="AGENT_NAME_REGENERATE_USER_PROMPT",
        default_system_prompt=(
            "You refine agent variable names so that they stay close to the "
            "original meaning and remain unique within the tenant."
        ),
        default_user_prompt_builder=lambda ctx: (
            f"### Task Description:\n{ctx['task_description']}\n\n"
            f"### Original Name:\n{ctx['original_value']}\n\n"
            f"### Existing Names:\n{ctx['existing_values']}\n\n"
            "Generate a concise Python variable name that keeps the same "
            "meaning and does not duplicate the existing names. Return only "
            "the variable name."
        ),
        fallback_fn=lambda base_value: _generate_unique_agent_name_with_suffix(
            base_value,
            tenant_id=tenant_id,
            agents_cache=agents_cache,
            exclude_agent_id=exclude_agent_id
        )
    )



def _regenerate_agent_display_name_with_llm(
    original_display_name: str,
    existing_display_names: list[str],
    task_description: str,
    model_id: int,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    agents_cache: list[dict] | None = None,
    exclude_agent_id: int | None = None
) -> str:
    return _regenerate_agent_value_with_llm(
        original_value=original_display_name,
        existing_values=existing_display_names,
        task_description=task_description,
        model_id=model_id,
        tenant_id=tenant_id,
        language=language,
        system_prompt_key="AGENT_DISPLAY_NAME_REGENERATE_SYSTEM_PROMPT",
        user_prompt_key="AGENT_DISPLAY_NAME_REGENERATE_USER_PROMPT",
        default_system_prompt=(
            "You refine agent display names so they remain unique, concise, "
            "and aligned with the agent's capability."
        ),
        default_user_prompt_builder=lambda ctx: (
            f"### Task Description:\n{ctx['task_description']}\n\n"
            f"### Original Display Name:\n{ctx['original_value']}\n\n"
            f"### Existing Display Names:\n{ctx['existing_values']}\n\n"
            "Generate a new display name that keeps the same meaning but does "
            "not duplicate existing names. Return only the display name."
        ),
        fallback_fn=lambda base_value: _generate_unique_display_name_with_suffix(
            base_value,
            tenant_id=tenant_id,
            agents_cache=agents_cache,
            exclude_agent_id=exclude_agent_id
        )
    )



async def check_agent_name_conflict_batch_impl(
    request: AgentNameBatchCheckRequest,
    authorization: str
) -> list[dict]:
    """
    Batch check name/display_name duplication for multiple agents.
    """
    _, tenant_id, _ = get_current_user_info(authorization)
    agents_cache = query_all_agent_info_by_tenant_id(tenant_id)

    results: list[dict] = []
    for item in request.items:
        if not item.name:
            results.append({
                "name_conflict": False,
                "display_name_conflict": False,
                "conflict_agents": []
            })
            continue

        conflicts: list[dict] = []
        name_conflict = False
        display_name_conflict = False
        for agent in agents_cache:
            if item.agent_id and agent.get("agent_id") == item.agent_id:
                continue
            matches_name = item.name and agent.get("name") == item.name
            matches_display = item.display_name and agent.get(
                "display_name") == item.display_name
            if matches_name:
                name_conflict = True
            if matches_display:
                display_name_conflict = True
            if matches_name or matches_display:
                conflicts.append({
                    "name": agent.get("name"),
                    "display_name": agent.get("display_name"),
                })

        results.append({
            "name_conflict": name_conflict,
            "display_name_conflict": display_name_conflict,
            "conflict_agents": conflicts
        })
    return results


async def regenerate_agent_name_batch_impl(
    request: AgentNameBatchRegenerateRequest,
    authorization: str
) -> list[dict]:
    """
    Batch regenerate agent name/display_name with LLM (or suffix fallback).
    """
    _, tenant_id, _ = get_current_user_info(authorization)
    agents_cache = query_all_agent_info_by_tenant_id(tenant_id)

    existing_names = [agent.get("name") for agent in agents_cache if agent.get("name")]
    existing_display_names = [agent.get("display_name") for agent in agents_cache if agent.get("display_name")]

    # Always use tenant quick-config LLM model
    quick_config_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id
    )
    resolved_model_id = quick_config_model.get("model_id") if quick_config_model else None
    if not resolved_model_id:
        raise ValueError("No available model for regeneration. Please configure an LLM model first.")

    results: list[dict] = []
    # Use local mutable caches to avoid regenerated duplicates in the same batch
    name_set = set(existing_names)
    display_name_set = set(existing_display_names)

    for item in request.items:
        agent_name = item.name or ""
        agent_display_name = item.display_name or ""
        task_description = item.task_description or ""
        exclude_agent_id = item.agent_id

        # Regenerate name if duplicate and non-empty
        if agent_name and _check_agent_name_duplicate(
            agent_name, tenant_id, agents_cache=agents_cache, exclude_agent_id=exclude_agent_id
        ):
            try:
                agent_name = await asyncio.to_thread(
                    _regenerate_agent_name_with_llm,
                    original_name=agent_name,
                    existing_names=list(name_set),
                    task_description=task_description,
                    model_id=resolved_model_id,
                    tenant_id=tenant_id,
                    language=LANGUAGE["ZH"],
                    agents_cache=agents_cache,
                    exclude_agent_id=exclude_agent_id
                )
            except Exception as e:
                logger.error(f"Failed to regenerate agent name with LLM: {str(e)}, using fallback")
                agent_name = _generate_unique_agent_name_with_suffix(
                    agent_name,
                    tenant_id=tenant_id,
                    agents_cache=agents_cache,
                    exclude_agent_id=exclude_agent_id
                )

        # Regenerate display_name if duplicate and non-empty
        if agent_display_name and _check_agent_display_name_duplicate(
            agent_display_name, tenant_id, agents_cache=agents_cache, exclude_agent_id=exclude_agent_id
        ):
            try:
                agent_display_name = await asyncio.to_thread(
                    _regenerate_agent_display_name_with_llm,
                    original_display_name=agent_display_name,
                    existing_display_names=list(display_name_set),
                    task_description=task_description,
                    model_id=resolved_model_id,
                    tenant_id=tenant_id,
                    language=LANGUAGE["ZH"],
                    agents_cache=agents_cache,
                    exclude_agent_id=exclude_agent_id
                )
            except Exception as e:
                logger.error(f"Failed to regenerate agent display_name with LLM: {str(e)}, using fallback")
                agent_display_name = _generate_unique_display_name_with_suffix(
                    agent_display_name,
                    tenant_id=tenant_id,
                    agents_cache=agents_cache,
                    exclude_agent_id=exclude_agent_id
                )

        # Track regenerated names to avoid duplicates within batch
        if agent_name:
            name_set.add(agent_name)
        if agent_display_name:
            display_name_set.add(agent_display_name)

        results.append({
            "name": agent_name,
            "display_name": agent_display_name
        })

    return results


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
        agent_run_manager.unregister_agent_run(
            agent_request.conversation_id, user_id)

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
                    {"role": MESSAGE_ROLE["USER"],
                        "content": agent_run_info.query},
                    {"role": MESSAGE_ROLE["ASSISTANT"],
                        "content": final_answer_local},
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
            # Create and store the background task to avoid warnings
            background_task = asyncio.create_task(_add_memory_background())
            # Add done callback to handle any exceptions that might occur
            background_task.add_done_callback(lambda t: t.exception() if t.exception() else None)
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


async def get_agent_info_impl(agent_id: int, tenant_id: str, version_no: int = 0):
    try:
        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id, version_no)
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

    if agent_info["model_id"] is not None:
        model_info = get_model_by_model_id(agent_info["model_id"])
        agent_info["model_name"] = model_info.get("display_name", None) if model_info is not None else None
    else:
        agent_info["model_name"] = None

    # Get business logic model display name from model_id
    if agent_info.get("business_logic_model_id") is not None:
        business_logic_model_info = get_model_by_model_id(agent_info["business_logic_model_id"])
        agent_info["business_logic_model_name"] = business_logic_model_info.get("display_name", None) if business_logic_model_info is not None else None
    elif "business_logic_model_name" not in agent_info:
        agent_info["business_logic_model_name"] = None

    if agent_info.get("group_ids") is not None:
        agent_info["group_ids"] = convert_string_to_list(agent_info.get("group_ids"))

    # Check agent availability
    is_available, unavailable_reasons = check_agent_availability(
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_info=agent_info
    )
    agent_info["is_available"] = is_available
    agent_info["unavailable_reasons"] = unavailable_reasons

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
            "model_id": agent_info.get("model_id"),
            "max_steps": agent_info["max_steps"],
            "business_description": agent_info["business_description"],
            "duty_prompt": agent_info.get("duty_prompt"),
            "constraint_prompt": agent_info.get("constraint_prompt"),
            "few_shots_prompt": agent_info.get("few_shots_prompt"),
            "sub_agent_id_list": query_sub_agents_id_list(main_agent_id=sub_agent_id, tenant_id=tenant_id)}


async def update_agent_info_impl(request: AgentInfoRequest, authorization: str = Header(None)):
    user_id, tenant_id, _ = get_current_user_info(authorization)

    # If agent_id is None, create a new agent; otherwise, update existing
    agent_id: Optional[int] = request.agent_id
    try:
        if agent_id is None:
            # Create agent - automatically set group_ids to current user's groups
            user_group_ids = _get_user_group_ids(user_id, tenant_id)
            created = create_agent(agent_info={
                "name": request.name,
                "display_name": request.display_name,
                "description": request.description,
                "business_description": request.business_description,
                "author": request.author,
                "model_id": request.model_id,
                "model_name": request.model_name,
                "business_logic_model_id": request.business_logic_model_id,
                "business_logic_model_name": request.business_logic_model_name,
                "max_steps": request.max_steps,
                "provide_run_summary": request.provide_run_summary,
                "duty_prompt": request.duty_prompt,
                "constraint_prompt": request.constraint_prompt,
                "few_shots_prompt": request.few_shots_prompt,
                "enabled": request.enabled if request.enabled is not None else True,
                "group_ids": convert_list_to_string(request.group_ids) if request.group_ids else user_group_ids
            }, tenant_id=tenant_id, user_id=user_id)
            agent_id = created["agent_id"]
        else:
            # Update agent
            update_agent(agent_id, request, user_id)
    except Exception as e:
        logger.error(f"Failed to update agent info: {str(e)}")
        raise ValueError(f"Failed to update agent info: {str(e)}")

    # Handle enabled tools saving when provided
    try:
        if request.enabled_tool_ids is not None and agent_id is not None:
            enabled_set = set(request.enabled_tool_ids)
            # Query existing tool instances for this agent
            existing_instances = query_tool_instances_by_agent_id(
                agent_id, tenant_id)

            # Handle unselected tool（already exist instance）→ enabled=False
            for instance in existing_instances:
                inst_tool_id = instance.get("tool_id")
                if inst_tool_id is not None and inst_tool_id not in enabled_set:
                    create_or_update_tool_by_tool_info(
                        tool_info=ToolInstanceInfoRequest(
                            tool_id=inst_tool_id,
                            agent_id=agent_id,
                            params=instance.get("params", {}),
                            enabled=False
                        ),
                        tenant_id=tenant_id,
                        user_id=user_id
                    )

            # Handle selected tool → enabled=True（create or update）
            for tool_id in enabled_set:
                # Keep existing params if any
                existing_instance = next(
                    (inst for inst in existing_instances
                     if inst.get("tool_id") == tool_id),
                    None
                )
                params = (existing_instance or {}).get("params", {})
                create_or_update_tool_by_tool_info(
                    tool_info=ToolInstanceInfoRequest(
                        tool_id=tool_id,
                        agent_id=agent_id,
                        params=params,
                        enabled=True,
                    ),
                    tenant_id=tenant_id,
                    user_id=user_id
                )
    except Exception as e:
        logger.error(f"Failed to update agent tools: {str(e)}")
        raise ValueError(f"Failed to update agent tools: {str(e)}")

    # Handle related agents saving when provided
    try:
        if request.related_agent_ids is not None and agent_id is not None:
            related_agent_ids = request.related_agent_ids
            # Check for circular dependencies using BFS
            search_list = deque(related_agent_ids)
            agent_id_set = set()

            while len(search_list):
                left_ele = search_list.popleft()
                if left_ele == agent_id:
                    raise ValueError("Circular dependency detected: Agent cannot be related to itself or create circular calls")
                if left_ele in agent_id_set:
                    continue
                else:
                    agent_id_set.add(left_ele)
                sub_ids = query_sub_agents_id_list(
                    main_agent_id=left_ele, tenant_id=tenant_id)
                search_list.extend(sub_ids)

            # Update related agents
            update_related_agents(
                parent_agent_id=agent_id,
                related_agent_ids=related_agent_ids,
                tenant_id=tenant_id,
                user_id=user_id
            )
    except ValueError as e:
        # Re-raise ValueError (circular dependency) as-is
        raise
    except Exception as e:
        logger.error(f"Failed to update related agents: {str(e)}")
        raise ValueError(f"Failed to update related agents: {str(e)}")

    return {"agent_id": agent_id}


async def delete_agent_impl(agent_id: int, tenant_id: str, user_id: str):
    """
    Delete an agent and all related data.

    Args:
        agent_id: Agent ID to delete
        tenant_id: Tenant ID
        user_id: User ID performing the deletion
    """
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
        if tool.class_name in ["KnowledgeBaseSearchTool", "AnalyzeTextFileTool", "AnalyzeImageTool", "DataMateSearchTool"]:
            tool.metadata = {}

    # Get model_id and model display name from agent_info
    model_id = agent_info.get("model_id")
    model_display_name = None
    if model_id is not None:
        model_info = get_model_by_model_id(model_id)
        model_display_name = model_info.get("display_name") if model_info is not None else None

    # Get business_logic_model_id and business logic model display name
    business_logic_model_id = agent_info.get("business_logic_model_id")
    business_logic_model_display_name = None
    if business_logic_model_id is not None:
        business_logic_model_info = get_model_by_model_id(business_logic_model_id)
        business_logic_model_display_name = business_logic_model_info.get("display_name") if business_logic_model_info is not None else None

    agent_info = ExportAndImportAgentInfo(agent_id=agent_id,
                                          name=agent_info["name"],
                                          display_name=agent_info["display_name"],
                                          description=agent_info["description"],
                                          business_description=agent_info["business_description"],
                                          author=agent_info.get("author"),
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
                                          managed_agents=agent_relation_in_db,
                                          model_id=model_id,
                                          model_name=model_display_name,
                                          business_logic_model_id=business_logic_model_id,
                                          business_logic_model_name=business_logic_model_display_name)
    return agent_info


async def import_agent_impl(
    agent_info: ExportAndImportDataFormat,
    authorization: str = Header(None),
    force_import: bool = False
):
    """
    Import agent using DFS.

    Note:
        MCP server registration and tool list refresh are now handled
        on the frontend / dedicated MCP configuration flows.
        The backend import logic only consumes the tools that already
        exist for the current tenant.
    """
    user_id, tenant_id, _ = get_current_user_info(authorization)
    agent_id = agent_info.agent_id

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
                user_id=user_id,
                skip_duplicate_regeneration=force_import
            )
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

    # Return the mapping of original IDs to new IDs
    return mapping_agent_id


async def import_agent_by_agent_id(
    import_agent_info: ExportAndImportAgentInfo,
    tenant_id: str,
    user_id: str,
    skip_duplicate_regeneration: bool = False
):
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
    if import_agent_info.max_steps <= 0 or import_agent_info.max_steps > 20:
        raise ValueError(
            f"Invalid max steps: {import_agent_info.max_steps}. max steps must be greater than 0 and less than 20.")
    if not import_agent_info.name.isidentifier():
        raise ValueError(
            f"Invalid agent name: {import_agent_info.name}. agent name must be a valid python variable name.")

    # Resolve model IDs with fallback
    # Note: We use model_display_name for cross-tenant compatibility
    # The exported model_id is kept for reference/debugging only
    model_id = _resolve_model_with_fallback(
        model_display_name=import_agent_info.model_name,
        exported_model_id=import_agent_info.model_id,
        model_label="Model",
        tenant_id=tenant_id
    )

    business_logic_model_id = _resolve_model_with_fallback(
        model_display_name=import_agent_info.business_logic_model_name,
        exported_model_id=import_agent_info.business_logic_model_id,
        model_label="Business logic model",
        tenant_id=tenant_id
    )

    agent_name = import_agent_info.name
    agent_display_name = import_agent_info.display_name

    # create a new agent - use current user's groups instead of imported group_ids
    user_group_ids = _get_user_group_ids(user_id, tenant_id)
    new_agent = create_agent(agent_info={"name": agent_name,
                                         "display_name": agent_display_name,
                                         "description": import_agent_info.description,
                                         "business_description": import_agent_info.business_description,
                                         "author": import_agent_info.author,
                                         "model_id": model_id,
                                         "model_name": import_agent_info.model_name,
                                         "business_logic_model_id": business_logic_model_id,
                                         "business_logic_model_name": import_agent_info.business_logic_model_name,
                                         "max_steps": import_agent_info.max_steps,
                                         "provide_run_summary": import_agent_info.provide_run_summary,
                                         "duty_prompt": import_agent_info.duty_prompt,
                                         "constraint_prompt": import_agent_info.constraint_prompt,
                                         "few_shots_prompt": import_agent_info.few_shots_prompt,
                                         "enabled": import_agent_info.enabled,
                                         "group_ids": user_group_ids},
                             tenant_id=tenant_id,
                             user_id=user_id)
    new_agent_id = new_agent["agent_id"]
    # create tool_instance
    for tool in tool_list:
        tool.agent_id = new_agent_id
        create_or_update_tool_by_tool_info(
            tool_info=tool, tenant_id=tenant_id, user_id=user_id)
    # Auto-publish initial version v1 for market-imported agents
    try:
        publish_version_impl(
            agent_id=new_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_name="v1",
            release_note="Initial version from Agent Market"
        )
    except Exception as e:
        logger.warning(f"Failed to auto-publish version v1 for agent {new_agent_id}: {str(e)}")
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


async def clear_agent_new_mark_impl(agent_id: int, tenant_id: str, user_id: str):
    """
    Clear the NEW mark for an agent

    Args:
        agent_id (int): Agent ID
        tenant_id (str): Tenant ID
        user_id (str): User ID (for audit purposes)
    """
    rowcount = clear_agent_new_mark(agent_id, tenant_id, user_id)
    logger.info(f"clear_agent_new_mark_impl called for agent_id={agent_id}, tenant_id={tenant_id}, user_id={user_id}, affected_rows={rowcount}")
    return rowcount




async def list_all_agent_info_impl(tenant_id: str, user_id: str) -> list[dict]:
    """
    list all agent info

    Args:
        tenant_id (str): tenant id
        user_id (str): user id (used for permission calculation and filtering)

    Raises:
        ValueError: failed to query all agent info

    Returns:
        list: list of agent info
    """
    try:
        user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant_record.get("user_role") or "").upper()

        can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

        # For DEV/USER, restrict visible agents to those whose group_ids overlap user's groups.
        user_group_ids: set[int] = set()
        if not can_edit_all:
            try:
                user_group_ids = set(query_group_ids_by_user(user_id) or [])
            except Exception as e:
                logger.warning(
                    f"Failed to query user group ids for filtering: user_id={user_id}, err={str(e)}"
                )
                user_group_ids = set()

        agent_list = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)

        model_cache: Dict[int, Optional[dict]] = {}
        enriched_agents: list[dict] = []

        for agent in agent_list:
            if not agent["enabled"]:
                continue

            # Apply visibility filter for DEV/USER based on group overlap
            if not can_edit_all:
                agent_group_ids = set(convert_string_to_list(agent.get("group_ids")))
                if len(user_group_ids.intersection(agent_group_ids)) == 0:
                    continue

            # Use shared availability check function
            _, unavailable_reasons = check_agent_availability(
                agent_id=agent["agent_id"],
                tenant_id=tenant_id,
                agent_info=agent,
                model_cache=model_cache
            )

            # Preserve the raw data so we can adjust availability for duplicates
            enriched_agents.append({
                "raw_agent": agent,
                "unavailable_reasons": unavailable_reasons,
            })

        # Handle duplicate name/display_name: keep the earliest created agent available,
        # mark later ones as unavailable due to duplication.
        _apply_duplicate_name_availability_rules(enriched_agents)

        simple_agent_list: list[dict] = []
        for entry in enriched_agents:
            agent = entry["raw_agent"]
            unavailable_reasons = list(dict.fromkeys(entry["unavailable_reasons"]))

            model_id = agent.get("model_id")
            model_info = None
            if model_id is not None:
                if model_id not in model_cache:
                    model_cache[model_id] = get_model_by_model_id(model_id, tenant_id)
                model_info = model_cache.get(model_id)

            permission = PERMISSION_EDIT if can_edit_all or str(agent.get("created_by")) == str(user_id) else PERMISSION_READ

            simple_agent_list.append({
                "agent_id": agent["agent_id"],
                "name": agent["name"] if agent["name"] else agent["display_name"],
                "display_name": agent["display_name"] if agent["display_name"] else agent["name"],
                "description": agent["description"],
                "author": agent.get("author"),
                "model_id": model_id,
                "model_name": model_info.get("model_name") if model_info is not None else agent.get("model_name"),
                "model_display_name": model_info.get("display_name") if model_info is not None else None,
                "is_available": len(unavailable_reasons) == 0,
                "unavailable_reasons": unavailable_reasons,
                "is_new": agent.get("is_new", False),
                "group_ids": convert_string_to_list(agent.get("group_ids")),
                "permission": permission,
                "is_published": agent.get("current_version_no") is not None,
            })

        return simple_agent_list
    except Exception as e:
        logger.error(f"Failed to query all agent info: {str(e)}")
        raise ValueError(f"Failed to query all agent info: {str(e)}")


def _apply_duplicate_name_availability_rules(enriched_agents: list[dict]) -> None:
    """
    For agents that share the same name or display_name, only the earliest created
    agent should remain available (if it has no other unavailable reasons).
    All later-created agents in the same group become unavailable due to duplication.
    """
    # Group by name and display_name
    name_groups: dict[str, list[dict]] = {}
    display_name_groups: dict[str, list[dict]] = {}

    for entry in enriched_agents:
        agent = entry["raw_agent"]
        name = agent.get("name")
        if name:
            name_groups.setdefault(name, []).append(entry)

        display_name = agent.get("display_name")
        if display_name:
            display_name_groups.setdefault(display_name, []).append(entry)

    def _mark_duplicates(groups: dict[str, list[dict]], reason_key: str) -> None:
        for entries in groups.values():
            if len(entries) <= 1:
                continue

            # Sort by create_time ascending so the earliest created agent comes first
            sorted_entries = sorted(
                entries,
                key=lambda e: e["raw_agent"].get("create_time"),
            )

            # The first (earliest) agent keeps its current availability;
            # subsequent agents are marked as duplicates.
            for duplicate_entry in sorted_entries[1:]:
                duplicate_entry["unavailable_reasons"].append(reason_key)

    _mark_duplicates(name_groups, "duplicate_name")
    _mark_duplicates(display_name_groups, "duplicate_display_name")


def _collect_model_availability_reasons(agent: dict, tenant_id: str, model_cache: Dict[int, Optional[dict]]) -> list[str]:
    """
    Build a list of reasons related to model availability issues for a given agent.
    """
    reasons: list[str] = []
    reasons.extend(_check_single_model_availability(
        model_id=agent.get("model_id"),
        tenant_id=tenant_id,
        model_cache=model_cache,
        reason_key="model_unavailable"
    ))

    return reasons


def _check_single_model_availability(
    model_id: int | None,
    tenant_id: str,
    model_cache: Dict[int, Optional[dict]],
    reason_key: str,
) -> list[str]:
    if not model_id:
        return []

    if model_id not in model_cache:
        model_cache[model_id] = get_model_by_model_id(model_id, tenant_id)

    model_info = model_cache.get(model_id)
    if not model_info:
        return [reason_key]

    connect_status = ModelConnectStatusEnum.get_value(
        model_info.get("connect_status"))
    if connect_status != ModelConnectStatusEnum.AVAILABLE.value:
        return [reason_key]

    return []


def check_agent_availability(
    agent_id: int,
    tenant_id: str,
    agent_info: dict | None = None,
    model_cache: Dict[int, Optional[dict]] | None = None
) -> tuple[bool, list[str]]:
    """
    Check if an agent is available based on its tools and model configuration.

    Args:
        agent_id: The agent ID to check
        tenant_id: The tenant ID
        agent_info: Optional pre-fetched agent info (to avoid duplicate DB queries)
        model_cache: Optional model cache for performance optimization

    Returns:
        tuple: (is_available: bool, unavailable_reasons: list[str])
    """
    unavailable_reasons: list[str] = []

    if model_cache is None:
        model_cache = {}

    # Fetch agent info if not provided
    if agent_info is None:
        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id)

    if not agent_info:
        return False, ["agent_not_found"]

    # Check tool availability
    tool_info = search_tools_for_sub_agent(agent_id=agent_id, tenant_id=tenant_id)
    tool_id_list = [tool["tool_id"] for tool in tool_info if tool.get("tool_id") is not None]
    if tool_id_list:
        tool_statuses = check_tool_is_available(tool_id_list)
        if not all(tool_statuses):
            unavailable_reasons.append("tool_unavailable")

    # Check model availability
    model_reasons = _collect_model_availability_reasons(
        agent=agent_info,
        tenant_id=tenant_id,
        model_cache=model_cache
    )
    unavailable_reasons.extend(model_reasons)

    is_available = len(unavailable_reasons) == 0
    return is_available, unavailable_reasons


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
    language: str = LANGUAGE["ZH"],
    allow_memory_search: bool = True,
):
    """
    Prepare for an agent run by creating context and run info, and registering the run.
    """

    memory_context = build_memory_context(
        user_id, tenant_id, agent_request.agent_id, skip_query=not allow_memory_search)
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
            logger.error(
                f"Agent run error after memory failure: {str(run_exc)}")
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
@monitoring_manager.monitor_endpoint("agent_service.generate_stream_no_memory", exclude_params=["authorization"])
async def generate_stream_no_memory(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
):
    """Stream agent responses without any memory preprocessing tokens or fallback logic."""

    # Prepare run info respecting memory disabled (honor provided user_id/tenant_id)
    monitoring_manager.add_span_event("generate_stream_no_memory.started")
    agent_run_info, memory_context = await prepare_agent_run(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        allow_memory_search=False,
    )
    monitoring_manager.add_span_event("generate_stream_no_memory.completed")

    monitoring_manager.add_span_event(
        "generate_stream_no_memory.streaming.started")
    async for data_chunk in _stream_agent_chunks(
        agent_request=agent_request,
        user_id=user_id,
        tenant_id=tenant_id,
        agent_run_info=agent_run_info,
        memory_ctx=memory_context,
    ):
        yield data_chunk
    monitoring_manager.add_span_event(
        "generate_stream_no_memory.streaming.completed")


@monitoring_manager.monitor_endpoint("agent_service.run_agent_stream", exclude_params=["authorization"])
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
    import time

    # Add initial span attributes for tracking
    monitoring_manager.set_span_attributes(
        agent_id=agent_request.agent_id,
        conversation_id=agent_request.conversation_id,
        is_debug=agent_request.is_debug,
        skip_user_save=skip_user_save,
        has_override_user_id=user_id is not None,
        has_override_tenant_id=tenant_id is not None,
        query_length=len(agent_request.query) if agent_request.query else 0,
        history_count=len(
            agent_request.history) if agent_request.history else 0,
        minio_files_count=len(
            agent_request.minio_files) if agent_request.minio_files else 0
    )

    # Step 1: Resolve user tenant language
    resolve_start_time = time.time()
    monitoring_manager.add_span_event("user_resolution.started")

    resolved_user_id, resolved_tenant_id, language = _resolve_user_tenant_language(
        authorization=authorization,
        http_request=http_request,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    resolve_duration = time.time() - resolve_start_time
    monitoring_manager.add_span_event("user_resolution.completed", {
        "duration": resolve_duration,
        "user_id": resolved_user_id,
        "tenant_id": resolved_tenant_id,
        "language": language
    })
    monitoring_manager.set_span_attributes(
        resolved_user_id=resolved_user_id,
        resolved_tenant_id=resolved_tenant_id,
        language=language,
        user_resolution_duration=resolve_duration
    )

    # Step 2: Save user message (if needed)
    if not agent_request.is_debug and not skip_user_save:
        save_start_time = time.time()
        monitoring_manager.add_span_event("user_message_save.started")

        save_messages(
            agent_request,
            target=MESSAGE_ROLE["USER"],
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
        )

        save_duration = time.time() - save_start_time
        monitoring_manager.add_span_event("user_message_save.completed", {
            "duration": save_duration
        })
        monitoring_manager.set_span_attributes(
            user_message_saved=True,
            user_message_save_duration=save_duration
        )
    else:
        monitoring_manager.add_span_event("user_message_save.skipped", {
            "reason": "debug_mode" if agent_request.is_debug else "skip_user_save_flag"
        })
        monitoring_manager.set_span_attributes(user_message_saved=False)

    # Step 3: Build memory context (skip for debug mode)
    memory_start_time = time.time()
    monitoring_manager.add_span_event("memory_context_build.started")

    memory_ctx_preview = build_memory_context(
        resolved_user_id, resolved_tenant_id, agent_request.agent_id, skip_query=agent_request.is_debug
    )

    memory_duration = time.time() - memory_start_time
    memory_enabled = memory_ctx_preview.user_config.memory_switch
    monitoring_manager.add_span_event("memory_context_build.completed", {
        "duration": memory_duration,
        "memory_enabled": memory_enabled,
        "agent_share_option": getattr(memory_ctx_preview.user_config, "agent_share_option", "unknown"),
        "debug_mode": agent_request.is_debug
    })
    monitoring_manager.set_span_attributes(
        memory_enabled=memory_enabled,
        memory_context_build_duration=memory_duration,
        agent_share_option=getattr(
            memory_ctx_preview.user_config, "agent_share_option", "unknown")
    )

    # Step 4: Choose streaming strategy
    strategy_start_time = time.time()
    use_memory_stream = memory_enabled and not agent_request.is_debug

    monitoring_manager.add_span_event("streaming_strategy.selected", {
        "strategy": "with_memory" if use_memory_stream else "no_memory",
        "memory_enabled": memory_enabled,
        "is_debug": agent_request.is_debug
    })

    if use_memory_stream:
        monitoring_manager.add_span_event(
            "stream_generator.memory_stream.creating")
        stream_gen = generate_stream_with_memory(
            agent_request,
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
            language=language,
        )
    else:
        monitoring_manager.add_span_event(
            "stream_generator.no_memory_stream.creating")
        stream_gen = generate_stream_no_memory(
            agent_request,
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
            language=language,
        )

    strategy_duration = time.time() - strategy_start_time
    monitoring_manager.add_span_event("streaming_strategy.completed", {
        "duration": strategy_duration,
        "selected_strategy": "with_memory" if use_memory_stream else "no_memory"
    })
    monitoring_manager.set_span_attributes(
        streaming_strategy=(
            "with_memory" if use_memory_stream else "no_memory"),
        strategy_selection_duration=strategy_duration
    )

    # Step 5: Create streaming response
    response_start_time = time.time()
    monitoring_manager.add_span_event("streaming_response.creating")

    response = StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

    response_duration = time.time() - response_start_time
    monitoring_manager.add_span_event("streaming_response.created", {
        "duration": response_duration,
        "media_type": "text/event-stream"
    })
    monitoring_manager.set_span_attributes(
        response_creation_duration=response_duration,
        total_preparation_duration=(time.time() - resolve_start_time)
    )

    monitoring_manager.add_span_event("run_agent_stream.preparation_completed", {
        "total_preparation_time": time.time() - resolve_start_time
    })

    return response


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
