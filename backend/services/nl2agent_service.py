"""Business logic for the ephemeral NL2Agent runtime."""

import ast
import asyncio
import json
import logging
import re
import threading
import unicodedata
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin

from nexent.core.agents.agent_model import AgentHistory, AgentRunInfo
from nexent.core.agents.context import ContextManagerConfig
from nexent.core.agents.run_agent import agent_run
from nexent.core.utils.observer import MessageObserver
from rapidfuzz import fuzz

from agents.create_agent_info import (
    _resolve_input_budget,
    _resolve_safe_input_budget,
    create_model_config_list,
    join_minio_file_description_to_query,
)
from agents.nl2agent_agent import create_nl2agent_agent_config
from consts.const import (
    CAN_EDIT_ALL_USER_ROLES,
    LOCAL_MCP_SERVER,
    MODEL_CONFIG_MAPPING,
    PERMISSION_EDIT,
)
from consts.model import HistoryItem, ModelConnectStatusEnum, NL2AgentRunRequest, ToolSourceEnum
from database.agent_db import (
    create_agent,
    query_agent_records_for_nl2agent,
    query_all_agent_info_by_tenant_id,
    update_agent_draft_fields,
)
from database.tool_db import query_all_tools
from database.user_tenant_db import get_user_role_by_tenant
from services.asset_owner_visibility import resolve_agent_list_permission
from services.prompt_template_service import (
    SYSTEM_PROMPT_TEMPLATE_ID,
    SYSTEM_PROMPT_TEMPLATE_NAME,
)
from tool_collection.mcp.nl2agent_mcp_tools import (
    AgentDraftFields,
    InstalledMcpToolRecommendation,
)
from utils.config_utils import tenant_config_manager
from utils.context_utils import build_authorized_context_input

logger = logging.getLogger(__name__)

MINIMUM_RECOMMENDATION_SCORE = 0.45
MAX_RECOMMENDATIONS = 5
AGENT_DRAFT_FIELD_ORDER = (
    "name",
    "display_name",
    "description",
    "business_description",
    "duty_prompt",
    "constraint_prompt",
    "few_shots_prompt",
    "greeting_message",
    "example_questions",
)
AGENT_DRAFT_CREATE_REQUIRED_FIELDS = (
    "name",
    "display_name",
    "description",
    "business_description",
)


class Nl2AgentDraftSaveError(Exception):
    """Stable service error consumed by the MCP boundary."""

    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _ordered_updated_fields(fields: AgentDraftFields) -> list[str]:
    return [name for name in AGENT_DRAFT_FIELD_ORDER if name in fields.model_fields_set]


def _resolve_default_draft_model(tenant_id: str) -> int:
    default_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id,
    )
    model_id = default_model.get("model_id") if isinstance(default_model, dict) else None
    model_type = default_model.get("model_type") if isinstance(default_model, dict) else None
    connect_status = (
        ModelConnectStatusEnum.get_value(default_model.get("connect_status"))
        if isinstance(default_model, dict)
        else ModelConnectStatusEnum.UNAVAILABLE.value
    )
    if (
        not isinstance(model_id, int)
        or model_id <= 0
        or model_type not in (None, "llm")
        or connect_status != ModelConnectStatusEnum.AVAILABLE.value
    ):
        raise Nl2AgentDraftSaveError("default_model_missing")
    return model_id


def _create_agent_draft_from_fields(
    fields: AgentDraftFields,
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    patch = fields.model_dump(mode="python", exclude_unset=True)
    missing = [
        field_name
        for field_name in AGENT_DRAFT_CREATE_REQUIRED_FIELDS
        if not isinstance(patch.get(field_name), str) or not patch[field_name].strip()
    ]
    if missing:
        raise Nl2AgentDraftSaveError("basic_fields_required")

    default_model_id = _resolve_default_draft_model(tenant_id)

    # Reuse the ordinary Agent path's deterministic suffix helpers without
    # invoking its optional LLM-based regeneration flow.
    from services.agent_service import (
        _check_agent_display_name_duplicate,
        _check_agent_name_duplicate,
        _generate_unique_agent_name_with_suffix,
        _generate_unique_display_name_with_suffix,
        _get_user_group_ids,
    )

    agents_cache = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)
    if _check_agent_name_duplicate(
        patch["name"], tenant_id=tenant_id, agents_cache=agents_cache
    ):
        patch["name"] = _generate_unique_agent_name_with_suffix(
            patch["name"], tenant_id=tenant_id, agents_cache=agents_cache
        )
    if _check_agent_display_name_duplicate(
        patch["display_name"], tenant_id=tenant_id, agents_cache=agents_cache
    ):
        patch["display_name"] = _generate_unique_display_name_with_suffix(
            patch["display_name"], tenant_id=tenant_id, agents_cache=agents_cache
        )

    patch.update(
        model_ids=[default_model_id],
        prompt_template_id=SYSTEM_PROMPT_TEMPLATE_ID,
        prompt_template_name=SYSTEM_PROMPT_TEMPLATE_NAME,
        group_ids=_get_user_group_ids(user_id, tenant_id),
        max_steps=15,
        is_main_agent=True,
        provide_run_summary=False,
        enabled=True,
    )
    try:
        created = create_agent(agent_info=patch, tenant_id=tenant_id, user_id=user_id)
    except Exception as exc:
        logger.exception("Failed to create NL2Agent AgentInfo draft")
        raise Nl2AgentDraftSaveError("draft_save_failed", retryable=True) from exc

    return {
        "status": "success",
        "agent_id": created["agent_id"],
        "created": True,
        "updated_fields": _ordered_updated_fields(fields),
    }


def _update_agent_draft_from_fields(
    agent_id: int,
    fields: AgentDraftFields,
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    records = query_agent_records_for_nl2agent(agent_id=agent_id, tenant_id=tenant_id)
    if not records:
        raise Nl2AgentDraftSaveError("agent_not_found")

    draft = next((record for record in records if record.get("version_no") == 0), None)
    if draft is None:
        raise Nl2AgentDraftSaveError("agent_not_draft")
    if draft.get("delete_flag") == "Y":
        raise Nl2AgentDraftSaveError("agent_deleted")

    user_role = get_user_role_by_tenant(user_id=user_id, tenant_id=tenant_id)
    permission = resolve_agent_list_permission(
        user_role=user_role,
        agent=draft,
        user_id=user_id,
        can_edit_all=user_role.upper() in CAN_EDIT_ALL_USER_ROLES,
    )
    if permission != PERMISSION_EDIT:
        raise Nl2AgentDraftSaveError("agent_read_only")

    patch = fields.model_dump(mode="python", exclude_unset=True)
    try:
        rowcount = update_agent_draft_fields(
            agent_id=agent_id,
            tenant_id=tenant_id,
            fields=patch,
        )
    except Exception as exc:
        logger.exception("Failed to update NL2Agent AgentInfo draft")
        raise Nl2AgentDraftSaveError("draft_save_failed", retryable=True) from exc
    if rowcount != 1:
        raise Nl2AgentDraftSaveError("draft_save_failed", retryable=True)

    return {
        "status": "success",
        "agent_id": agent_id,
        "created": False,
        "updated_fields": _ordered_updated_fields(fields),
    }


def save_agent_draft_fields_impl(
    agent_id: int | None,
    fields: AgentDraftFields,
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Create or partially update one ordinary tenant-owned AgentInfo draft."""
    if agent_id is None:
        return _create_agent_draft_from_fields(fields, tenant_id, user_id)
    return _update_agent_draft_from_fields(agent_id, fields, tenant_id, user_id)


def _normalize_search_text(value: Any) -> str:
    """Normalize catalog text before fuzzy matching."""

    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


def _normalize_labels(value: Any) -> list[str]:
    """Return a safe list of display labels."""

    if not isinstance(value, list):
        return []
    return [str(label) for label in value if label is not None]


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_input_strings(value: Any) -> Any:
    if isinstance(value, str):
        return _collapse_whitespace(value)
    if isinstance(value, dict):
        return {
            key: _normalize_input_strings(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_input_strings(item) for item in value]
    return value


def _parse_tool_inputs(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return {}
    else:
        return {}

    if not isinstance(parsed, dict):
        return {}
    return _normalize_input_strings(parsed)


def _build_tool_document(tool: dict[str, Any]) -> str:
    labels = " ".join(_normalize_labels(tool.get("labels")))
    return _normalize_search_text(
        " ".join(
            str(part)
            for part in (
                tool.get("name") or "",
                tool.get("origin_name") or "",
                tool.get("description") or "",
                labels,
                tool.get("usage") or "",
            )
            if part
        )
    )


def search_installed_mcp_tools_by_query(
    tenant_id: str,
    query_text: str,
    limit: int = MAX_RECOMMENDATIONS,
) -> list[InstalledMcpToolRecommendation]:
    """Return the best installed MCP tool matches for normalized query text."""

    query = _normalize_search_text(query_text)
    scored_tools: list[tuple[float, int, dict[str, Any]]] = []

    for tool in query_all_tools(tenant_id=tenant_id):
        if tool.get("source") != ToolSourceEnum.MCP.value:
            continue
        if tool.get("is_available") is not True:
            continue

        document = _build_tool_document(tool)
        if not document:
            continue

        score = (
            max(
                fuzz.WRatio(query, document),
                fuzz.token_set_ratio(query, document),
            )
            / 100
        )
        if score < MINIMUM_RECOMMENDATION_SCORE:
            continue

        tool_id = int(tool["tool_id"])
        scored_tools.append((score, tool_id, tool))

    scored_tools.sort(key=lambda item: (-item[0], item[1]))
    result_limit = max(0, min(limit, MAX_RECOMMENDATIONS))

    return [
        InstalledMcpToolRecommendation(
            tool_id=tool_id,
            name=str(tool.get("name") or ""),
            origin_name=(
                str(tool["origin_name"])
                if tool.get("origin_name") is not None
                else None
            ),
            description=_collapse_whitespace(
                str(tool.get("description") or "")
            ),
            usage=str(tool.get("usage") or ""),
            labels=_normalize_labels(tool.get("labels")),
            inputs=_parse_tool_inputs(tool.get("inputs")),
            score=round(score, 4),
        )
        for score, tool_id, tool in scored_tools[:result_limit]
    ]


def _convert_history(history: list[HistoryItem] | None) -> list[AgentHistory]:
    if not history:
        return []
    return [
        AgentHistory(role=item.role, content=item.content)
        for item in history
        if item.role in {"user", "assistant"}
    ]


async def build_nl2agent_run_info(
    request: NL2AgentRunRequest,
    tenant_id: str,
    language: str,
    authorization: str | None,
) -> AgentRunInfo:
    """Build all request-scoped NL2Agent runtime objects in memory."""

    final_query = await join_minio_file_description_to_query(
        minio_files=request.minio_files,
        query=request.query,
        history=request.history,
    )
    model_config_list = await create_model_config_list(tenant_id)
    agent_config = create_nl2agent_agent_config(language)
    default_model = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"],
        tenant_id=tenant_id,
    )
    input_budget, capacity_snapshot, resolved_capacity_snapshot = (
        _resolve_input_budget(default_model)
    )
    safe_input_budget_snapshot = _resolve_safe_input_budget(
        capacity_snapshot=resolved_capacity_snapshot,
        tenant_id=tenant_id,
        agent_requested_output_tokens=None,
        request_requested_output_tokens=None,
    )
    if safe_input_budget_snapshot is not None:
        soft_input_budget_tokens = safe_input_budget_snapshot[
            "soft_input_budget_tokens"
        ]
        hard_input_budget_tokens = safe_input_budget_snapshot[
            "hard_input_budget_tokens"
        ]
        token_threshold = soft_input_budget_tokens
    else:
        soft_input_budget_tokens = 0
        hard_input_budget_tokens = 0
        token_threshold = input_budget

    context_window_tokens = (
        resolved_capacity_snapshot.context_window_tokens
        if resolved_capacity_snapshot is not None
        and resolved_capacity_snapshot.context_window_tokens is not None
        else input_budget
    )
    agent_config.context_manager_config = ContextManagerConfig(
        token_threshold=token_threshold,
        context_window_tokens=context_window_tokens,
        soft_input_budget_tokens=soft_input_budget_tokens,
        hard_input_budget_tokens=hard_input_budget_tokens,
    )
    agent_config.capacity_snapshot = capacity_snapshot
    agent_config.safe_input_budget_snapshot = safe_input_budget_snapshot
    mcp_config: dict[str, Any] = {
        "url": urljoin(LOCAL_MCP_SERVER, "sse"),
        "transport": "sse",
    }
    if authorization:
        mcp_config["headers"] = {"Authorization": authorization}

    run_info = AgentRunInfo(
        query=final_query,
        model_config_list=model_config_list,
        observer=MessageObserver(
            lang=language,
            enable_nl2a_wrapper=True,
        ),
        agent_config=agent_config,
        mcp_host=[mcp_config],
        history=_convert_history(request.history),
        stop_event=threading.Event(),
        capacity_snapshot=capacity_snapshot,
        safe_input_budget_snapshot=safe_input_budget_snapshot,
        enable_planning=False,
        sandbox_config=None,
        redis_client=None,
    )
    run_info.context_input = build_authorized_context_input(run_info)
    return run_info


async def create_nl2agent_stream(
    request: NL2AgentRunRequest,
    tenant_id: str,
    language: str,
    authorization: str | None,
) -> AsyncIterator[str]:
    """Create an SSE-compatible stream for one ephemeral NL2Agent run."""

    run_info = await build_nl2agent_run_info(
        request=request,
        tenant_id=tenant_id,
        language=language,
        authorization=authorization,
    )

    async def generate() -> AsyncIterator[str]:
        try:
            async for chunk in agent_run(run_info):
                yield f"data: {chunk}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("NL2Agent execution failed")
            error_payload = json.dumps(
                {
                    "type": "error",
                    "content": "NL2Agent execution failed.",
                },
                ensure_ascii=False,
            )
            yield f"data: {error_payload}\n\n"
        finally:
            run_info.stop_event.set()

    return generate()
