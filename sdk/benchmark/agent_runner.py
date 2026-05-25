# -*- coding: utf-8 -*-
"""
此模块提供了构建 Agent 测试所需的基础功能：
1. Prompt 构建（system prompt, prompt templates）
2. AgentRunInfo 构造
3. 消息流处理和统计
"""
import sys
import io
import json
import os
import re
from datetime import datetime
from typing import AsyncIterator, Callable, Optional

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from jinja2 import Template, StrictUndefined
from smolagents.utils import BASE_BUILTIN_MODULES
from dotenv import load_dotenv
import string

# ============ Environment Setup ============
# Add benchmark/ to sys.path so paths.py can be found, then import it.
# paths.py resolves PROJECT_ROOT/SDK_DIR/BACKEND_DIR via .git discovery and
# injects them into sys.path automatically — no manual path manipulation needed.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: F401 — side-effect: adds sdk/, backend/ to sys.path

from utils.prompt_template_utils import get_agent_prompt_template
from nexent.core.agents.agent_model import (
    AgentRunInfo, AgentConfig, ModelConfig, AgentHistory, ToolConfig
)



from nexent.core.agents.run_agent import agent_run
from nexent.core.utils.observer import MessageObserver
from nexent.core.agents.agent_context import ContextManagerConfig
import logging
logging.getLogger("smolagents").setLevel(logging.WARNING)
import random
load_dotenv()

# ============ 全局配置 ============
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME")
LLM_API_URL = os.getenv("LLM_API_URL")

# Optional provider-specific knobs forwarded to chat.completions.create as
# the OpenAI SDK's ``extra_body`` parameter. Two layered sources:
#   * LLM_EXTRA_BODY — raw JSON, wins when set. Example:
#       LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}
#   * LLM_ENABLE_THINKING — convenience flag. When set to a falsey value
#       ("false"/"0"/"no"/"off") this produces the Qwen3 thinking-off body.
# Default behaviour (both unset) leaves extra_body=None — fully backwards
# compatible.
_LLM_EXTRA_BODY_RAW = (os.getenv("LLM_EXTRA_BODY") or "").strip()
_LLM_ENABLE_THINKING_RAW = (os.getenv("LLM_ENABLE_THINKING") or "true").strip().lower()


def _resolve_llm_extra_body():
    if _LLM_EXTRA_BODY_RAW:
        try:
            return json.loads(_LLM_EXTRA_BODY_RAW)
        except json.JSONDecodeError as exc:
            logging.getLogger(__name__).warning(
                "Ignoring LLM_EXTRA_BODY (not valid JSON): %s", exc
            )
            return None
    if _LLM_ENABLE_THINKING_RAW in ("false", "0", "no", "off"):
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return None


LLM_EXTRA_BODY = _resolve_llm_extra_body()

APP_NAME = os.getenv("APP_NAME", "Nexent")
APP_DESCRIPTION = os.getenv("APP_DESCRIPTION", "Nexent 是一个开源智能体SDK和平台")

# ============ 默认 Prompt 模板 ============
DEFAULT_DUTY_PROMPT = """你是一个智能助手，专注于帮助用户解决问题。你需要：
1. 理解用户的需求并提供准确的回答
2. 保持友好和专业的态度
3. 记住对话中的关键信息"""

DEFAULT_CONSTRAINT_PROMPT = """1. 不得生成有害内容
2. 遵守法律法规
3. 不确定时诚实告知用户"""

DEFAULT_FEW_SHOTS_PROMPT = ""

DEFAULT_FALLBACK_PROMPT = """你是一个有用的 AI 助手，可以帮助用户解决各种问题。请记住对话中的重要信息。"""

# ============ 消息类型常量 ============
TRACKED_MESSAGE_TYPES = {
    "agent_new_run",          # 任务开始
    "step_count",              # 步骤计数
    "model_output_thinking",   # 思考过程
    "model_output",            # 模型输出
    "code_output",             # 代码执行结果
    "final_answer",            # 最终答案
    "error",                   # 错误
}


# ============ Prompt 构建函数 ============

def build_system_prompt(
    duty: str = "",
    constraint: str = "",
    few_shots: str = "",
    tools: list = None,
    managed_agents: list = None,
    memory_list: list = None,
    knowledge_base_summary: str = "",
    language: str = "zh",
    is_manager: bool = False,
    user_id: str = "",
    skills: list = None
) -> str:
    """
    构建 System Prompt

    Args:
        duty: 职责描述
        constraint: 约束条件
        few_shots: Few-shot 示例
        tools: 工具列表
        managed_agents: 管理的子 Agent 列表
        memory_list: 记忆列表
        knowledge_base_summary: 知识库摘要
        language: 语言 (zh/en)
        is_manager: 是否为管理 Agent

    Returns:
        渲染后的 system prompt 字符串
    """
    tools = tools or []
    managed_agents = managed_agents or []
    memory_list = memory_list or []

    prompt_template = get_agent_prompt_template(is_manager=is_manager, language=language)
    template_content = prompt_template.get("system_prompt", "")

    tools_dict = {tool.name: tool for tool in tools}
    managed_agents_dict = {agent.name: agent for agent in managed_agents}

    system_prompt = Template(template_content, undefined=StrictUndefined).render({
        "duty": duty,
        "constraint": constraint,
        "few_shots": few_shots,
        "tools": tools_dict,
        "managed_agents": managed_agents_dict,
        "authorized_imports": str(BASE_BUILTIN_MODULES),
        "APP_NAME": APP_NAME,
        "APP_DESCRIPTION": APP_DESCRIPTION,
        "memory_list": memory_list,
        "knowledge_base_summary": knowledge_base_summary,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": user_id,
        "skills": skills or []
    })

    return system_prompt


def build_prompt_templates(
    system_prompt: str,
    language: str = "zh",
    is_manager: bool = False
) -> dict:
    """
    构建完整的 prompt_templates 字典

    Args:
        system_prompt: 系统提示词
        language: 语言
        is_manager: 是否为管理 Agent

    Returns:
        prompt_templates 字典
    """
    prompt_templates = get_agent_prompt_template(is_manager=is_manager, language=language)
    prompt_templates["system_prompt"] = system_prompt
    return prompt_templates


# ============ AgentRunInfo 构建函数 ============

def build_agent_run_info(
    query: str,
    history: list[AgentHistory],
    duty_prompt: str = "",
    constraint_prompt: str = "",
    few_shots_prompt: str = "",
    fallback_prompt: str = "",
    tools: list = None,
    managed_agents: list = None,
    max_steps: int = 10,
    temperature: float = 0.1,
    agent_name: str = "test_agent",
    agent_description: str = "测试 Agent",
    language: str = "zh",
    is_manager: bool = False,
    context_manager_config: Optional[ContextManagerConfig] = None,
    user_id: str = "",
    skills: list = None
) -> AgentRunInfo:
    """
    构造 AgentRunInfo

    Args:
        query: 用户查询
        history: 对话历史
        duty_prompt: 职责提示词（为空则使用默认）
        constraint_prompt: 约束提示词（为空则使用默认）
        few_shots_prompt: Few-shot 提示词
        fallback_prompt: 降级提示词（为空则使用默认）
        tools: 工具列表
        managed_agents: 管理的子 Agent 列表
        max_steps: 最大执行步骤
        temperature: 温度参数
        agent_name: Agent 名称
        agent_description: Agent 描述
        language: 语言
        is_manager: 是否为管理 Agent
        context_manager_config: 上下文管理器配置，None则使用默认配置

    Returns:
        AgentRunInfo 对象
    """
    # 使用默认值
    duty = duty_prompt or DEFAULT_DUTY_PROMPT
    constraint = constraint_prompt or DEFAULT_CONSTRAINT_PROMPT
    few_shots = few_shots_prompt or DEFAULT_FEW_SHOTS_PROMPT
    fallback = fallback_prompt or DEFAULT_FALLBACK_PROMPT
    tools = tools or []
    managed_agents = managed_agents or []

    model_config = ModelConfig(
        cite_name="main_model",
        api_key=LLM_API_KEY,
        model_name=LLM_MODEL_NAME,
        url=LLM_API_URL,
        temperature=temperature,
        ssl_verify=False,
        extra_body=LLM_EXTRA_BODY,
    )

    if duty or constraint or few_shots:
        system_prompt = build_system_prompt(
            duty=duty,
            constraint=constraint,
            few_shots=few_shots,
            tools=tools,
            managed_agents=managed_agents,
            memory_list=[],
            knowledge_base_summary="",
            language=language,
            is_manager=is_manager,
            user_id=user_id,
            skills=skills
        )
    else:
        system_prompt = fallback

    prompt_templates = build_prompt_templates(
        system_prompt,
        language=language,
        is_manager=is_manager
    )

    # 设置上下文管理器配置
    cm_config = context_manager_config


    agent_config = AgentConfig(
        name=agent_name,
        description=agent_description,
        tools=tools,
        max_steps=max_steps,
        model_name="main_model",
        prompt_templates=prompt_templates,
        managed_agents=managed_agents,
        context_manager_config=cm_config
    )


    import threading
    return AgentRunInfo(
        query=query,
        model_config_list=[model_config],
        observer=MessageObserver(lang=language),
        agent_config=agent_config,
        mcp_host=None,
        history=history,
        stop_event=threading.Event(),
    )


def build_agent_run_info_with_custom_prompt(
    query: str,
    system_prompt: str,
    history: list[AgentHistory],
    tools: list = None,
    managed_agents: list = None,
    max_steps: int = 10,
    temperature: float = 0.1,
    agent_name: str = "test_agent",
    agent_description: str = "Test Agent",
    language: str = "en",
    is_manager: bool = False,
    context_manager_config: Optional[ContextManagerConfig] = None,
) -> AgentRunInfo:
    """
    Build AgentRunInfo with a pre-rendered system prompt string.

    Unlike build_agent_run_info which renders the system prompt via Jinja2 template,
    this function accepts the final system prompt directly, bypassing the template
    engine entirely. Use this for benchmark scenarios that need a specialized prompt
    without the standard platform scaffolding.

    Args:
        query: User query
        system_prompt: Pre-rendered system prompt string (used as-is)
        history: Conversation history
        tools: Tool list
        managed_agents: Managed sub-agents
        max_steps: Max execution steps
        temperature: Temperature parameter
        agent_name: Agent name
        agent_description: Agent description
        language: Language
        is_manager: Whether this is a manager agent
        context_manager_config: Context manager config

    Returns:
        AgentRunInfo object
    """
    tools = tools or []
    managed_agents = managed_agents or []

    model_config = ModelConfig(
        cite_name="main_model",
        api_key=LLM_API_KEY,
        model_name=LLM_MODEL_NAME,
        url=LLM_API_URL,
        temperature=temperature,
        ssl_verify=False,
        extra_body=LLM_EXTRA_BODY,
    )

    prompt_templates = build_prompt_templates(
        system_prompt,
        language=language,
        is_manager=is_manager,
    )

    agent_config = AgentConfig(
        name=agent_name,
        description=agent_description,
        tools=tools,
        max_steps=max_steps,
        model_name="main_model",
        prompt_templates=prompt_templates,
        managed_agents=managed_agents,
        context_manager_config=context_manager_config,
    )

    import threading
    return AgentRunInfo(
        query=query,
        model_config_list=[model_config],
        observer=MessageObserver(lang=language),
        agent_config=agent_config,
        mcp_host=None,
        history=history,
        stop_event=threading.Event(),
    )


# ============ 消息处理函数 ============

def process_agent_message(chunk: str) -> tuple[str, str]:
    """
    解析 agent_run 返回的 JSON 消息

    Args:
        chunk: JSON 字符串

    Returns:
        (message_type, message_content) 元组
    """
    try:
        data = json.loads(chunk)
        return data.get("type", ""), data.get("content", "")
    except json.JSONDecodeError:
        return "", chunk


class AgentRunResult:
    """Agent 运行结果封装"""
    def __init__(self):
        self.final_answer: str = ""
        self.full_response: str = ""
        self.message_type_count: dict = {}
        self.step_count: int = 0
        self.errors: list = []

    def __repr__(self):
        return f"AgentRunResult(final_answer_len={len(self.final_answer)}, " \
               f"steps={self.step_count}, types={self.message_type_count})"


async def run_agent_with_tracking(
    agent_run_info: AgentRunInfo,
    on_final_answer: Optional[Callable[[str], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    debug: bool = False
) -> AgentRunResult:
    """
    运行 Agent 并跟踪消息统计

    Args:
        agent_run_info: Agent 运行信息
        on_final_answer: 收到 final_answer 时的回调函数
        on_error: 收到 error 时的回调函数
        debug: 是否打印调试信息

    Returns:
        AgentRunResult 对象，包含最终结果和统计信息

    Example:
        >>> result = await run_agent_with_tracking(agent_run_info)
        >>> print(result.final_answer)
        >>> print(result.message_type_count)
    """
    result = AgentRunResult()

    async for chunk in agent_run(agent_run_info):
        if not chunk:
            continue

        msg_type, msg_content = process_agent_message(chunk)

        if debug:
            print(f"[DEBUG] Type={msg_type}, Content Length={len(msg_content)}",
                  file=sys.stderr, flush=True)

        # 统计消息类型
        if msg_type in TRACKED_MESSAGE_TYPES:
            result.message_type_count[msg_type] = result.message_type_count.get(msg_type, 0) + 1

            if msg_type in ["step_count", "final_answer"]:
                result.step_count += 1

        # 处理最终答案
        if msg_type == "final_answer":
            result.final_answer = msg_content
            result.full_response += msg_content
            if on_final_answer:
                on_final_answer(msg_content)

        # 处理错误
        elif msg_type == "error":
            result.errors.append(msg_content)
            if on_error:
                on_error(msg_content)

    # 降级处理
    if not result.final_answer:
        result.final_answer = result.full_response if result.full_response else "（未获得回应）"

    return result




def parse_conversation_to_history(file_path: str) -> list[AgentHistory]:
    """
    Parse a JSON conversation file into a list of AgentHistory objects.

    Expected format: [{"role": "user"|"assistant", "content": "..."}, ...]

    Args:
        file_path: Path to a .json conversation file.

    Returns:
        List of AgentHistory objects in conversation order.

    Raises:
        ValueError: If file is not a .json file.
    """
    if not file_path.endswith(".json"):
        raise ValueError(
            f"Only .json conversation files are supported, got: {file_path}"
        )

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return [AgentHistory(role=entry["role"], content=entry["content"]) for entry in data]
