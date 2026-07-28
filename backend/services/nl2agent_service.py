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
from agents.nl2agent_agent import (
    InstalledMcpToolRecommendation,
    create_nl2agent_agent_config,
)
from consts.const import LOCAL_MCP_SERVER, MODEL_CONFIG_MAPPING
from consts.model import HistoryItem, NL2AgentRunRequest, ToolSourceEnum
from database.tool_db import query_all_tools
from utils.config_utils import tenant_config_manager

logger = logging.getLogger(__name__)

MINIMUM_RECOMMENDATION_SCORE = 0.45
MAX_RECOMMENDATIONS = 5


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

    return AgentRunInfo(
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
