"""Search memory tool for the new Memory system.

This tool is invoked by the agent to retrieve relevant memories. Under the
new Memory architecture:

- Searches default to the agent's own short-term memory (vector search).
- Tenant / user long-term memories can be exposed as full-context (handled by
  the backend ``memory_context_service``); the tool surfaces a stable prompt
  contract regardless of which retrieval backend is in use.
- When the backend wires a ``memory_context_service`` into the tool
  metadata, the tool routes results through the Phase 4 retrieval pipeline
  (``MemoryContextService.build_context``) so that score fusion,
  temporal decay, MMR deduplication, and token-budget selection are all
  applied. Otherwise it falls back to the legacy direct
  ``MemoryService.search_memory`` call.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from smolagents.tools import Tool
from pydantic import Field

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory


logger = logging.getLogger("search_memory_tool")


def _run_coroutine(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class SearchMemoryTool(Tool):
    """Tool that searches memories for the current agent.

    The new architecture enforces:
    ``agent_id`` is part of every search so that sub-agents and parent agents
    do not share short-term memory.
    """

    name = "search_memory"
    description = (
        "Search memory for relevant information from previous interactions. "
        "Use this when you need context about the user's preferences, past "
        "decisions, or previously discussed topics that aren't in the current "
        "conversation. The system already provides some memory context "
        "automatically -- use this tool when you need to search for specific "
        "information not already available."
    )
    description_zh = (
        "在记忆中搜索来自之前交互的相关信息。"
        "当你需要了解用户的偏好、过去的决策或当前对话中未提及的之前讨论过的话题时使用此工具。"
        "系统已自动提供一些记忆上下文 -- 仅在需要搜索尚未提供的特定信息时使用此工具。"
    )

    inputs = {
        "query": {
            "type": "string",
            "description": "Natural language query describing what to search for",
            "description_zh": "描述要搜索内容的自然语言查询"
        },
        "top_k": {
            "type": "integer",
            "description": "Maximum number of results to return",
            "description_zh": "返回结果的最大数量",
            "default": 5,
            "nullable": True,
        },
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.MEMORY_OPERATION.value

    def __init__(
        self,
        memory_service: Any = Field(
            description="MemoryService instance (new SDK facade)",
            default=None,
            exclude=True,
        ),
        memory_context_service: Any = Field(
            description=(
                "Backend MemoryContextService. When provided, the tool "
                "delegates retrieval to its ``build_context`` so that "
                "Phase 4 pipeline stages (normalize / score fusion / "
                "temporal decay / MMR / token-budget selection) are "
                "applied. Falls back to ``memory_service`` when absent."
            ),
            default=None,
            exclude=True,
        ),
        tenant_id: str = Field(
            description="Tenant ID",
            default="",
            exclude=True,
        ),
        user_id: str = Field(
            description="User ID",
            default="",
            exclude=True,
        ),
        agent_id: str = Field(
            description="Agent ID",
            default="",
            exclude=True,
        ),
        conversation_id: str = Field(
            description="Conversation ID",
            default="",
            exclude=True,
        ),
        observer: MessageObserver = Field(
            description="Message observer",
            default=None,
            exclude=True,
        ),
    ):
        super().__init__()
        self.memory_service = memory_service
        self.memory_context_service = memory_context_service
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.conversation_id = conversation_id
        self.observer = observer
        self.running_prompt_en = "Searching memory..."
        self.running_prompt_zh = "搜索记忆中..."

    def _format_context(self, context: Any) -> str:
        """Render a ``MemorySearchContext`` to the tool's output string.

        The rendering mirrors the backend prompt-injection format so that
        the agent sees the same shape whether the context comes from the
        automatic prompt path or from an active ``search_memory`` call.
        """
        # Lazy import: avoids forcing the heavy retrieval stack onto callers
        # that only exercise the legacy direct ``memory_service`` path.
        from ...memory.models import MemoryLayer

        layer_labels = {
            MemoryLayer.TENANT: "Tenant Long-term Memory",
            MemoryLayer.USER: "User Long-term Memory",
            MemoryLayer.AGENT: "Agent Short-term Memory",
        }
        # The pipeline's external bucket is keyed separately rather than via
        # ``MemoryLayer``; render it last with its own section header.
        sections: list[tuple[str, list[Any]]] = []
        for layer_enum, attr in (
            (MemoryLayer.TENANT, "tenant_long_term"),
            (MemoryLayer.USER, "user_long_term"),
            (MemoryLayer.AGENT, "agent_short_term"),
        ):
            items = context.__getattribute__(attr)
            if items:
                sections.append((layer_labels[layer_enum], items))
        external_items = context.external
        if external_items:
            sections.append(("External Memory", external_items))

        total = sum(len(items) for _, items in sections)
        if total == 0:
            return "No relevant memories found."

        parts = [f"Found {total} relevant memories:"]
        for label, items in sections:
            parts.append(f"#### {label}")
            for i, item in enumerate(items, start=1):
                score = getattr(item, "score", None)
                score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "n/a"
                parts.append(
                    f"[{i}] (score: {score_str}, "
                    f"source: {getattr(item, 'source', 'n/a')}) "
                    f"{getattr(item, 'content', '')}"
                )
        return "\n".join(parts)

    def _search_via_context_service(
        self, query: str, top_k: int
    ) -> str:
        """Run retrieval through the Phase 4 pipeline via MemoryContextService."""
        from ...memory.models import MemoryLayer

        async def _build():
            return await self.memory_context_service.build_context(
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                agent_id=self.agent_id or None,
                conversation_id=self.conversation_id or None,
                query=query,
                top_k=top_k,
                layers=[MemoryLayer.AGENT.value],
            )

        context = _run_coroutine(_build())
        logger.info(
            "[ACTIVE MEMORY] SearchMemoryTool pipeline path completed: "
            "tenant=%d user=%d agent=%d external=%d",
            len(context.tenant_long_term),
            len(context.user_long_term),
            len(context.agent_short_term),
            len(context.external),
        )
        return self._format_context(context)

    def forward(self, query: str, top_k: int = 5) -> str:
        """Search memories relevant to ``query``.

        Args:
            query: Natural language query describing what to search for.
            top_k: Maximum number of results to return.

        Returns:
            A formatted string describing the search results.
        """
        logger.info(
            f"[ACTIVE MEMORY] SearchMemoryTool invoked: query={query[:200]}, "
            f"top_k={top_k}, user_id={self.user_id}, agent_id={self.agent_id}, "
            f"pipeline={'on' if self.memory_context_service else 'off'}"
        )
        if self.observer:
            running_prompt = (
                self.running_prompt_zh
                if self.observer.lang == "zh"
                else self.running_prompt_en
            )
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if self.memory_context_service is not None:
            try:
                return self._search_via_context_service(query=query, top_k=top_k)
            except Exception as exc:
                logger.error(
                    "search_memory via MemoryContextService failed (%s); "
                    "falling back to MemoryService path.",
                    exc,
                )
                # Fall through to the legacy direct path so that a broken
                # pipeline does not break the agent.

        if self.memory_service is None:
            return (
                "Memory search failed: MemoryService is not configured. "
                "Pass a MemoryService instance or wire "
                "MemoryContextService when constructing SearchMemoryTool."
            )

        try:
            from ...memory import MemoryLayer

            async def _search():
                return await self.memory_service.search_memory(
                    query=query,
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    conversation_id=self.conversation_id or None,
                    layers=[MemoryLayer.AGENT],
                    top_k=top_k,
                )

            results = _run_coroutine(_search())

            logger.info(
                f"[ACTIVE MEMORY] SearchMemoryTool completed: "
                f"found {len(results)} memories"
            )
            if not results:
                return "No relevant memories found."

            lines = [f"Found {len(results)} relevant memories:"]
            for i, item in enumerate(results):
                lines.append(
                    f"[{i + 1}] (score: {item.score:.2f}, "
                    f"layer: {item.layer}, source: {item.source}) {item.content}"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.error(f"search_memory failed: {exc}")
            return (
                f"Memory search failed: {exc}. "
                "Continuing without memory results."
            )
