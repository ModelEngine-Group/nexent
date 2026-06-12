import asyncio
import logging
from typing import Any

from smolagents.tools import Tool
from pydantic import Field

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("search_memory_tool")


class SearchMemoryTool(Tool):
    name = "search_memory"
    description = (
        "Search long-term memory for relevant information from previous interactions. "
        "Use this when you need context about the user's preferences, past decisions, "
        "or previously discussed topics that aren't in the current conversation. "
        "The system already provides some memory context automatically -- use this tool "
        "when you need to search for specific information not already available."
    )
    description_zh = (
        "搜索长期记忆中来自之前交互的相关信息。"
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
            "nullable": True
        }
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
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
        self.running_prompt_en = "Searching memory..."
        self.running_prompt_zh = "搜索记忆中..."

    def forward(self, query: str, top_k: int = 5) -> str:
        logger.info(f"[ACTIVE MEMORY] SearchMemoryTool invoked: query={query[:200]}, top_k={top_k}, user_id={self.user_id}, agent_id={self.agent_id}")
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        memory_levels = ["tenant", "user", "agent", "user_agent"]
        if self.memory_user_config.agent_share_option == "never":
            memory_levels.remove("agent")
        if self.agent_id in getattr(self.memory_user_config, "disable_agent_ids", []):
            if "agent" in memory_levels:
                memory_levels.remove("agent")
        if self.agent_id in getattr(self.memory_user_config, "disable_user_agent_ids", []):
            if "user_agent" in memory_levels:
                memory_levels.remove("user_agent")

        try:
            from ...memory.memory_service import search_memory_in_levels
            result = asyncio.run(search_memory_in_levels(
                query_text=query,
                memory_config=self.memory_config,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                agent_id=self.agent_id,
                top_k=top_k,
                memory_levels=memory_levels,
            ))

            items = result.get("results", [])
            logger.info(f"[ACTIVE MEMORY] SearchMemoryTool completed: found {len(items)} memories, levels={[item.get('memory_level', 'unknown') for item in items]}")
            if not items:
                return "No relevant memories found."

            lines = [f"Found {len(items)} relevant memories:"]
            for i, item in enumerate(items):
                content = item.get("memory", "") or item.get("content", "")
                score = item.get("score", 0.0)
                level = item.get("memory_level", "unknown")
                lines.append(f"[{i+1}] (score: {score:.2f}, level: {level}) {content}")
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"search_memory failed: {e}")
            return f"Memory search failed: {str(e)}. Continuing without memory results."
