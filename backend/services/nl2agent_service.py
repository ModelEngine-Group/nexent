"""Business logic for the ephemeral NL2Agent runtime."""

import asyncio
import json
import logging
import re
import threading
import unicodedata
from collections.abc import AsyncIterator
from typing import Any

from nexent.core.agents.agent_model import AgentHistory, AgentRunInfo
from nexent.core.agents.run_agent import agent_run
from nexent.core.utils.observer import MessageObserver
from rapidfuzz import fuzz

from agents.create_agent_info import (
    create_model_config_list,
    join_minio_file_description_to_query,
)
from agents.nl2agent_agent import (
    GeneratedAgentDraft,
    InstalledMcpToolRecommendation,
    build_search_installed_mcp_tools,
    create_nl2agent_agent_config,
)
from consts.model import HistoryItem, NL2AgentRunRequest, ToolSourceEnum
from database.tool_db import query_all_tools

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


def _build_draft_query(draft: GeneratedAgentDraft) -> str:
    return _normalize_search_text(
        " ".join(
            part
            for part in (
                draft.display_name,
                draft.description,
                draft.duty_prompt,
                draft.constraint_prompt,
                draft.few_shots_prompt or "",
            )
            if part
        )
    )


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


def search_installed_mcp_tools_for_tenant(
    tenant_id: str,
    draft: GeneratedAgentDraft,
    limit: int = MAX_RECOMMENDATIONS,
) -> list[InstalledMcpToolRecommendation]:
    """Return the best installed MCP tool matches for one tenant."""

    query = _build_draft_query(draft)
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
            description=str(tool.get("description") or ""),
            usage=str(tool.get("usage") or ""),
            labels=_normalize_labels(tool.get("labels")),
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
) -> AgentRunInfo:
    """Build all request-scoped NL2Agent runtime objects in memory."""

    final_query = await join_minio_file_description_to_query(
        minio_files=request.minio_files,
        query=request.query,
        history=request.history,
    )
    model_config_list = await create_model_config_list(tenant_id)
    search_tool = build_search_installed_mcp_tools(
        tenant_id=tenant_id,
        language=language,
        search_fn=search_installed_mcp_tools_for_tenant,
    )
    agent_config = create_nl2agent_agent_config(language, search_tool)

    return AgentRunInfo(
        query=final_query,
        model_config_list=model_config_list,
        observer=MessageObserver(lang=language),
        agent_config=agent_config,
        mcp_host=None,
        history=_convert_history(request.history),
        stop_event=threading.Event(),
        enable_planning=False,
        sandbox_config=None,
        redis_client=None,
    )


async def create_nl2agent_stream(
    request: NL2AgentRunRequest,
    tenant_id: str,
    language: str,
) -> AsyncIterator[str]:
    """Create an SSE-compatible stream for one ephemeral NL2Agent run."""

    run_info = await build_nl2agent_run_info(request, tenant_id, language)

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
