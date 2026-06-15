import asyncio
import logging
from typing import Any

from smolagents.tools import Tool
from pydantic import Field

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("store_memory_tool")


class StoreMemoryTool(Tool):
    name = "store_memory"
    description = (
        "Save important information to long-term memory for future recall. "
        "Use this when the user shares personal preferences, facts about themselves, "
        "project context, or instructions that should persist across conversations. "
        "Do NOT store transient information like temporary calculations, information "
        "already in the knowledge base, or data the user explicitly says to forget."
    )
    description_zh = (
        "将重要信息保存到长期记忆中以便未来回忆。"
        "当用户分享个人偏好、关于自己的事实、项目上下文或应跨对话保留的指令时使用此工具。"
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
        memory_config: dict = Field(description="Mem0 configuration", exclude=True),
        tenant_id: str = Field(description="Tenant ID", default="", exclude=True),
        user_id: str = Field(description="User ID", default="", exclude=True),
        agent_id: str = Field(description="Agent ID", default="", exclude=True),
        memory_user_config: Any = Field(description="User memory preferences", default=None, exclude=True),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
    ):
        super().__init__()
        self.memory_config = memory_config
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.memory_user_config = memory_user_config
        self.observer = observer
        self.store_count = 0
        self.max_stores_per_run = 3
        self.running_prompt_en = "Saving to memory..."
        self.running_prompt_zh = "保存到记忆中..."

    def forward(self, content: str) -> str:
        logger.info(f"[ACTIVE MEMORY] StoreMemoryTool invoked: content={content[:200]}, user_id={self.user_id}, agent_id={self.agent_id}, store_count={self.store_count}/{self.max_stores_per_run}")
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if self.store_count >= self.max_stores_per_run:
            return "Memory storage limit reached for this conversation. Information will be saved automatically at the end."

        levels = ["user_agent", "agent"]
        if self.memory_user_config.agent_share_option == "never":
            levels.remove("agent")
        if self.agent_id in getattr(self.memory_user_config, "disable_user_agent_ids", []):
            levels = [l for l in levels if l != "user_agent"]
        if self.agent_id in getattr(self.memory_user_config, "disable_agent_ids", []):
            levels = [l for l in levels if l != "agent"]
        if not levels:
            return "No memory levels available (all disabled by user preferences)."

        try:
            from ...memory.memory_service import add_memory_in_levels
            result = asyncio.run(add_memory_in_levels(
                messages=[{"role": "user", "content": content}],
                memory_config=self.memory_config,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                agent_id=self.agent_id,
                memory_levels=levels,
            ))
            self.store_count += 1

            items = result.get("results", [])
            logger.info(f"[ACTIVE MEMORY] StoreMemoryTool completed: {len(items)} items processed, events={[item.get('event', 'NONE') for item in items]}")
            if not items:
                return "No new facts were extracted from the content."

            stored_facts = []
            for item in items:
                event = item.get("event", "NONE")
                text = item.get("memory", "")
                if event in ("ADD", "UPDATE"):
                    stored_facts.append(f"[{event}] {text}")

            if not stored_facts:
                return "The information was already present in memory (no changes needed)."
            return "Stored successfully:\n" + "\n".join(stored_facts)

        except Exception as e:
            logger.error(f"store_memory failed: {e}")
            return f"Failed to store memory: {str(e)}. Continuing without saving."
