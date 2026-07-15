"""Search memory tool for the new Memory system.

This tool is invoked by the agent to retrieve relevant memories. Under the
new Memory architecture:

- Searches default to the agent's own short-term memory (vector search).
- Tenant / user long-term memories can be exposed as full-context (handled by
  the backend ``memory_context_service``); the tool surfaces a stable prompt
  contract regardless of which retrieval backend is in use.
- The legacy mem0-based ``search_memory_in_levels`` multi-level fan-out has
  been removed in favor of a single ``MemoryService.search_memory`` call.
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
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.conversation_id = conversation_id
        self.observer = observer
        self.running_prompt_en = "Searching memory..."
        self.running_prompt_zh = "搜索记忆中..."

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
            f"top_k={top_k}, user_id={self.user_id}, agent_id={self.agent_id}"
        )
        if self.observer:
            running_prompt = (
                self.running_prompt_zh
                if self.observer.lang == "zh"
                else self.running_prompt_en
            )
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if self.memory_service is None:
            return (
                "Memory search failed: MemoryService is not configured. "
                "Pass a MemoryService instance when constructing "
                "SearchMemoryTool."
            )

        try:
            from ..memory import MemoryLayer

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
