"""Search memory tool for the new Memory system.

This tool is invoked once by the runtime before the agent model loop. Under
the new Memory architecture it is not exposed for model-directed calls:

- Searches default to the agent's own short-term memory (vector search).
- Tenant / user long-term memories can be exposed as full-context (handled by
  the backend ``memory_context_service``); the tool surfaces a stable prompt
  contract regardless of which retrieval backend is in use.
- When the backend wires a ``memory_context_service`` into the tool
  metadata, the tool routes results exclusively through the Phase 4 retrieval
  pipeline (``MemoryContextService.build_context``) so that score fusion,
  temporal decay, MMR deduplication, and token-budget selection are always
  applied. Callers that explicitly configure only ``memory_service`` retain
  the direct SDK retrieval mode.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from smolagents.tools import Tool
from pydantic import Field

from ..utils.observer import MessageObserver
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
                "applied. Pipeline failures do not switch retrieval modes."
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
        embedding_configured: bool = Field(
            description="Whether the tenant has an active embedding model",
            default=True,
            exclude=True,
        ),
        external_results: Any = Field(
            description="Pre-fetched external memory results to include in search",
            default=None,
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
        self.embedding_configured = embedding_configured
        self.external_results = external_results
        self.observer = observer

    def _format_context(self, context: Any) -> str:
        """Render a ``MemorySearchContext`` to the tool's output string.

        The rendering mirrors the backend prompt-injection format so that
        the agent sees the same shape whether the context comes from the
        automatic prompt path or from an active ``search_memory`` call.
        """
        # Lazy import: avoids forcing the heavy retrieval stack onto callers
        # that explicitly use the direct ``memory_service`` mode.
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
        async def _build():
            return await self.memory_context_service.build_context(
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                agent_id=self.agent_id or None,
                conversation_id=self.conversation_id or None,
                query=query,
                top_k=top_k,
                layers=["agent"],
                external_results=self.external_results,
            )

        context = _run_coroutine(_build())
        existing_external = {
            (
                str(getattr(item, "id", None) or getattr(item, "external_id", None) or ""),
                str(getattr(item, "content", "")),
                str(getattr(item, "provider", None) or getattr(item, "source", "")),
            )
            for item in context.external
        }
        for item in self.external_results or []:
            identity = (
                str(getattr(item, "id", None) or getattr(item, "external_id", None) or ""),
                str(getattr(item, "content", "")),
                str(getattr(item, "provider", None) or getattr(item, "source", "")),
            )
            if identity not in existing_external:
                context.external.append(item)
                existing_external.add(identity)
        logger.info(
            "event=memory_tool_completed tool=search_memory tenant_id=%s user_id=%s "
            "agent_id=%s conversation_id=%s path=pipeline result_count=%d",
            self.tenant_id,
            self.user_id,
            self.agent_id,
            self.conversation_id,
            len(context.agent_short_term),
        )
        context.tenant_long_term = []
        context.user_long_term = []
        # Keep external results - they were already searched in create_agent_info.py
        # and passed to build_context via external_results parameter
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
            "event=memory_tool_invoked tool=search_memory tenant_id=%s user_id=%s "
            "agent_id=%s conversation_id=%s query_length=%d top_k=%s pipeline_enabled=%s",
            self.tenant_id,
            self.user_id,
            self.agent_id,
            self.conversation_id,
            len(query),
            top_k,
            self.memory_context_service is not None,
        )
        if not self.embedding_configured:
            logger.info(
                "event=memory_tool_degraded tool=search_memory tenant_id=%s "
                "reason=embedding_not_configured",
                self.tenant_id,
            )
            return "[]"
        if self.memory_context_service is not None:
            try:
                return self._search_via_context_service(query=query, top_k=top_k)
            except Exception as exc:
                logger.error(
                    "event=memory_tool_failed tool=search_memory tenant_id=%s user_id=%s "
                    "agent_id=%s conversation_id=%s path=pipeline "
                    "error_type=%s",
                    self.tenant_id,
                    self.user_id,
                    self.agent_id,
                    self.conversation_id,
                    type(exc).__name__,
                )
                return (
                    "Memory search failed. Continuing without memory results."
                )

        if self.memory_service is None:
            logger.error(
                "event=memory_tool_failed tool=search_memory tenant_id=%s user_id=%s "
                "agent_id=%s conversation_id=%s reason=service_not_configured",
                self.tenant_id,
                self.user_id,
                self.agent_id,
                self.conversation_id,
            )
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
                "event=memory_tool_completed tool=search_memory tenant_id=%s user_id=%s "
                "agent_id=%s conversation_id=%s path=memory_service result_count=%d",
                self.tenant_id,
                self.user_id,
                self.agent_id,
                self.conversation_id,
                len(results),
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
            logger.error(
                "event=memory_tool_failed tool=search_memory tenant_id=%s user_id=%s "
                "agent_id=%s conversation_id=%s error_type=%s",
                self.tenant_id,
                self.user_id,
                self.agent_id,
                self.conversation_id,
                type(exc).__name__,
            )
            return (
                f"Memory search failed: {exc}. "
                "Continuing without memory results."
            )
