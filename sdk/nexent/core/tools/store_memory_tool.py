"""Store memory tool for the new Memory system.

This tool is invoked by the agent to persist important information to its
short-term memory. Under the new Memory system architecture:

- Agents can ONLY write to the ``agent`` layer with ``short_term`` type.
- Calls write a single memory record via the ``MemoryService`` facade.
- Per-run storage limits are preserved.
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


logger = logging.getLogger("store_memory_tool")


def _run_coroutine(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class StoreMemoryTool(Tool):
    """Tool that stores a memory into the agent's short-term memory.

    In the new architecture the tool enforces:
    ``layer == MemoryLayer.AGENT`` and ``memory_type == MemoryType.SHORT_TERM``.
    The legacy multi-level concatenation (``user_agent`` etc.) is no longer
    supported: a sub-agent cannot write to a parent agent's memory and vice
    versa.
    """

    name = "store_memory"
    description = (
        "Save important information to the current agent's short-term memory. "
        "Use this when the user shares personal preferences, facts about "
        "themselves, project context, or instructions that should persist "
        "across the current conversation. Do NOT store transient information "
        "like temporary calculations, information already in the knowledge "
        "base, or data the user explicitly says to forget."
    )
    description_zh = (
        "将重要信息保存到当前智能体的短期记忆中。"
        "当用户分享个人偏好、关于自己的事实、项目上下文或应在本对话中保留的指令时使用此工具。"
        "不要存储临时信息，如临时计算结果、知识库中已有的信息或用户明确要求遗忘的数据。"
    )

    inputs = {
        "content": {
            "type": "string",
            "description": "The information to remember",
            "description_zh": "需要记住的信息"
        }
    }
    output_type = "string"
    category = ToolCategory.DATABASE.value
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
        self.store_count = 0
        self.max_stores_per_run = 3
        self.running_prompt_en = "Saving to memory..."
        self.running_prompt_zh = "保存到记忆中..."

    def forward(self, content: str) -> str:
        """Store ``content`` into the current agent's short-term memory.

        Args:
            content: The information to remember.

        Returns:
            Status message describing what was stored.
        """
        logger.info(
            f"[ACTIVE MEMORY] StoreMemoryTool invoked: content={content[:200]}, "
            f"user_id={self.user_id}, agent_id={self.agent_id}, "
            f"store_count={self.store_count}/{self.max_stores_per_run}"
        )
        if self.observer:
            running_prompt = (
                self.running_prompt_zh
                if self.observer.lang == "zh"
                else self.running_prompt_en
            )
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if self.store_count >= self.max_stores_per_run:
            return (
                "Memory storage limit reached for this conversation. "
                "Information will be saved automatically at the end."
            )

        if self.memory_service is None:
            return (
                "Failed to store memory: MemoryService is not configured. "
                "Pass a MemoryService instance when constructing "
                "StoreMemoryTool."
            )

        try:
            from ...memory import MemoryLayer, MemoryType

            async def _store():
                return await self.memory_service.store_memory(
                    content=content,
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    conversation_id=self.conversation_id or None,
                    layer=MemoryLayer.AGENT,
                    memory_type=MemoryType.SHORT_TERM,
                )

            result = _run_coroutine(_store())
            self.store_count += 1

            logger.info(
                f"[ACTIVE MEMORY] StoreMemoryTool completed: "
                f"memory_id={result.memory_id}, event={result.event}"
            )
            return (
                "Stored successfully:\n"
                f"[{result.event}] {result.content}"
            )
        except PermissionError as exc:
            logger.error(f"store_memory denied by policy: {exc}")
            return (
                "Failed to store memory: agent is not allowed to write to "
                "the requested layer/type."
            )
        except Exception as exc:
            logger.error(f"store_memory failed: {exc}")
            return (
                f"Failed to store memory: {exc}. Continuing without saving."
            )
