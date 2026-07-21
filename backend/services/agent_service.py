import asyncio
import base64
from http import HTTPStatus
import io
import json
import logging
import os
import uuid
import zipfile
from collections import deque
from typing import Any, Callable, Optional, Dict, List

from fastapi import Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from nexent.core.agents.run_agent import agent_run
from nexent.memory.memory_service import clear_memory, add_memory_in_levels
from jinja2 import Template

from agents.agent_run_manager import agent_run_manager
from agents.create_agent_info import create_agent_run_info, create_tool_config_list
from agents.preprocess_manager import preprocess_manager
from services.agent_version_service import publish_version_impl
from utils.prompt_template_utils import normalize_prompt_generate_template_content
from consts.const import MEMORY_SEARCH_START_MSG, MEMORY_SEARCH_DONE_MSG, MEMORY_SEARCH_FAIL_MSG, TOOL_TYPE_MAPPING, \
    LANGUAGE, MESSAGE_ROLE, MODEL_CONFIG_MAPPING, CAN_EDIT_ALL_USER_ROLES, PERMISSION_PRIVATE, STREAM_STATUS_EVENT, \
    DEFAULT_EN_TITLE, DEFAULT_ZH_TITLE, RUNTIME_CANCEL_POLL_INTERVAL_SECONDS
from consts.exceptions import AppException, MemoryPreparationException, SkillDuplicateError
from consts.error_code import ErrorCode
from consts.agent_unavailable_reasons import AgentUnavailableReason
from nexent.core.utils.observer import ProcessType
from consts.model import (
    AgentInfoRequest,
    AgentRequest,
    AgentNameBatchCheckRequest,
    AgentNameBatchRegenerateRequest,
    ExportAndImportAgentInfo,
    ExportAndImportDataFormat,
    MCPInfo,
    MessageRequest,
    MessageUnit,
    SkillInstanceInfoRequest,
    SkillZipEntry,
    ToolInstanceInfoRequest,
    ToolSourceEnum, ModelConnectStatusEnum,
    TurnResourceInvocationRequest,
)
from services.asset_owner_visibility import resolve_agent_list_permission
from database.agent_db import (
    create_agent,
    delete_agent_by_id,
    delete_agent_relationship,
    delete_related_agent,
    insert_related_agent,
    query_all_agent_info_by_tenant_id,
    query_sub_agent_relations,
    query_sub_agents_id_list,
    resolve_sub_agent_version_no,
    search_agent_id_by_agent_name,
    search_agent_info_by_agent_id,
    search_blank_sub_agent_by_main_agent_id,
    update_agent,
    update_related_agents,
    clear_agent_new_mark
)
from database import a2a_agent_db
from database.model_management_db import get_model_by_model_id, get_model_by_model_id_ignore_delete, get_model_id_by_display_name, get_valid_model_ids
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
from database import skill_db
from database.attachment_db import upload_fileobj
from services.skill_service import SkillService
from services.file_management_service import is_allowed_skill_upload_path
from database.agent_version_db import query_version_list, query_current_version_no
from database.group_db import query_group_ids_by_user
from database.user_tenant_db import get_user_tenant_by_user_id
from database.a2a_agent_db import get_server_agent_ids, query_external_sub_agents
from services.prompt_template_service import (
    SYSTEM_PROMPT_TEMPLATE_ID,
    SYSTEM_PROMPT_TEMPLATE_NAME,
    get_prompt_template_summary,
)
from utils.str_utils import convert_list_to_string, convert_string_to_list
from services.conversation_management_service import (
    create_new_conversation,
    generate_conversation_title_service,
    get_latest_assistant_message,
    get_last_unit_for_message,
    save_conversation_user,
    save_message,
    save_message_unit,
    save_source_image,
    save_source_search,
    save_skill_files_to_conversation,
    update_conversation_agent_id_service,
    update_message_content,
    update_message_status,
    update_unit_content,
    update_unit_status,
)
from services.memory_config_service import build_memory_context
from services.streaming_channel import streaming_channel_manager
from services.runtime_state_service import runtime_state_service
from utils.auth_utils import get_current_user_info, get_user_language
from utils.config_utils import tenant_config_manager
from utils.memory_utils import build_memory_config
from utils.thread_utils import submit
from utils.prompt_template_utils import get_prompt_generate_prompt_template
from utils.llm_utils import call_llm_for_system_prompt

# Monitoring utilities: bind Agent metadata once at the request boundary.
from nexent.monitor import AgentRunMetadata, agent_monitoring_context
from utils.monitoring import monitoring_manager

logger = logging.getLogger(__name__)
SAFE_AGENT_STREAM_ERROR_MESSAGE = "Agent execution failed. Please try again later."


def _resolve_agent_request_turn_resources(
    agent_request: AgentRequest,
    tenant_id: str,
) -> None:
    """Resolve optional resources lazily to keep the normal run path isolated."""
    if not isinstance(agent_request.turn_resources, TurnResourceInvocationRequest):
        agent_request._resolved_turn_resources = None
        return
    from services.turn_resource_service import resolve_turn_resources

    agent_request._resolved_turn_resources = resolve_turn_resources(
        agent_request.turn_resources,
        tenant_id,
    )


async def _cleanup_channel_later(conversation_id: int, user_id: str, delay: float = 5.0):
    """
    Remove the streaming channel after a delay to allow subscribers to finish.
    This gives reconnected clients time to receive the final chunks before cleanup.
    """
    await asyncio.sleep(delay)
    await streaming_channel_manager.remove_channel(conversation_id, user_id)


async def _poll_runtime_cancel_signal(conversation_id: int, user_id: str, stop_event) -> None:
    """Mirror Redis cancel signal into the local agent stop_event."""
    while not stop_event.is_set():
        if await runtime_state_service.is_cancelled_async(user_id=user_id, conversation_id=conversation_id):
            stop_event.set()
            logger.info(
                "Runtime cancel signal received, user_id=%s, conversation_id=%s",
                user_id,
                conversation_id,
            )
            return
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


async def _cancel_task_on_runtime_signal(conversation_id: int, user_id: str, task: asyncio.Task) -> None:
    """Cancel a local asyncio task when another Pod writes the runtime cancel signal."""
    while not task.done():
        if await runtime_state_service.is_cancelled_async(user_id=user_id, conversation_id=conversation_id):
            task.cancel()
            logger.info(
                "Runtime cancel signal cancelled task, user_id=%s, conversation_id=%s",
                user_id,
                conversation_id,
            )
            return
        await asyncio.sleep(RUNTIME_CANCEL_POLL_INTERVAL_SECONDS)


def _extract_json_objects_from_text(text: str) -> list[dict]:
    """Extract all JSON objects embedded in a text blob."""
    if not text:
        return []

    decoder = json.JSONDecoder()
    results: list[dict] = []
    index = 0

    while index < len(text):
        start_index = text.find("{", index)
        if start_index < 0:
            break

        try:
            payload, end_index = decoder.raw_decode(text, start_index)
        except json.JSONDecodeError:
            index = start_index + 1
            continue

        if isinstance(payload, dict):
            results.append(payload)
        index = max(end_index, start_index + 1)

    return results


def _extract_skill_file_upload_payloads(content: str) -> list[dict]:
    """Extract JSON payloads containing absolute_path from streamed tool output."""
    payloads: list[dict] = []
    for payload in _extract_json_objects_from_text(content):
        if payload.get("absolute_path"):
            payloads.append(payload)
    return payloads


def _transform_skill_files_to_standard_format(upload_results: list[dict]) -> list[dict]:
    """
    Transform skill file upload results to match the frontend attachment format.

    Skill upload format:
        {file_name, absolute_path, object_name, preview_url, url, presigned_url, mime_type, file_size, status}
    Frontend format:
        {object_name, name, type, size, url, presigned_url, description}
    """
    frontend_files = []
    for result in upload_results:
        frontend_files.append({
            "object_name": result.get("object_name", ""),
            "name": result.get("file_name", result.get("name", "")),
            "type": "file",
            "size": result.get("file_size", result.get("size", 0)),
            "url": result.get("url", ""),
            "presigned_url": result.get("presigned_url", result.get("preview_url", "")),
            "description": "",
        })
    return frontend_files


async def _process_skill_file_uploads(
    content: str,
    user_id: str,
    tenant_id: str,
) -> list[dict]:
    """Upload generated skill files to storage and return upload metadata."""

    upload_results: list[dict] = []
    for payload in _extract_skill_file_upload_payloads(content):
        absolute_path = str(payload.get("absolute_path") or "").strip()
        file_name = str(
            payload.get("file_name")
            or payload.get("file_path")
            or os.path.basename(absolute_path)
        )
        mime_type = str(payload.get("mime_type") or payload.get("content_type") or "application/octet-stream")
        if not absolute_path:
            continue

        if not is_allowed_skill_upload_path(absolute_path):
            logger.warning(
                "[skill-file] rejected unsafe path absolute_path=%s",
                absolute_path,
            )
            continue

        if not file_name:
            file_name = os.path.basename(absolute_path)

        if not os.path.exists(absolute_path):
            continue

        try:
            file_size = os.path.getsize(absolute_path)
            actual_prefix = f"skill-files/{user_id}" if user_id else "skill-files"
            with open(absolute_path, "rb") as file_obj:
                upload_result = upload_fileobj(
                    file_obj=file_obj,
                    file_name=file_name,
                    prefix=actual_prefix,
                    generate_presigned_url=True,
                    file_size=file_size,
                )

            if upload_result.get("success"):
                upload_results.append(
                    {
                        "status": "success",
                        "file_name": file_name,
                        "absolute_path": absolute_path,
                        "object_name": upload_result.get("object_name"),
                        "preview_url": upload_result.get("presigned_url") or upload_result.get("url"),
                        "url": upload_result.get("url"),
                        "presigned_url": upload_result.get("presigned_url"),
                        "mime_type": mime_type,
                        "file_size": upload_result.get("file_size", file_size),
                    }
                )
            else:
                error_message = upload_result.get("error") or "Upload failed"
                logger.warning(
                    "[skill-file] upload failed file_name=%s absolute_path=%s error=%s",
                    file_name,
                    absolute_path,
                    error_message,
                )
        except Exception as exc:
            logger.exception(
                "[skill-file] failed to upload file file_name=%s absolute_path=%s",
                file_name,
                absolute_path,
            )

    return upload_results


def _safe_agent_stream_error_chunk() -> str:
    """Return a sanitized SSE error chunk without internal exception details."""
    error_payload = json.dumps(
        {"type": "error", "content": SAFE_AGENT_STREAM_ERROR_MESSAGE},
        ensure_ascii=False,
    )
    return f"data: {error_payload}\n\n"


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


def _resolve_model_ids_with_fallback(
    model_ids: List[int] | None,
    model_display_names: List[str] | None,
    model_label: str,
    tenant_id: str,
) -> List[int] | None:
    """
    Resolve model_ids from an import payload, merging two sources in priority order:

      1. Explicit `model_ids` provided in the payload. Each id is validated against
         the target tenant's catalog; missing ids are dropped (logged).
      2. `model_display_names` resolved via ``get_model_id_by_display_name`` to
         cover ids that were lost in step 1.
      3. A single quick config LLM model id is appended if any of the desired
         models could not be resolved (so the agent always has at least one
         usable model after import).

    Args:
        model_ids: Optional list of model ids from the export payload.
        model_display_names: Optional list of display names for fallback lookup.
        model_label: Label for logging (e.g., "Model", "Business logic model").
        tenant_id: Tenant ID for catalog lookup.

    Returns:
        Ordered, de-duplicated list of resolved model_ids; empty list if no
        input was provided (caller should skip persisting model_ids).
    """
    if not model_ids and not model_display_names:
        return None

    resolved_ids: List[int] = []
    seen: set[int] = set()
    missing_ids: List[int] = []

    # Step 1: validate explicit ids against the current tenant catalog.
    for mid in model_ids or []:
        if mid in seen:
            continue
        info = get_model_by_model_id(mid)
        if info:
            seen.add(mid)
            resolved_ids.append(mid)
        else:
            missing_ids.append(mid)

    if resolved_ids:
        logger.info(
            f"{model_label} import: kept {len(resolved_ids)}/{len(model_ids or [])} "
            f"explicit model_ids in tenant {tenant_id}"
            + (f"; missing ids: {missing_ids}" if missing_ids else "")
        )
        # When the caller explicitly provides model_ids, the selection is intentional —
        # do NOT supplement with extra models from model_display_names.
        return resolved_ids

    # Step 2: resolve remaining slots by display name.
    # Only reached when model_ids was empty/None (caller did not specify a preference),
    # so we use display names to find a suitable model in the target tenant.
    used_name_indices: set[int] = set()
    missing_names: List[str] = []

    for idx, display_name in enumerate(model_display_names or []):
        if not display_name:
            continue

        resolved_id = get_model_id_by_display_name(display_name, tenant_id)
        if resolved_id and resolved_id not in seen:
            seen.add(resolved_id)
            resolved_ids.append(resolved_id)
            used_name_indices.add(idx)
        else:
            missing_names.append(display_name)
            used_name_indices.add(idx)

    if model_display_names:
        logger.info(
            f"{model_label} import: resolved {len(used_name_indices) - len(missing_names)}/"
            f"{len(model_display_names)} display names in tenant {tenant_id}"
            + (f"; missing names: {missing_names}" if missing_names else "")
        )

    # Step 3: quick config LLM fallback when still nothing resolved.
    if not resolved_ids and (missing_ids or missing_names):
        quick_config_model = tenant_config_manager.get_model_config(
            key=MODEL_CONFIG_MAPPING["llm"],
            tenant_id=tenant_id,
        )
        if quick_config_model:
            fallback_id = quick_config_model.get("model_id")
            if fallback_id is not None and fallback_id not in seen:
                logger.warning(
                    f"{model_label} import: no usable model found in tenant {tenant_id} "
                    f"(missing ids: {missing_ids}, missing names: {missing_names}); "
                    f"falling back to quick config LLM model "
                    f"'{quick_config_model.get('display_name')}' (model_id: {fallback_id})"
                )
                resolved_ids.append(fallback_id)

    return resolved_ids


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
    fallback_fn: Callable[[str], str],
    prompt_template_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> str:
    """
    Shared helper to regenerate agent-related values with an LLM.
    """
    if user_id is not None:
        from services.prompt_template_service import resolve_prompt_generate_template
        prompt_template = resolve_prompt_generate_template(
            tenant_id=tenant_id,
            user_id=user_id,
            language=language,
            prompt_template_id=prompt_template_id,
        )
    else:
        prompt_template = normalize_prompt_generate_template_content(
            get_prompt_generate_prompt_template(language)
        )
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
            candidate = (regenerated_value or "").strip().splitlines()[
                0].strip()
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
    exclude_agent_id: int | None = None,
    prompt_template_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> str:
    return _regenerate_agent_value_with_llm(
        original_value=original_name,
        existing_values=existing_names,
        task_description=task_description,
        model_id=model_id,
        tenant_id=tenant_id,
        language=language,
        system_prompt_key="agent_name_regenerate_system_prompt",
        user_prompt_key="agent_name_regenerate_user_prompt",
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
        ),
        prompt_template_id=prompt_template_id,
        user_id=user_id,
    )


def _regenerate_agent_display_name_with_llm(
    original_display_name: str,
    existing_display_names: list[str],
    task_description: str,
    model_id: int,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    agents_cache: list[dict] | None = None,
    exclude_agent_id: int | None = None,
    prompt_template_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> str:
    return _regenerate_agent_value_with_llm(
        original_value=original_display_name,
        existing_values=existing_display_names,
        task_description=task_description,
        model_id=model_id,
        tenant_id=tenant_id,
        language=language,
        system_prompt_key="agent_display_name_regenerate_system_prompt",
        user_prompt_key="agent_display_name_regenerate_user_prompt",
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
        ),
        prompt_template_id=prompt_template_id,
        user_id=user_id,
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

    existing_names = [agent.get("name")
                      for agent in agents_cache if agent.get("name")]
    existing_display_names = [agent.get(
        "display_name") for agent in agents_cache if agent.get("display_name")]

    # Always use tenant quick-config LLM model
    quick_config_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id
    )
    resolved_model_id = quick_config_model.get(
        "model_id") if quick_config_model else None
    if not resolved_model_id:
        raise ValueError(
            "No available model for regeneration. Please configure an LLM model first.")

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
                logger.error(
                    f"Failed to regenerate agent name with LLM: {str(e)}, using fallback")
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
                logger.error(
                    f"Failed to regenerate agent display_name with LLM: {str(e)}, using fallback")
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
    resume_from_unit_index: int = 0,
    resume_message_id: Optional[int] = None,
    channel: Optional[Any] = None,
):
    """
    Yield SSE chunks from agent_run while persisting messages incrementally.

    Args:
        resume_from_unit_index: If > 0, we're in resume mode and should start
                                the unit index counter from this position.
        resume_message_id: The existing message_id to use in resume mode
                          (instead of creating a new one).
        channel: Optional StreamingChannel for multi-subscriber support.
    """

    # Types whose chunks should be merged into the previous unit boundary,
    # matching the legacy batch merge logic.
    _MERGEABLE_TYPES = {
        ProcessType.MODEL_OUTPUT_CODE.value,
        ProcessType.MODEL_OUTPUT_THINKING.value,
        ProcessType.MODEL_OUTPUT_DEEP_THINKING.value,
    }

    captured_final_answer = None
    captured_skill_files: dict[str, dict] = {}
    skill_file_uploads: list[dict] = []

    # Determine if we're in resume mode
    is_resume_mode = resume_from_unit_index > 0

    # Persist the parent ConversationMessage row up front with status='streaming'
    # so that units saved incrementally have a valid message_id to reference.
    streaming_message_id: Optional[int] = resume_message_id
    if not is_resume_mode and not agent_request.is_debug:
        user_role_count = sum(
            1 for item in getattr(agent_request, "history", [])
            if item.role == MESSAGE_ROLE["USER"]
        )
        assistant_message_req = MessageRequest(
            conversation_id=agent_request.conversation_id,
            message_idx=user_role_count * 2 + 1,
            role=MESSAGE_ROLE["ASSISTANT"],
            message=[],
            minio_files=None,
        )
        try:
            streaming_message_id = save_message(
                assistant_message_req,
                user_id=user_id,
                tenant_id=tenant_id,
                status="streaming",
            )
        except Exception as msg_exc:
            logger.error(
                "Failed to create streaming message row: %r", msg_exc, exc_info=True)

    # Tracks the unit currently being accumulated in memory. Each entry is
    # a dict with keys: type, content, unit_id, unit_index, mergeable.
    current_unit: Optional[Dict[str, Any]] = None
    # The next unit_index to assign to a brand-new (non-merge) unit.
    # In resume mode, start from the position after the last persisted unit.
    next_unit_index: int = resume_from_unit_index
    # Set when the agent run loop finishes successfully.
    stream_completed_normally: bool = False

    # Get or create streaming channel for multi-subscriber support
    if channel is None:
        channel = await streaming_channel_manager.get_or_create_channel(
            conversation_id=agent_request.conversation_id,
            user_id=user_id
        )

    cancel_poll_task = asyncio.create_task(
        _poll_runtime_cancel_signal(
            conversation_id=agent_request.conversation_id,
            user_id=user_id,
            stop_event=agent_run_info.stop_event,
        )
    )

    # In resume mode, emit a status event first
    if is_resume_mode:
        await channel.publish(STREAM_STATUS_EVENT)
        await channel.publish(f'data: {{"status": "resumed", "last_unit_index": {resume_from_unit_index - 1}}}\n\n')
        yield STREAM_STATUS_EVENT
        yield f'data: {{"status": "resumed", "last_unit_index": {resume_from_unit_index - 1}}}\n\n'

    try:
        async for chunk in agent_run(agent_run_info):
            chunk_type: Optional[str] = None
            chunk_content: str = ""
            try:
                data = json.loads(chunk)
                chunk_type = data.get("type")
                chunk_content = data.get("content", "") or ""

                # Add unit_index to the chunk data for frontend resume skip logic.
                # This allows frontend to accurately skip chunks that were already persisted.
                # For mergeable types (continuing chunks), use the current unit's index.
                # For new units, use the next_unit_index that will be assigned.
                if streaming_message_id is not None and chunk_type:
                    mergeable = chunk_type in _MERGEABLE_TYPES
                    if current_unit is not None and mergeable and current_unit.get("type") == chunk_type:
                        # Continuing chunk - use current unit's index
                        data["unit_index"] = current_unit["unit_index"]
                    elif chunk_type not in ("search_content_placeholder",):
                        # New unit - this will be the next index after assignment
                        data["unit_index"] = next_unit_index
                    # Re-serialize the chunk with unit_index for accurate frontend skip
                    chunk = json.dumps(data)
                    logger.debug(f"[resume-debug] Added unit_index to chunk: type={chunk_type}, unit_index={data.get('unit_index')}")
            except Exception:
                # Malformed chunk: emit as-is and skip persistence bookkeeping.
                await channel.publish(f"data: {chunk}\n\n")
                yield f"data: {chunk}\n\n"
                continue

            if chunk_type == "final_answer":
                captured_final_answer = chunk_content

            should_parse_skill_file = (
                chunk_type in {"execution_logs", "parse"}
                or data.get("role") == "tool-response"
            )
            if should_parse_skill_file:
                extracted_payload_count = 0
                content_value = data.get("content")
                if isinstance(content_value, list):
                    content_items = content_value
                elif content_value:
                    content_items = [{"type": "text", "text": str(content_value)}]
                else:
                    content_items = []

                for item in content_items:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_value = item.get("text")
                        if text_value:
                            extracted_payloads = _extract_json_objects_from_text(text_value)
                            for payload in extracted_payloads:
                                absolute_path = str(payload.get("absolute_path") or "").strip()
                                if not absolute_path:
                                    continue
                                if absolute_path in captured_skill_files:
                                    continue
                                if not os.path.exists(absolute_path):
                                    continue
                                captured_skill_files[absolute_path] = payload
                                extracted_payload_count += 1
                if extracted_payload_count:
                    logger.info(
                        "[skill-file] captured payloads count=%s current_total=%s",
                        extracted_payload_count,
                        len(captured_skill_files),
                    )

            # Incremental unit persistence: when a new chunk belongs to a different
            # unit than the one currently being buffered, flush the previous unit
            # and insert a fresh row for the new chunk.
            if streaming_message_id is not None and chunk_type:
                mergeable = chunk_type in _MERGEABLE_TYPES
                is_continuation = (
                    current_unit is not None
                    and mergeable
                    and current_unit.get("type") == chunk_type
                )

                if is_continuation:
                    # Same mergeable unit: append to the in-memory buffer and
                    # update the DB row to keep content in sync.
                    # Use synchronous write to prevent race condition: the async submit()
                    # approach has a critical bug where concurrent submits can read stale
                    # content and overwrite the DB with incomplete data. Since the main
                    # loop is async but the DB operations are I/O-bound with network
                    # latency, synchronous writes here are acceptably fast and guarantee
                    # that each chunk is fully persisted before the next chunk arrives.
                    old_len = len(current_unit["content"])
                    current_unit["content"] += chunk_content
                    new_len = len(current_unit["content"])
                    update_unit_content(
                        current_unit["unit_id"],
                        current_unit["content"],
                        user_id,
                    )
                else:
                    # Boundary detected: close the previous unit (if any) and
                    # open a new one for this chunk.
                    if current_unit is not None:
                        submit(
                            update_unit_status,
                            current_unit["unit_id"],
                            "completed",
                            user_id,
                        )

                    # Special-case: final_answer also updates message_content
                    if chunk_type == "final_answer":
                        submit(
                            update_message_content,
                            streaming_message_id,
                            chunk_content,
                            user_id,
                        )

                    # Special-case: picture_web saves image source references
                    if chunk_type == "picture_web":
                        try:
                            content_json = json.loads(chunk_content)
                            if isinstance(content_json, dict) and "images_url" in content_json:
                                seen_urls: set[str] = set()
                                unique_urls: list[str] = []
                                for image_url in content_json["images_url"]:
                                    if image_url not in seen_urls:
                                        seen_urls.add(image_url)
                                        unique_urls.append(image_url)
                                for image_url in unique_urls:
                                    submit(
                                        save_source_image,
                                        {
                                            "message_id": streaming_message_id,
                                            "conversation_id": agent_request.conversation_id,
                                            "image_url": image_url,
                                        },
                                    )
                        except Exception as img_exc:
                            logger.error(
                                "Failed to persist picture_web unit: %r", img_exc, exc_info=True
                            )

                    # Special-case: search_content creates a placeholder unit
                    # and inserts each search result as a source_search row
                    # linked back to the unit_id we just created.
                    if chunk_type == "search_content":
                        placeholder_unit_id = submit(
                            save_message_unit,
                            message_id=streaming_message_id,
                            conversation_id=agent_request.conversation_id,
                            unit_index=next_unit_index,
                            unit_type="search_content_placeholder",
                            unit_content='{"placeholder": true}',
                            user_id=user_id,
                            unit_status="completed",
                        ).result()
                        try:
                            search_results = json.loads(chunk_content)
                            if not isinstance(search_results, list):
                                search_results = [search_results]
                            for result in search_results:
                                search_data = {
                                    "message_id": streaming_message_id,
                                    "conversation_id": agent_request.conversation_id,
                                    "unit_id": placeholder_unit_id,
                                    "source_type": result.get("source_type", ""),
                                    "source_title": result.get("title", ""),
                                    "source_location": result.get("url", ""),
                                    "source_content": result.get("text", ""),
                                    "score_overall": float(result.get("score"))
                                    if result.get("score") not in (None, "")
                                    else None,
                                    "score_accuracy": float(result.get("score_details", {}).get("accuracy"))
                                    if result.get("score_details", {}).get("accuracy") not in (None, "")
                                    else None,
                                    "score_semantic": float(result.get("score_details", {}).get("semantic"))
                                    if result.get("score_details", {}).get("semantic") not in (None, "")
                                    else None,
                                    "published_date": result.get("published_date")
                                    if result.get("published_date") not in (None, "")
                                    else None,
                                    "cite_index": result.get("cite_index")
                                    if result.get("cite_index") != ""
                                    else None,
                                    "search_type": result.get("search_type")
                                    if result.get("search_type")
                                    else None,
                                    "tool_sign": result.get("tool_sign", ""),
                                }
                                submit(save_source_search, search_data, user_id)
                        except Exception as src_exc:
                            logger.error(
                                "Failed to persist search_content unit: %r", src_exc, exc_info=True
                            )
                        current_unit = None
                        next_unit_index += 1
                        await channel.publish(f"data: {chunk}\n\n")
                        yield f"data: {chunk}\n\n"
                        continue

                    # Default path: insert a new unit row with unit_status='streaming'.
                    if streaming_message_id is not None and chunk_type not in (
                        "search_content_placeholder",
                    ):
                        new_unit_id = submit(
                            save_message_unit,
                            message_id=streaming_message_id,
                            conversation_id=agent_request.conversation_id,
                            unit_index=next_unit_index,
                            unit_type=chunk_type,
                            unit_content=chunk_content,
                            user_id=user_id,
                            unit_status="streaming",
                        ).result()
                        current_unit = {
                            "type": chunk_type,
                            "content": chunk_content,
                            "unit_id": new_unit_id,
                            "unit_index": next_unit_index,
                            "mergeable": mergeable,
                        }
                        next_unit_index += 1

            await channel.publish(f"data: {chunk}\n\n")
            yield f"data: {chunk}\n\n"
        stream_completed_normally = True
    except Exception as run_exc:
        logger.error("Agent run error: %r", run_exc, exc_info=True)
        await channel.publish(_safe_agent_stream_error_chunk())
        yield _safe_agent_stream_error_chunk()
    finally:
        # Finalize any in-flight unit and transition the parent message to its
        # terminal status before releasing the agent run slot.
        if streaming_message_id is not None:
            if current_unit is not None:
                try:
                    # First update the content to ensure the last chunk is persisted
                    # This must be done synchronously before updating status
                    final_content = current_unit["content"]
                    update_unit_content(
                        current_unit["unit_id"],
                        final_content,
                        user_id,
                    )
                except Exception:
                    logger.exception("Failed to update last unit content")
                try:
                    update_unit_status(
                        current_unit["unit_id"],
                        "completed",
                        user_id,
                    )
                except Exception:
                    logger.exception("Failed to mark last unit as completed")

            was_stopped = getattr(agent_run_info, "stop_event", None) and agent_run_info.stop_event.is_set()
            terminal_status = "stopped" if was_stopped else "completed" if stream_completed_normally else "failed"
            try:
                update_message_status(
                    streaming_message_id,
                    terminal_status,
                    user_id,
                )
            except Exception:
                logger.exception("Failed to mark assistant message as %s", terminal_status)

        if not cancel_poll_task.done():
            cancel_poll_task.cancel()

        was_stopped = getattr(agent_run_info, "stop_event", None) and agent_run_info.stop_event.is_set()
        terminal_status = 'stopped' if was_stopped else 'completed' if stream_completed_normally else 'failed'

        agent_run_manager.unregister_agent_run(
            agent_request.conversation_id, user_id, status=terminal_status)

        # Mark channel as completed and schedule cleanup
        if channel is not None:
            await streaming_channel_manager.complete_channel(
                conversation_id=agent_request.conversation_id,
                user_id=user_id,
                status=terminal_status
            )
            # Schedule channel removal (give subscribers time to receive final chunks)
            cleanup_task = asyncio.create_task(
                _cleanup_channel_later(
                    conversation_id=agent_request.conversation_id,
                    user_id=user_id
                )
            )

        try:
            skill_file_content_local = "\n".join(
                json.dumps(payload, ensure_ascii=False)
                for payload in captured_skill_files.values()
            )
            if skill_file_content_local:
                skill_file_uploads = await _process_skill_file_uploads(
                    content=skill_file_content_local,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                logger.info(
                    "[skill-file] upload finished conversation=%s result_count=%s results=%s",
                    agent_request.conversation_id,
                    len(skill_file_uploads), skill_file_uploads
                )
                if skill_file_uploads:
                    # Keep original format for real-time SSE display
                    skill_files_payload = json.dumps(
                        {"skill_file_uploads": skill_file_uploads},
                        ensure_ascii=False,
                    )
                    try:
                        yield f"data: {json.dumps({'type': 'skill_files', 'content': skill_files_payload}, ensure_ascii=False)}\n\n"
                    except RuntimeError:
                        # Stream is closing (e.g., client disconnect). Avoid raising during generator teardown.
                        pass
                    # Persist skill file uploads to the conversation history so they
                    # appear in subsequent GET /conversation/{id} calls.
                    # Transform to frontend attachment format (object_name, name, type, size, etc.)
                    try:
                        frontend_files = _transform_skill_files_to_standard_format(skill_file_uploads)
                        save_skill_files_to_conversation(
                            conversation_id=agent_request.conversation_id,
                            skill_file_uploads=frontend_files,
                            user_id=user_id,
                        )
                    except Exception:
                        logger.exception(
                            "[skill-file] failed to persist skill file uploads to conversation=%s",
                            agent_request.conversation_id,
                        )
        except Exception:
            logger.exception("Failed to process skill file uploads")

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
            background_task.add_done_callback(
                lambda t: t.exception() if t.exception() else None)
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


async def get_agent_info_impl(agent_id: int, tenant_id: str, version_no: int = 0, user_id: Optional[str] = None):
    try:
        agent_info = search_agent_info_by_agent_id(
            agent_id, tenant_id, version_no)
        # Keep the request-scoped tenant_id unless the record explicitly provides one.
        record_tenant_id = agent_info.get("tenant_id")
        if record_tenant_id:
            tenant_id = record_tenant_id
    except Exception as e:
        logger.error(f"Failed to get agent info: {str(e)}")
        raise ValueError(f"Failed to get agent info: {str(e)}")

    # Calculate permission if user_id is provided
    if user_id is not None:
        try:
            user_tenant_record = get_user_tenant_by_user_id(user_id) or {}
            user_role = str(user_tenant_record.get("user_role") or "").upper()
            can_edit_all = user_role in CAN_EDIT_ALL_USER_ROLES

            # Permission logic (same as agent list, including ASSET_OWNER read-only override)
            agent_info["permission"] = resolve_agent_list_permission(
                user_role=user_role,
                agent=agent_info,
                user_id=user_id,
                can_edit_all=can_edit_all,
            )
        except Exception as e:
            logger.warning(f"Failed to calculate agent permission: {str(e)}")

    try:
        tool_info = search_tools_for_sub_agent(
            agent_id=agent_id, tenant_id=tenant_id)
        # Check if selected_model_id in tool params points to a deleted model
        for tool in tool_info:
            unavailable_reasons: List[str] = []
            params = tool.get("params") or []
            if isinstance(params, list):
                for param_def in params:
                    if not isinstance(param_def, dict):
                        continue
                    if param_def.get("name") == "selected_model_id":
                        selected_model_id = param_def.get("default")
                        if selected_model_id is not None:
                            model_record = get_model_by_model_id_ignore_delete(selected_model_id, tenant_id)
                            if model_record is not None and model_record.get("delete_flag") == "Y":
                                unavailable_reasons.append(AgentUnavailableReason.MCP_MODEL_UNAVAILABLE)
                        break
            tool["unavailable_reasons"] = unavailable_reasons
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

    try:
        skill_service = SkillService()
        instances = skill_service.list_skill_instances(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no
        )
        # Keep disabled instances for their saved configuration, but do not
        # return them as selected skills in the agent configuration.
        agent_info["skills"] = [
            instance for instance in instances if instance.get("enabled", True)
        ]
    except Exception as e:
        logger.exception(f"Failed to get agent skills: {str(e)}")
        agent_info["skills"] = []

    try:
        external_agents = query_external_sub_agents(
            local_agent_id=agent_id, tenant_id=tenant_id, version_no=version_no)
        agent_info["external_sub_agent_id_list"] = [
            ea["external_agent_id"] for ea in external_agents
        ]
    except Exception as e:
        logger.error(f"Failed to get external sub agents: {str(e)}")
        agent_info["external_sub_agent_id_list"] = []

    # Get model names from model_ids array
    # Filter out deleted models (delete_flag='Y' in model_record_t)
    model_ids = agent_info.get("model_ids") or []
    valid_model_ids = get_valid_model_ids(model_ids, tenant_id)
    agent_info["model_ids"] = valid_model_ids

    model_names: List[str] = []
    for mid in valid_model_ids:
        model_info = get_model_by_model_id(mid)
        if model_info:
            display_name = model_info.get("display_name")
            if display_name:
                model_names.append(display_name)
    agent_info["model_names"] = model_names
    # Always derive model_name from valid_model_ids so the API contract is consistent.
    if valid_model_ids:
        first_model_info = get_model_by_model_id(valid_model_ids[0])
        agent_info["model_name"] = first_model_info.get(
            "display_name", None) if first_model_info is not None else None
    else:
        agent_info["model_name"] = None

    # Get business logic model display name from model_id
    if agent_info.get("business_logic_model_id") is not None:
        business_logic_model_info = get_model_by_model_id(
            agent_info["business_logic_model_id"])
        agent_info["business_logic_model_name"] = business_logic_model_info.get(
            "display_name", None) if business_logic_model_info is not None else None
    elif "business_logic_model_name" not in agent_info:
        agent_info["business_logic_model_name"] = None

    if not agent_info.get("prompt_template_id"):
        agent_info["prompt_template_id"] = SYSTEM_PROMPT_TEMPLATE_ID
    if not agent_info.get("prompt_template_name"):
        agent_info["prompt_template_name"] = SYSTEM_PROMPT_TEMPLATE_NAME

    if agent_info.get("group_ids") is not None:
        agent_info["group_ids"] = convert_string_to_list(
            agent_info.get("group_ids"))

    # Check agent availability
    is_available, unavailable_reasons = check_agent_availability(
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_info=agent_info
    )
    agent_info["is_available"] = is_available
    agent_info["unavailable_reasons"] = unavailable_reasons

    # Set current_version_no from draft record (version_no=0)
    # This ensures the returned data always has the current published version info
    if version_no > 0:
        draft_version_no = query_current_version_no(agent_id, tenant_id)
        agent_info["current_version_no"] = draft_version_no

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
            "model_ids": agent_info.get("model_ids"),
            "model_names": agent_info.get("model_names"),
            "max_steps": agent_info["max_steps"],
            "requested_output_tokens": agent_info.get("requested_output_tokens"),
            "business_description": agent_info["business_description"],
            "duty_prompt": agent_info.get("duty_prompt"),
            "constraint_prompt": agent_info.get("constraint_prompt"),
            "few_shots_prompt": agent_info.get("few_shots_prompt"),
            "sub_agent_id_list": query_sub_agents_id_list(main_agent_id=sub_agent_id, tenant_id=tenant_id)}


def _validate_requested_output_tokens_for_agent(
    request: AgentInfoRequest,
    tenant_id: str,
) -> None:
    requested_output_tokens = request.requested_output_tokens
    if requested_output_tokens is None:
        return

    model_id = request.model_id
    if model_id is None and request.agent_id is not None:
        try:
            existing_agent = search_agent_info_by_agent_id(
                agent_id=request.agent_id,
                tenant_id=tenant_id,
                version_no=request.version_no,
            )
            model_id = existing_agent.get("model_id")
        except Exception as exc:
            logger.warning(
                "Could not resolve existing agent model for requested_output_tokens validation: %s",
                exc,
            )

    if model_id is None:
        return

    model_info = get_model_by_model_id(model_id, tenant_id=tenant_id)
    max_output_tokens = model_info.get("max_output_tokens") if model_info else None
    if max_output_tokens is not None and requested_output_tokens > max_output_tokens:
        raise AppException(
            ErrorCode.COMMON_PARAMETER_INVALID,
            (
                "requested_output_tokens cannot exceed the selected model "
                f"max_output_tokens ({max_output_tokens})"
            ),
        )


async def update_agent_info_impl(request: AgentInfoRequest, authorization: str = Header(None)):
    user_id, tenant_id, _ = get_current_user_info(authorization)

    if request.example_questions is not None and len(request.example_questions) > 6:
        raise AppException(ErrorCode.COMMON_PARAMETER_INVALID, "example_questions cannot exceed 6 items")

    _validate_requested_output_tokens_for_agent(request, tenant_id)

    prompt_template_id, prompt_template_name = get_prompt_template_summary(
        template_id=request.prompt_template_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

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
                "model_ids": request.model_ids,
                "business_logic_model_id": request.business_logic_model_id,
                "business_logic_model_name": request.business_logic_model_name,
                "prompt_template_id": prompt_template_id,
                "prompt_template_name": prompt_template_name,
                "max_steps": request.max_steps,
                "requested_output_tokens": request.requested_output_tokens,
                "provide_run_summary": request.provide_run_summary,
                "verification_config": request.verification_config,
                "duty_prompt": request.duty_prompt,
                "constraint_prompt": request.constraint_prompt,
                "few_shots_prompt": request.few_shots_prompt,
                "greeting_message": request.greeting_message,
                "example_questions": request.example_questions,
                "enabled": request.enabled if request.enabled is not None else True,
                "group_ids": convert_list_to_string(request.group_ids) if request.group_ids else user_group_ids,
                "ingroup_permission": request.ingroup_permission
            }, tenant_id=tenant_id, user_id=user_id)
            agent_id = created["agent_id"]
        else:
            # Update agent
            request.prompt_template_id = prompt_template_id
            request.prompt_template_name = prompt_template_name
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
                # Safely get params, default to empty dict if None or not present
                raw_params = (existing_instance or {}).get("params")
                params = raw_params if raw_params is not None else {}
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

    # Handle enabled skills saving when provided
    try:
        if request.enabled_skill_ids is not None and agent_id is not None:
            enabled_set = set(request.enabled_skill_ids)
            # Query existing skill instances for this agent
            existing_instances = skill_db.query_skill_instances_by_agent_id(
                agent_id, tenant_id)

            # Handle unselected skill (already exist instance) -> enabled=False
            for instance in existing_instances:
                inst_skill_id = instance.get("skill_id")
                if inst_skill_id is not None and inst_skill_id not in enabled_set:
                    skill_db.create_or_update_skill_by_skill_info(
                        skill_info=SkillInstanceInfoRequest(
                            skill_id=inst_skill_id,
                            agent_id=agent_id,
                            skill_description=instance.get(
                                "skill_description"),
                            skill_content=instance.get("skill_content"),
                            enabled=False,
                            config_values=instance.get("config_values"),
                        ),
                        tenant_id=tenant_id,
                        user_id=user_id
                    )

            # Handle selected skill -> enabled=True (create or update)
            for skill_id in enabled_set:
                # Keep existing skill_description and skill_content if any
                existing_instance = next(
                    (inst for inst in existing_instances
                     if inst.get("skill_id") == skill_id),
                    None
                )
                skill_description = (existing_instance or {}).get(
                    "skill_description")
                skill_content = (existing_instance or {}).get("skill_content")
                skill_db.create_or_update_skill_by_skill_info(
                    skill_info=SkillInstanceInfoRequest(
                        skill_id=skill_id,
                        agent_id=agent_id,
                        skill_description=skill_description,
                        skill_content=skill_content,
                        enabled=True,
                        config_values=(existing_instance or {}
                                       ).get("config_values"),
                    ),
                    tenant_id=tenant_id,
                    user_id=user_id
                )
    except Exception as e:
        logger.error(f"Failed to update agent skills: {str(e)}")
        raise ValueError(f"Failed to update agent skills: {str(e)}")

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
                    raise ValueError(
                        "Circular dependency detected: Agent cannot be related to itself or create circular calls")
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

    # Handle related external agents saving when provided
    try:
        if request.related_external_agent_ids is not None and agent_id is not None:
            related_external_agent_ids = request.related_external_agent_ids
            # Query current relations
            current_relations = a2a_agent_db.list_external_relations_by_local_agent(
                local_agent_id=agent_id,
                tenant_id=tenant_id
            )
            current_external_ids = {
                rel["external_agent_id"] for rel in current_relations
            }
            new_external_ids = set(
                related_external_agent_ids) if related_external_agent_ids else set()

            # Find IDs to delete (in current but not in new)
            ids_to_delete = current_external_ids - new_external_ids
            # Find IDs to add (in new but not in current)
            ids_to_add = new_external_ids - current_external_ids

            # Soft delete removed relations
            for ext_agent_id in ids_to_delete:
                a2a_agent_db.remove_external_agent_relation(
                    local_agent_id=agent_id,
                    external_agent_id=ext_agent_id,
                    tenant_id=tenant_id
                )

            # Add new relations
            for ext_agent_id in ids_to_add:
                try:
                    a2a_agent_db.add_external_agent_relation(
                        local_agent_id=agent_id,
                        external_agent_id=ext_agent_id,
                        tenant_id=tenant_id,
                        user_id=user_id
                    )
                except ValueError:
                    # Relation already exists, skip
                    pass
    except Exception as e:
        logger.error(f"Failed to update related external agents: {str(e)}")
        raise ValueError(f"Failed to update related external agents: {str(e)}")

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
        skill_db.delete_skills_by_agent_id(agent_id, tenant_id, user_id)

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


async def _export_agent_dict_core(
    root_agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int = 0,
) -> dict:
    """Build ExportAndImportDataFormat dict for an agent tree at the given version."""
    export_agent_dict = {}
    search_list: deque = deque([(root_agent_id, version_no)])
    visited: set = set()

    mcp_info_set = set()

    while search_list:
        current_agent_id, current_version_no = search_list.popleft()
        visit_key = (current_agent_id, current_version_no)
        if visit_key in visited:
            continue
        visited.add(visit_key)

        agent_info = await export_agent_by_agent_id(
            agent_id=current_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=current_version_no,
        )

        for tool in agent_info.tools:
            if tool.source == "mcp" and tool.usage:
                mcp_info_set.add(tool.usage)

        relations = query_sub_agent_relations(
            main_agent_id=current_agent_id,
            tenant_id=tenant_id,
            version_no=current_version_no,
        )
        for rel in relations:
            child_id = rel["selected_agent_id"]
            child_version = resolve_sub_agent_version_no(
                child_id,
                rel.get("selected_agent_version_no"),
                tenant_id,
            )
            search_list.append((child_id, child_version))

        export_agent_dict[str(agent_info.agent_id)] = agent_info

    mcp_info_list = []
    for mcp_server_name in mcp_info_set:
        mcp_url = get_mcp_server_by_name_and_tenant(mcp_server_name, tenant_id)
        mcp_info_list.append(
            MCPInfo(mcp_server_name=mcp_server_name, mcp_url=mcp_url))

    export_data = ExportAndImportDataFormat(
        agent_id=root_agent_id,
        agent_info=export_agent_dict,
        mcp_info=mcp_info_list,
    )
    return export_data.model_dump()


async def export_agent_dict_impl(
    agent_id: int,
    authorization: str = Header(None),
    version_no: int = 0,
) -> dict:
    """
    Export the configuration information of the specified agent and all its sub-agents.

    Args:
        agent_id (int): The ID of the agent to export.
        authorization (str): User authentication information, obtained from the Header.
        version_no (int): Version to export. Default 0 = draft.

    Returns:
        dict: ExportAndImportDataFormat as a plain dict (via model_dump).
    """
    user_id, tenant_id, _ = get_current_user_info(authorization)
    return await _export_agent_dict_core(
        root_agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )


async def export_agent_dict_for_repository_impl(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int,
) -> dict:
    """Export agent tree for marketplace repository storage (no HTTP auth header)."""
    return await _export_agent_dict_core(
        root_agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )


async def export_agent_impl(
    agent_id: int,
    authorization: str = Header(None),
    version_no: int = 0,
) -> str:
    """Serialize export_agent_dict_impl output to a JSON string for download or ZIP embedding."""
    agent_dict = await export_agent_dict_impl(
        agent_id, authorization, version_no=version_no
    )
    return json.dumps(agent_dict)


def _collect_skill_names_from_tree(
    agent_id: int,
    tenant_id: str,
    version_no: int,
    visited: Optional[set] = None,
) -> List[str]:
    """Collect unique skill names from an agent tree at the given version."""
    if visited is None:
        visited = set()

    skill_names: List[str] = []
    seen_names: set = set()

    def _walk(current_agent_id: int, current_version_no: int) -> None:
        visit_key = (current_agent_id, current_version_no)
        if visit_key in visited:
            return
        visited.add(visit_key)

        skill_instances = skill_db.query_skill_instances_by_agent_id(
            agent_id=current_agent_id,
            tenant_id=tenant_id,
            version_no=current_version_no,
        )
        for inst in skill_instances:
            skill_id = inst.get("skill_id")
            skill = skill_db.get_skill_by_id(skill_id, tenant_id)
            if skill:
                name = skill.get("name")
                if name and name not in seen_names:
                    seen_names.add(name)
                    skill_names.append(name)

        relations = query_sub_agent_relations(
            main_agent_id=current_agent_id,
            tenant_id=tenant_id,
            version_no=current_version_no,
        )
        for rel in relations:
            child_id = rel["selected_agent_id"]
            child_version = resolve_sub_agent_version_no(
                child_id,
                rel.get("selected_agent_version_no"),
                tenant_id,
            )
            _walk(child_id, child_version)

    _walk(agent_id, version_no)
    return skill_names


def collect_skill_zip_entries(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0,
) -> List[SkillZipEntry]:
    """Export skill ZIP payloads for all skills in an agent tree."""
    skill_names = _collect_skill_names_from_tree(agent_id, tenant_id, version_no)
    if not skill_names:
        return []

    skill_service = SkillService(tenant_id=tenant_id)
    exported = skill_service.export_skills_by_names(skill_names, tenant_id)
    return [
        SkillZipEntry(
            skill_name=entry["skill_name"],
            skill_zip_base64=entry["skill_zip_base64"],
        )
        for entry in exported
    ]


async def export_agent_by_agent_id(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    version_no: int = 0,
) -> ExportAndImportAgentInfo:
    """Export a single agent's information based on agent_id and version_no."""
    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )
    agent_relation_in_db = query_sub_agents_id_list(
        main_agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )
    tool_list = await create_tool_config_list(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        version_no=version_no,
    )

    # Collect skill names from skill instances
    skill_names: List[str] = []
    try:
        skill_instances = skill_db.query_skill_instances_by_agent_id(
            agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
        )
        for inst in skill_instances:
            skill_id = inst.get("skill_id")
            skill = skill_db.get_skill_by_id(skill_id, tenant_id)
            if skill:
                name = skill.get("name")
                if name:
                    skill_names.append(name)
    except Exception as e:
        logger.warning(
            f"Failed to collect skill instances for agent {agent_id}: {e}")

    # Check if any tool is KnowledgeBaseSearchTool and set its metadata to empty dict
    for tool in tool_list:
        if tool.class_name in ["KnowledgeBaseSearchTool", "AnalyzeTextFileTool", "AnalyzeImageTool", "AnalyzeAudioTool", "AnalyzeVideoTool", "DataMateSearchTool"]:
            tool.metadata = {}

    # Resolve model display names from model_ids array
    model_ids_list = agent_info.get("model_ids") or []
    model_names_list: List[str] = []
    for mid in model_ids_list:
        mid_info = get_model_by_model_id(mid)
        if mid_info:
            display = mid_info.get("display_name")
            if display:
                model_names_list.append(display)

    # Get business_logic_model_id and business logic model display name
    business_logic_model_id = agent_info.get("business_logic_model_id")
    business_logic_model_display_name = None
    if business_logic_model_id is not None:
        business_logic_model_info = get_model_by_model_id(
            business_logic_model_id)
        business_logic_model_display_name = business_logic_model_info.get(
            "display_name") if business_logic_model_info is not None else None

    agent_info = ExportAndImportAgentInfo(agent_id=agent_id,
                                          tenant_id=agent_info["tenant_id"],
                                          name=agent_info["name"],
                                          display_name=agent_info["display_name"],
                                          description=agent_info["description"],
                                          business_description=agent_info["business_description"],
                                          author=agent_info.get("author"),
                                          max_steps=agent_info["max_steps"],
                                          requested_output_tokens=agent_info.get("requested_output_tokens"),
                                          provide_run_summary=agent_info["provide_run_summary"],
                                          verification_config=agent_info.get("verification_config"),
                                          duty_prompt=agent_info.get(
                                              "duty_prompt"),
                                          constraint_prompt=agent_info.get(
                                              "constraint_prompt"),
                                          few_shots_prompt=agent_info.get(
                                              "few_shots_prompt"),
                                          enabled=agent_info["enabled"],
                                          tools=tool_list,
                                          managed_agents=agent_relation_in_db,
                                          model_ids=model_ids_list,
                                          model_names=model_names_list,
                                          business_logic_model_id=business_logic_model_id,
                                          business_logic_model_name=business_logic_model_display_name,
                                          skill_names=skill_names,
                                          prompt_template_id=agent_info.get(
                                              "prompt_template_id"),
                                          prompt_template_name=agent_info.get("prompt_template_name"))
    return agent_info


async def import_agent_impl(
    agent_info: ExportAndImportDataFormat,
    authorization: str = Header(None),
    force_import: bool = False,
    skill_name_to_id: Optional[Dict[str, int]] = None
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
                                     tenant_id=tenant_id,
                                     user_id=user_id)
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
    if import_agent_info.max_steps <= 0:
        raise ValueError(
            f"Invalid max steps: {import_agent_info.max_steps}. max steps must be greater than 0.")
    if not import_agent_info.name.isidentifier():
        raise ValueError(
            f"Invalid agent name: {import_agent_info.name}. agent name must be a valid python variable name.")

    # Resolve model_ids from the export payload.
    # Payload may carry explicit model_ids (preferred when still valid in the
    # target tenant) plus model_names for cross-tenant compatibility.
    model_ids = _resolve_model_ids_with_fallback(
        model_ids=import_agent_info.model_ids,
        model_display_names=import_agent_info.model_names,
        model_label="Model",
        tenant_id=tenant_id,
    )

    business_logic_model_id = _resolve_model_ids_with_fallback(
        model_ids=[import_agent_info.business_logic_model_id]
        if import_agent_info.business_logic_model_id is not None
        else None,
        model_display_names=[import_agent_info.business_logic_model_name]
        if import_agent_info.business_logic_model_name
        else None,
        model_label="Business logic model",
        tenant_id=tenant_id,
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
                                         "model_ids": model_ids,
                                         "business_logic_model_id": (
                                             business_logic_model_id[0]
                                             if business_logic_model_id else None
                                         ),
                                         "business_logic_model_name": import_agent_info.business_logic_model_name,
                                         "prompt_template_id": import_agent_info.prompt_template_id or SYSTEM_PROMPT_TEMPLATE_ID,
                                         "prompt_template_name": import_agent_info.prompt_template_name or SYSTEM_PROMPT_TEMPLATE_NAME,
                                         "max_steps": import_agent_info.max_steps,
                                         "requested_output_tokens": import_agent_info.requested_output_tokens,
                                         "provide_run_summary": import_agent_info.provide_run_summary,
                                         "verification_config": getattr(import_agent_info, "verification_config", None),
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
    # Auto-publish initial version V1 for market-imported agents
    try:
        publish_version_impl(
            agent_id=new_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            version_name="V1",
            release_note="Initial version from Agent Market"
        )
    except Exception as e:
        logger.warning(
            f"Failed to auto-publish version V1 for agent {new_agent_id}: {str(e)}")
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
    logger.info(
        f"clear_agent_new_mark_impl called for agent_id={agent_id}, tenant_id={tenant_id}, user_id={user_id}, affected_rows={rowcount}")
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

        # Get all agent IDs that are registered as A2A Server agents
        a2a_server_agent_ids = get_server_agent_ids(tenant_id)

        model_cache: Dict[int, Optional[dict]] = {}
        enriched_agents: list[dict] = []

        for agent in agent_list:
            if not agent["enabled"]:
                continue

            # Apply visibility filter for DEV/USER based on group overlap
            if not can_edit_all:
                agent_group_ids = set(
                    convert_string_to_list(agent.get("group_ids")))
                ingroup_permission = agent.get("ingroup_permission")
                is_creator = str(agent.get("created_by")) == str(user_id)
                # Hide agent if: no group overlap OR (ingroup_permission is PRIVATE AND user is not creator)
                if not is_creator and (len(user_group_ids.intersection(agent_group_ids)) == 0 or ingroup_permission == PERMISSION_PRIVATE):
                    continue

            # Filter out deleted models (delete_flag='Y' in model_record_t)
            raw_model_ids = agent.get("model_ids") or []
            valid_model_ids = get_valid_model_ids(raw_model_ids, tenant_id)
            agent["model_ids"] = valid_model_ids

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
            unavailable_reasons = list(
                dict.fromkeys(entry["unavailable_reasons"]))

            # Get model names from model_ids array
            model_ids = agent.get("model_ids") or []
            model_names: List[str] = []
            for mid in model_ids:
                if mid not in model_cache:
                    model_cache[mid] = get_model_by_model_id(mid, tenant_id)
                mid_info = model_cache.get(mid)
                if mid_info and mid_info.get("display_name"):
                    model_names.append(mid_info["display_name"])

            # Derive legacy model_name from the first entry in model_ids for backward compat.
            first_model_name = model_names[0] if model_names else None

            # Permission logic (ASSET_OWNER-scoped + non-ASSET_OWNER role => READ_ONLY first):
            permission = resolve_agent_list_permission(
                user_role=user_role,
                agent=agent,
                user_id=user_id,
                can_edit_all=can_edit_all,
            )

            simple_agent_list.append({
                "agent_id": agent["agent_id"],
                "name": agent["name"] if agent["name"] else agent["display_name"],
                "display_name": agent["display_name"] if agent["display_name"] else agent["name"],
                "description": agent["description"],
                "author": agent.get("author"),
                "model_ids": model_ids,
                "model_names": model_names,
                "model_name": first_model_name,
                "is_available": len(unavailable_reasons) == 0,
                "unavailable_reasons": unavailable_reasons,
                "is_new": agent.get("is_new", False),
                "group_ids": convert_string_to_list(agent.get("group_ids")),
                "permission": permission,
                "is_published": agent.get("current_version_no") is not None,
                "is_a2a_server": agent["agent_id"] in a2a_server_agent_ids,
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

    _mark_duplicates(name_groups, AgentUnavailableReason.DUPLICATE_NAME)
    _mark_duplicates(display_name_groups,
                     AgentUnavailableReason.DUPLICATE_DISPLAY_NAME)


def _collect_model_availability_reasons(agent: dict, tenant_id: str, model_cache: Dict[int, Optional[dict]]) -> list[str]:
    """
    Build a list of reasons related to model availability issues for a given agent.
    Iterates over model_ids (the canonical field) and collects one unavailable reason
    per model that is missing or not in AVAILABLE status.
    """
    reasons: list[str] = []
    model_ids = agent.get("model_ids") or []
    if model_ids:
        for mid in model_ids:
            reasons.extend(_check_single_model_availability(
                model_id=mid,
                tenant_id=tenant_id,
                model_cache=model_cache,
                reason_key=AgentUnavailableReason.MODEL_UNAVAILABLE,
            ))
    else:
        reasons.append(AgentUnavailableReason.MODEL_NOT_CONFIGURED)

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
        return False, [AgentUnavailableReason.AGENT_NOT_FOUND]

    # Check tool availability
    tool_info = search_tools_for_sub_agent(
        agent_id=agent_id, tenant_id=tenant_id)
    tool_id_list = [tool["tool_id"]
                    for tool in tool_info if tool.get("tool_id") is not None]
    if tool_id_list:
        tool_statuses = check_tool_is_available(tool_id_list)
        if not all(tool_statuses):
            unavailable_reasons.append(AgentUnavailableReason.TOOL_UNAVAILABLE)

    # Check if any tool has a selected_model_id pointing to a deleted model
    for tool in tool_info:
        params = tool.get("params") or []
        if isinstance(params, list):
            for param_def in params:
                if not isinstance(param_def, dict):
                    continue
                if param_def.get("name") == "selected_model_id":
                    selected_model_id = param_def.get("default")
                    if selected_model_id is not None:
                        model_record = get_model_by_model_id_ignore_delete(
                            selected_model_id, tenant_id)
                        if model_record is not None and model_record.get("delete_flag") == "Y":
                            unavailable_reasons.append(AgentUnavailableReason.TOOL_UNAVAILABLE)
                    break

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
    create_run_kwargs = dict(
        agent_id=agent_request.agent_id,
        minio_files=agent_request.minio_files,
        query=agent_request.query,
        history=agent_request.history,
        tenant_id=tenant_id,
        user_id=user_id,
        language=language,
        allow_memory_search=allow_memory_search,
        is_debug=agent_request.is_debug,
        override_version_no=agent_request.version_no,
        override_model_id=agent_request.model_id,
        requested_output_tokens=agent_request.requested_output_tokens,
        tool_params=agent_request.tool_params,
    )
    if agent_request._resolved_turn_resources is not None:
        create_run_kwargs["turn_resources"] = agent_request._resolved_turn_resources
    agent_run_info = await create_agent_run_info(**create_run_kwargs)

    # Mount conversation-level reusable ContextManager if enabled
    cm_config = getattr(agent_run_info.agent_config,
                        'context_manager_config', None)
    if cm_config and cm_config.enabled:
        cm = agent_run_manager.get_or_create_context_manager(
            conversation_id=str(agent_request.conversation_id),
            config=cm_config,
            max_steps=agent_run_info.agent_config.max_steps
        )
        agent_run_info.context_manager = cm

    agent_run_manager.register_agent_run(
        agent_request.conversation_id, agent_run_info, user_id)
    return agent_run_info, memory_context


# Helper function for run_agent_stream, used to save the user-side message
# before streaming begins. Assistant-side persistence is handled incrementally
# inside _stream_agent_chunks (see save_message / save_message_unit).
def save_messages(agent_request, target: str, user_id: str, tenant_id: str, messages=None):
    if target == MESSAGE_ROLE["USER"]:
        if messages is not None:
            raise ValueError("Messages should be None when saving for user.")
        submit(save_conversation_user, agent_request, user_id, tenant_id)
        return

    if target == MESSAGE_ROLE["ASSISTANT"]:
        raise ValueError(
            "save_messages no longer persists the assistant message; "
            "_stream_agent_chunks persists units incrementally via "
            "save_message_unit."
        )

    raise ValueError(f"Unsupported target for save_messages: {target!r}")


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
    cancel_poll_task = (
        asyncio.create_task(_cancel_task_on_runtime_signal(conversation_id, user_id, current_task))
        if current_task
        else None
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

    # Create channel for multi-subscriber support
    channel = await streaming_channel_manager.get_or_create_channel(
        conversation_id=agent_request.conversation_id,
        user_id=user_id
    )

    memory_enabled = False
    try:
        memory_context_preview = build_memory_context(
            user_id, tenant_id, agent_request.agent_id
        )
        memory_enabled = bool(memory_context_preview.user_config.memory_switch)

        if memory_enabled:
            # Emit start token before memory retrieval
            await channel.publish(f"data: {_memory_token(msg_start)}\n\n")
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
            await channel.publish(f"data: {_memory_token(msg_done)}\n\n")
            yield f"data: {_memory_token(msg_done)}\n\n"

        async for data_chunk in _stream_agent_chunks(
            agent_request=agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            agent_run_info=agent_run_info,
            memory_ctx=memory_context,
            channel=channel,
        ):
            yield data_chunk

    except MemoryPreparationException:
        # Memory retrieval failure: emit failure token when memory is enabled, and continue without blocking
        if memory_enabled:
            await channel.publish(f"data: {_memory_token(msg_fail)}\n\n")
            yield f"data: {_memory_token(msg_fail)}\n\n"

        try:
            # Fallback to the no-memory streaming path, which internally handles
            async for data_chunk in generate_stream_no_memory(
                agent_request,
                user_id=user_id,
                tenant_id=tenant_id,
                channel=channel,
            ):
                yield data_chunk
        except Exception as run_exc:
            logger.error(
                "Agent run error after memory failure: %r",
                run_exc,
                exc_info=True,
            )
            await channel.publish(_safe_agent_stream_error_chunk())
            yield _safe_agent_stream_error_chunk()
            return
    except Exception as stream_exc:
        logger.error(
            "Generate stream with memory error: %r",
            stream_exc,
            exc_info=True,
        )
        await channel.publish(_safe_agent_stream_error_chunk())
        yield _safe_agent_stream_error_chunk()
        return
    finally:
        if cancel_poll_task and not cancel_poll_task.done():
            cancel_poll_task.cancel()
        # Always unregister preprocess task
        preprocess_manager.unregister_preprocess_task(task_id)


# Helper function for run_agent_stream, used when user memory is disabled (no memory tokens)
async def generate_stream_no_memory(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    channel: Optional[Any] = None,
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
        channel=channel,
    ):
        yield data_chunk


def _detect_resume_position(
    conversation_id: int,
    user_id: str,
) -> Dict[str, Any]:
    """
    Determine the position to resume streaming from.

    This function queries the database to check if there's an in-progress
    streaming message for the given conversation. Used when frontend reconnects
    after tab switch.

    Returns:
        Dict containing:
            - should_resume: bool - whether we should resume streaming
            - message_id: int - the assistant message ID
            - message_status: str - current status (streaming/completed/failed/stopped)
            - resume_from_unit_index: int - the unit index to resume from
            - reason: str - explanation of the decision
    """
    latest_msg = get_latest_assistant_message(conversation_id, user_id)

    if latest_msg is None:
        return {
            'should_resume': False,
            'message_id': None,
            'message_status': None,
            'resume_from_unit_index': None,
            'reason': 'no_assistant_message'
        }

    message_status = latest_msg.get('status')
    message_id = latest_msg['message_id']

    # Check if channel exists and is still active
    channel = streaming_channel_manager.get_channel(conversation_id, user_id)
    channel_active = channel is not None and not channel.is_completed

    if message_status == 'streaming':
        # Backend still running - get last unit position
        last_unit = get_last_unit_for_message(message_id)
        resume_from = last_unit['unit_index'] + 1 if last_unit else 0
        return {
            'should_resume': True,
            'message_id': message_id,
            'message_status': message_status,
            'resume_from_unit_index': resume_from,
            'resume_message_id': message_id,
            'reason': 'backend_streaming'
        }
    elif channel_active:
        # Message shows completed but channel is still active - resume to get remaining chunks
        # This handles edge case where message status was updated but channel not yet cleaned up
        last_unit = get_last_unit_for_message(message_id)
        resume_from = last_unit['unit_index'] + 1 if last_unit else 0
        return {
            'should_resume': True,
            'message_id': message_id,
            'message_status': message_status,
            'resume_from_unit_index': resume_from,
            'resume_message_id': message_id,
            'reason': 'channel_active'
        }
    else:
        # Backend finished - no more chunks to stream
        return {
            'should_resume': False,
            'message_id': message_id,
            'message_status': message_status,
            'resume_from_unit_index': None,
            'resume_message_id': None,
            'reason': f'backend_{message_status}'
        }


async def run_agent_stream(
    agent_request: AgentRequest,
    http_request: Request,
    authorization: str,
    user_id: str = None,
    tenant_id: str = None,
    skip_user_save: bool = False,
    resume: bool = False,
):
    """
    Start an agent run and stream responses.
    If user_id or tenant_id is provided, authorization will be overridden. (Useful in northbound apis)

    Args:
        resume: If True, check for existing streaming message and continue from where it left off
    """
    resolved_user_id, resolved_tenant_id, language = _resolve_user_tenant_language(
        authorization=authorization,
        http_request=http_request,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    _resolve_agent_request_turn_resources(agent_request, resolved_tenant_id)

    # Auto-create conversation when conversation_id is not provided.
    # Skip in debug mode: debug runs are ephemeral and must not persist
    # conversations, titles, or messages to the user's history.
    is_new_conversation = False
    if agent_request.is_debug:
        logger.info(
            "Skipping conversation auto-create: is_debug=True (conversation_id=%s)",
            agent_request.conversation_id,
        )
    elif agent_request.conversation_id is None:
        default_title = DEFAULT_EN_TITLE if language == LANGUAGE["EN"] else DEFAULT_ZH_TITLE
        conversation_data = create_new_conversation(
            title=default_title,
            user_id=resolved_user_id,
            agent_id=agent_request.agent_id,
        )
        agent_request.conversation_id = conversation_data["conversation_id"]
        is_new_conversation = True
        logger.info(
            "Auto-created conversation_id=%s for user=%s (new conversation)",
            agent_request.conversation_id,
            resolved_user_id,
        )

    if (
        not agent_request.is_debug
        and not resume
        and not is_new_conversation
        and agent_request.conversation_id is not None
        and agent_request.agent_id is not None
    ):
        update_conversation_agent_id_service(
            conversation_id=agent_request.conversation_id,
            agent_id=agent_request.agent_id,
            user_id=resolved_user_id,
        )

    # Resume mode: check for existing streaming message
    if resume:
        resume_info = _detect_resume_position(
            conversation_id=agent_request.conversation_id,
            user_id=resolved_user_id,
        )

        if not resume_info['should_resume']:
            # Backend already finished
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    'status': resume_info['message_status'],
                    'message': f"Stream already {resume_info['message_status']}: {resume_info['reason']}",
                }
            )

        # Check if the agent is still running by querying the agent_run_manager
        existing_run_info = agent_run_manager.get_agent_run_info(
            user_id=resolved_user_id,
            conversation_id=agent_request.conversation_id
        )
        run_state = await runtime_state_service.get_run_state_async(
            user_id=resolved_user_id,
            conversation_id=agent_request.conversation_id,
        )
        is_remote_running = run_state.get("status") == "running"

        if existing_run_info is None and not is_remote_running:
            # Agent has finished while frontend was disconnected
            # Update message status to completed if it's still streaming
            try:
                update_message_status(
                    message_id=resume_info['message_id'],
                    status='completed'
                )
            except Exception:
                pass

            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    'status': 'completed',
                    'message': 'Agent finished during disconnection',
                }
            )

        # Agent is still running - subscribe to the channel to receive new chunks
        channel = streaming_channel_manager.get_channel(
            conversation_id=agent_request.conversation_id,
            user_id=resolved_user_id
        )
        last_unit_index = resume_info["resume_from_unit_index"] - 1

        def _resume_status_chunk(replay_chunk_count: int) -> str:
            payload = {
                'status': 'resumed',
                'last_unit_index': last_unit_index,
                'replay_chunk_count': replay_chunk_count,
            }
            return f"data: {json.dumps(payload)}\n\n"

        def _resume_completed_chunk(status: str = "completed") -> str:
            payload = {
                'status': status,
                'last_unit_index': last_unit_index,
            }
            return f"data: {json.dumps(payload)}\n\n"

        if channel is None:
            if runtime_state_service.enabled and is_remote_running:
                async def redis_channel_stream():
                    replay_events = await runtime_state_service.read_stream_events_async(
                        user_id=resolved_user_id,
                        conversation_id=agent_request.conversation_id,
                    )
                    replay_chunk_count = len(replay_events)

                    yield STREAM_STATUS_EVENT
                    yield _resume_status_chunk(replay_chunk_count)

                    last_event_id = "0-0"
                    for event_id, chunk in replay_events:
                        last_event_id = event_id
                        if chunk:
                            yield chunk

                    while True:
                        events = await runtime_state_service.wait_for_stream_events_async(
                            user_id=resolved_user_id,
                            conversation_id=agent_request.conversation_id,
                            last_id=last_event_id,
                        )
                        for event_id, chunk in events:
                            last_event_id = event_id
                            if chunk:
                                yield chunk

                        stream_status = await runtime_state_service.get_stream_status_async(
                            user_id=resolved_user_id,
                            conversation_id=agent_request.conversation_id,
                        )
                        latest_run_state = await runtime_state_service.get_run_state_async(
                            user_id=resolved_user_id,
                            conversation_id=agent_request.conversation_id,
                        )
                        if stream_status.get("status") or latest_run_state.get("status") in {
                            "completed",
                            "failed",
                            "stopped",
                        }:
                            break

                    terminal_status = stream_status.get("status") or latest_run_state.get("status") or "completed"
                    yield STREAM_STATUS_EVENT
                    yield _resume_completed_chunk(terminal_status)

                return StreamingResponse(
                    redis_channel_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Stream-Status": "resumed",
                        "X-Last-Unit-Index": str(resume_info['resume_from_unit_index']),
                    },
                )

            # No channel exists, agent might be in a different state
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    'status': 'streaming',
                    'message': 'Stream channel not found',
                }
            )

        # Subscribe to the channel and stream chunks to the frontend
        async def channel_stream():
            # Include the current buffer size so frontend knows how many chunks to skip
            replay_chunk_count = channel.history_size if channel else 0

            # Emit status event first with chunk count for skip tracking
            yield STREAM_STATUS_EVENT
            yield _resume_status_chunk(replay_chunk_count)

            # Use subscribe_with_history(0) to replay ALL chunks from the buffer
            # This ensures no chunks are lost even if frontend disconnected during streaming
            # The frontend skips all chunks until replay_chunk_count is reached
            async for chunk in channel.subscribe_with_history(0):
                yield chunk

            # Mark as complete when channel ends
            yield STREAM_STATUS_EVENT
            yield _resume_completed_chunk()

        return StreamingResponse(
            channel_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Stream-Status": "resumed",
                "X-Last-Unit-Index": str(resume_info['resume_from_unit_index']),
            },
        )

    # Normal mode: start new stream
    await runtime_state_service.reset_stream_async(
        user_id=resolved_user_id,
        conversation_id=agent_request.conversation_id,
    )

    if not agent_request.is_debug and not skip_user_save:
        save_messages(
            agent_request,
            target=MESSAGE_ROLE["USER"],
            user_id=resolved_user_id,
            tenant_id=resolved_tenant_id,
        )

    memory_ctx_preview = build_memory_context(
        resolved_user_id, resolved_tenant_id, agent_request.agent_id, skip_query=agent_request.is_debug
    )
    memory_enabled = memory_ctx_preview.user_config.memory_switch

    agent_metadata = monitoring_manager.bind_agent_context(AgentRunMetadata(
        agent_id=agent_request.agent_id,
        conversation_id=agent_request.conversation_id,
        user_id=resolved_user_id,
        tenant_id=resolved_tenant_id,
        query=agent_request.query,
        is_debug=agent_request.is_debug,
        language=language,
        memory_enabled=memory_enabled,
        history_count=len(
            agent_request.history) if agent_request.history else 0,
        minio_files_count=len(
            agent_request.minio_files) if agent_request.minio_files else 0,
        extra_metadata={
            "agent_share_option": getattr(
                memory_ctx_preview.user_config,
                "agent_share_option",
                "unknown",
            ),
            "skip_user_save": skip_user_save,
            "has_override_user_id": user_id is not None,
            "has_override_tenant_id": tenant_id is not None,
        },
    ))

    use_memory_stream = memory_enabled and not agent_request.is_debug

    if use_memory_stream:
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

    async def stream_with_agent_context():
        try:
            # Emit conversation_created event for new conversations
            if is_new_conversation:
                yield f'data: {{"type": "conversation_created", "content": {{"conversation_id": {agent_request.conversation_id}}}}}\n\n'

            with agent_monitoring_context(agent_metadata):
                async for data_chunk in stream_gen:
                    yield data_chunk
        except Exception as stream_exc:
            logger.error(
                "Agent stream response error: %r",
                stream_exc,
                exc_info=True,
            )
            yield _safe_agent_stream_error_chunk()
        finally:
            # Auto-generate title for new conversations after stream completes
            if is_new_conversation:
                try:
                    await generate_conversation_title_service(
                        conversation_id=agent_request.conversation_id,
                        question=agent_request.query,
                        user_id=resolved_user_id,
                        tenant_id=resolved_tenant_id,
                        language=language,
                    )
                except Exception as title_exc:
                    logger.warning(
                        "Failed to auto-generate title for conversation_id=%s: %r",
                        agent_request.conversation_id,
                        title_exc,
                    )

    return StreamingResponse(
        stream_with_agent_context(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def run_agent_background(
    agent_request: AgentRequest,
    user_id: str,
    tenant_id: str,
    language: str = LANGUAGE["ZH"],
    skip_user_save: bool = False,
) -> Dict[str, Any]:
    """
    Run an agent without returning an SSE response.

    This path is used by background automation tasks. It reuses the same
    preparation, monitoring, memory and message persistence flow as
    run_agent_stream, but consumes generated chunks internally.
    """
    if not agent_request.conversation_id:
        raise ValueError("conversation_id is required for background agent runs")

    _resolve_agent_request_turn_resources(agent_request, tenant_id)

    if not agent_request.is_debug and not skip_user_save:
        save_messages(
            agent_request,
            target=MESSAGE_ROLE["USER"],
            user_id=user_id,
            tenant_id=tenant_id,
        )

    memory_ctx_preview = build_memory_context(
        user_id, tenant_id, agent_request.agent_id, skip_query=agent_request.is_debug
    )
    memory_enabled = memory_ctx_preview.user_config.memory_switch

    agent_metadata = monitoring_manager.bind_agent_context(AgentRunMetadata(
        agent_id=agent_request.agent_id,
        conversation_id=agent_request.conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        query=agent_request.query,
        is_debug=agent_request.is_debug,
        language=language,
        memory_enabled=memory_enabled,
        history_count=len(agent_request.history) if agent_request.history else 0,
        minio_files_count=len(agent_request.minio_files) if agent_request.minio_files else 0,
        extra_metadata={
            "background": True,
            "skip_user_save": skip_user_save,
            "agent_share_option": getattr(
                memory_ctx_preview.user_config,
                "agent_share_option",
                "unknown",
            ),
        },
    ))

    if memory_enabled and not agent_request.is_debug:
        stream_gen = generate_stream_with_memory(
            agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
        )
    else:
        stream_gen = generate_stream_no_memory(
            agent_request,
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
        )

    chunks = 0
    with agent_monitoring_context(agent_metadata):
        async for _ in stream_gen:
            chunks += 1

    latest_message = get_latest_assistant_message(agent_request.conversation_id, user_id)
    return {
        "conversation_id": agent_request.conversation_id,
        "assistant_message_id": latest_message.get("message_id") if latest_message else None,
        "chunks": chunks,
    }


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
        logging.info(message)
        return {"status": "success", "message": message, "already_stopped": True}


def is_agent_running(conversation_id: int, user_id: str) -> bool:
    return agent_run_manager.get_agent_run_info(conversation_id, user_id) is not None


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


def get_agent_by_name_impl(agent_name: str, tenant_id: str) -> dict:
    """
    Resolve agent id and latest published version by agent name.

    Returns:
        dict with agent_id and latest_version_no (may be None)
    """
    if not agent_name:
        raise Exception("agent_name required")
    try:
        agent_id = search_agent_id_by_agent_name(agent_name, tenant_id)
        versions = query_version_list(agent_id, tenant_id)
        latest_version = versions[0]["version_no"] if versions else None
        return {"agent_id": agent_id, "latest_version_no": latest_version}
    except Exception as _:
        logger.error(
            f"Failed to find agent '{agent_name}' in tenant {tenant_id}")
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


async def export_agent_with_skills_impl(
    agent_id: int,
    authorization: str,
    version_no: int = 0,
) -> dict:
    """Export an agent, returning a ZIP if it has skill instances, otherwise a plain dict.

    The response is either:
      - A dict with {"_zip": True, "data": bytes, "filename": str} when the agent has skills
      - ExportAndImportDataFormat as a plain dict when the agent has no skills
    """
    user_id, tenant_id, _ = get_current_user_info(authorization)

    skill_zip_entries = collect_skill_zip_entries(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )

    if not skill_zip_entries:
        return await export_agent_dict_impl(
            agent_id, authorization, version_no=version_no
        )

    agent_json_str = await export_agent_impl(
        agent_id, authorization, version_no=version_no
    )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("agent.json", agent_json_str)
        for entry in skill_zip_entries:
            skill_zip_bytes = base64.b64decode(entry.skill_zip_base64)
            zf.writestr(f"skills/{entry.skill_name}.zip", skill_zip_bytes)

    zip_buffer.seek(0)
    zip_data = zip_buffer.read()

    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )
    agent_name = agent_info.get(
        "name", "anonymous") if agent_info else "anonymous"

    filename = f"{agent_name}.zip"

    return {
        "_zip": True,
        "data": zip_data,
        "filename": filename
    }


async def import_agent_with_skills_impl(
    agent_info: "ExportAndImportDataFormat",
    skills: List[SkillZipEntry],
    authorization: str,
    force_import: bool = False
):
    """Import an agent with skills bundled from a ZIP export.

    For each skill in the bundle:
      1. Check if a skill with the same name already exists in the target tenant.
      2. If duplicates exist, raise SkillDuplicateError (do not create anything).
      3. If no duplicates, create the skill from ZIP bytes via SkillService.
      4. Create a SkillInstance linking the new skill_id to the new agent_id.

    Then proceeds with the standard agent import flow using the mapped skill IDs.
    """
    from services.skill_service import SkillService

    user_id, tenant_id, _ = get_current_user_info(authorization)

    skill_name_to_zip_base64 = {
        entry.skill_name: entry.skill_zip_base64 for entry in skills}

    existing_skills = skill_db.list_skills(tenant_id)
    existing_skill_names = {s.get("name") for s in existing_skills}

    import_skill_names = set(skill_name_to_zip_base64.keys())
    duplicate_names = list(import_skill_names & existing_skill_names)

    if duplicate_names:
        raise SkillDuplicateError(duplicate_names)

    skill_name_to_id: Dict[str, int] = {}
    skill_service = SkillService(tenant_id=tenant_id)

    for skill_name, zip_base64 in skill_name_to_zip_base64.items():
        zip_bytes = base64.b64decode(zip_base64)
        result = skill_service.create_skill_from_zip_bytes(
            zip_bytes=zip_bytes,
            skill_name=skill_name,
            source="导入",
            user_id=user_id,
            tenant_id=tenant_id,
            skip_duplicate_check=True
        )
        skill_name_to_id[skill_name] = result.get("skill_id")

    agent_id_mapping = await import_agent_impl(
        agent_info, authorization, force_import,
        skill_name_to_id=skill_name_to_id
    )

    main_agent_id = agent_id_mapping.get(agent_info.agent_id)
    if main_agent_id:
        for skill_name, new_skill_id in skill_name_to_id.items():
            skill_db.create_or_update_skill_by_skill_info(
                skill_info=SkillInstanceInfoRequest(
                    skill_id=new_skill_id,
                    agent_id=main_agent_id,
                    enabled=True,
                    version_no=0
                ),
                tenant_id=tenant_id,
                user_id=user_id,
                version_no=0
            )

    return agent_id_mapping
