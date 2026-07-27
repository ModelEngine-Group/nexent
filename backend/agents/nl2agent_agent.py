"""Build the ephemeral NL2Agent and its runtime-only search tool."""

import json
import logging
from typing import Any, Callable, Literal

from langchain_core.tools import StructuredTool
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from consts.const import LANGUAGE

logger = logging.getLogger(__name__)

NL2AGENT_NAME = "__nl2agent_runtime__"
SEARCH_INSTALLED_MCP_TOOLS_NAME = "search_installed_mcp_tools"
MAX_TOOL_RECOMMENDATIONS = 5


class GeneratedAgentDraft(BaseModel):
    """Complete in-memory agent draft used to search for compatible tools."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    duty_prompt: str = Field(min_length=1)
    constraint_prompt: str = Field(min_length=1)
    few_shots_prompt: str | None = None


class SearchInstalledMcpToolsArgs(BaseModel):
    """LangChain-compatible schema without nested Pydantic references."""

    draft: dict[str, Any] = Field(
        description=(
            "Complete agent draft with name, display_name, description, "
            "duty_prompt, constraint_prompt, and optional few_shots_prompt."
        )
    )


class InstalledMcpToolRecommendation(BaseModel):
    """Safe display metadata for one installed MCP tool recommendation."""

    tool_id: int
    name: str
    origin_name: str | None = None
    description: str
    source: Literal["mcp"] = "mcp"
    usage: str
    labels: list[str]
    score: float


class SearchInstalledMcpToolsObservation(BaseModel):
    """Successful structured observation returned to the agent."""

    status: Literal["success"] = "success"
    recommendation_count: int
    recommendations: list[InstalledMcpToolRecommendation]


class SearchInstalledMcpToolsErrorObservation(BaseModel):
    """Safe structured error returned to the agent."""

    status: Literal["error"] = "error"
    code: Literal["invalid_draft", "invalid_keywords", "tool_search_failed"]
    retryable: Literal[True] = True


SearchFunction = Callable[
    [str, GeneratedAgentDraft, int],
    list[InstalledMcpToolRecommendation],
]


def build_nl2agent_system_prompt(
    language: str,
    tool_name: str = SEARCH_INSTALLED_MCP_TOOLS_NAME,
    max_results: int = MAX_TOOL_RECOMMENDATIONS,
) -> str:
    """Assemble the NL2Agent instructions for one ephemeral run."""

    draft_shape = json.dumps(
        {
            "name": "string",
            "display_name": "string",
            "description": "string",
            "duty_prompt": "string",
            "constraint_prompt": "string",
            "few_shots_prompt": "string or null",
        },
        ensure_ascii=False,
        indent=2,
    )

    if language == LANGUAGE["EN"]:
        sections = [
            """## Role
You are NL2Agent, an ephemeral assistant that clarifies a user's desired agent and searches the current tenant's installed MCP tool catalog. This run does not create or persist an agent.""",
            f"""## Workflow
1. If the user's goal is not clear enough to identify required capabilities, ask a concise clarifying question and do not call a tool.
2. Once the goal is clear, create one complete agent draft and call `{tool_name}` with that draft.
3. Use the returned observation to explain the recommendations briefly. The tool returns at most {max_results} tools ordered by relevance.""",
            f"""## Draft Schema
Pass exactly one `draft` object with this shape:
```json
{draft_shape}
```
Every field except `few_shots_prompt` must be a non-empty string. Do not add fields.""",
            """## Constraints
- The search tool is the only available business tool. Do not attempt to call MCP tools or other agents.
- Do not create, update, publish, or claim to have persisted an agent.
- Do not present cards or ask for creation confirmation.
- Never invent tenant IDs, user IDs, credentials, tool IDs, or search results.
- Treat a structured error observation as a tool failure and explain it without exposing internal details.""",
            """## Final Response
After a successful search, state that the installed tool search completed and summarize the returned recommendations. Do not claim that the recommended tools were executed.""",
        ]
    else:
        sections = [
            """## 角色
你是 NL2Agent，一个临时智能体。你负责澄清用户希望创建的智能体，并搜索当前租户已经安装的 MCP 工具。本次运行不会创建或持久化任何智能体。""",
            f"""## 工作流程
1. 如果用户目标尚不足以判断所需能力，提出一个简洁的澄清问题，不调用工具。
2. 目标明确后，生成一份完整的智能体草稿，并用该草稿调用 `{tool_name}`。
3. 根据工具 Observation 简要说明推荐结果。工具最多返回 {max_results} 个结果，并已按匹配度排序。""",
            f"""## 草稿结构
只传入一个 `draft` 对象，结构必须如下：
```json
{draft_shape}
```
除 `few_shots_prompt` 外，每个字段都必须是非空字符串。不得添加其他字段。""",
            """## 约束
- 搜索工具是唯一可用的业务工具，不得尝试调用 MCP 工具或其他智能体。
- 不得创建、更新、发布智能体，也不得声称已经持久化智能体。
- 不得展示卡片或请求创建确认。
- 不得编造租户 ID、用户 ID、凭据、工具 ID 或搜索结果。
- 收到结构化错误 Observation 时，将其作为工具失败处理，不得暴露内部错误细节。""",
            """## 最终回答
搜索成功后，说明已完成已安装工具搜索，并简要概括返回的推荐结果。不得声称已经执行推荐工具。""",
        ]

    return "\n\n".join(sections)


def build_search_installed_mcp_tools(
    tenant_id: str,
    language: str,
    search_fn: SearchFunction,
) -> StructuredTool:
    """Create a request-scoped LangChain tool bound to one tenant."""

    def search_installed_mcp_tools(draft: dict[str, Any]) -> str:
        try:
            validated_draft = GeneratedAgentDraft.model_validate(draft)
        except ValidationError:
            return SearchInstalledMcpToolsErrorObservation(
                code="invalid_draft"
            ).model_dump_json()

        try:
            recommendations = search_fn(
                tenant_id,
                validated_draft,
                MAX_TOOL_RECOMMENDATIONS,
            )
        except Exception:
            logger.exception("Failed to search installed MCP tools for NL2Agent")
            return SearchInstalledMcpToolsErrorObservation(
                code="tool_search_failed"
            ).model_dump_json()

        return SearchInstalledMcpToolsObservation(
            recommendation_count=len(recommendations),
            recommendations=recommendations,
        ).model_dump_json()

    description = (
        "Search the current tenant's installed and available MCP tools using a complete agent draft. "
        "Returns a structured JSON observation ordered by relevance."
        if language == LANGUAGE["EN"]
        else "根据完整的智能体草稿，搜索当前租户已安装且可用的 MCP 工具，并按匹配度返回结构化 JSON。"
    )
    return StructuredTool.from_function(
        func=search_installed_mcp_tools,
        name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        description=description,
        args_schema=SearchInstalledMcpToolsArgs,
    )


def create_nl2agent_agent_config(
    language: str,
    search_tool: StructuredTool,
) -> AgentConfig:
    """Create the in-memory AgentConfig for one NL2Agent request."""

    tool_config = ToolConfig(
        class_name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        name=SEARCH_INSTALLED_MCP_TOOLS_NAME,
        description=search_tool.description,
        inputs='{"draft": "object"}',
        output_type="string",
        params={},
        source="langchain",
    )
    tool_config.metadata = search_tool

    return AgentConfig(
        name=NL2AGENT_NAME,
        description="Ephemeral natural-language agent builder",
        prompt_templates=None,
        tools=[tool_config],
        max_steps=5,
        model_name="main_model",
        provide_run_summary=False,
        instructions=build_nl2agent_system_prompt(language),
        enable_planning=False,
    )
