# -*- coding: utf-8 -*-
"""
测试工具模块 - 从 test_multi_run.py 抽提的可复用组件

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
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
# temp_scripts 在 sdk/nexent/core/agents/ 下，需要向上 4 级到达 sdk 目录
SDK_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR))))
# sdk 的父目录即为项目根目录
PROJECT_ROOT = os.path.dirname(SDK_DIR)
BACKEND_PATH = os.path.join(PROJECT_ROOT, "backend")

if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_PATH not in sys.path:
    sys.path.insert(0, BACKEND_PATH)

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

# 关闭模型原生思考的 extra_body（兼容多种后端）
THINKING_OFF_EXTRA_BODY = {
    "chat_template_kwargs": {"enable_thinking": False},
    "thinking": {"type": "disabled"},
}


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
    skills: list = None,
    extra_body: Optional[dict] = None,
    offload_store: Optional[object] = None,
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
        user_id: 用户ID
        skills: 技能列表
        extra_body: 附加的 API 请求体参数，可用于关闭模型原生思考等。
                    None 时使用模型默认行为。
                    THINKING_OFF_EXTRA_BODY 常量可关闭思考（兼容多后端）。

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
        extra_body=extra_body,
    )
    
    # If reload is enabled, include the reload tool in system prompt rendering
    # so the LLM sees its name / description / inputs natively through the
    # YAML template's normal tool-rendering loop.
    display_tools = list(tools)
    if context_manager_config and context_manager_config.enable_reload:
        display_tools.append(ToolConfig(
            class_name="ReloadOriginalContextTool",
            name="reload_original_context_messages",
            description=(
                "Reload the original full content of an offloaded / archived context step. "
                "Use this when the system notice at the start of the conversation lists "
                "archived handles that are relevant to the user's question."
            ),
            inputs=str({"offload_handle": "str: handle value from the system notice inventory"}),
            output_type="string",
            params={},
            source="local",
        ))

    if duty or constraint or few_shots:
        system_prompt = build_system_prompt(
            duty=duty,
            constraint=constraint,
            few_shots=few_shots,
            tools=display_tools,
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
        context_manager_config=cm_config,
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


# ============ 历史记录构建工具 ============

def build_mock_history(
    turns: int = 5,
    user_prefix: str = "用户问题",
    assistant_prefix: str = "助手回答"
) -> list[AgentHistory]:
    """
    构建模拟的对话历史
    
    Args:
        turns: 对话轮数
        user_prefix: 用户消息前缀
        assistant_prefix: 助手消息前缀
    
    Returns:
        AgentHistory 列表
    """
    history = []
    for i in range(turns):
        history.append(AgentHistory(role="user", content=f"{user_prefix} {i+1}"))
        history.append(AgentHistory(
            role="assistant", 
            content=f"{assistant_prefix} {i+1}: 这是第 {i+1} 轮对话的回答内容。"
        ))
    return history




def parse_conversation_to_history(file_path: str) -> list[AgentHistory]:
    """
    解析对话文本，提取用户和助手消息，构建 AgentHistory 列表。
    
    文本格式示例：
        **user**：
        内容...
        **assistant**
        内容...
    
    支持 user 的常见拼写变体（如 usesr）。
    
    Args:
        text: 包含对话记录的 Markdown 文本
    
    Returns:
        AgentHistory 对象列表，按对话顺序排列
    """
    with open(file_path,'r',encoding='utf-8') as f:

        tmp = f.readlines()
    text = "".join(tmp)
    history = []
    
    # 正则匹配角色标记行，不区分大小写，容忍 user 拼写错误
    # 匹配模式：**角色名** 或 **角色名：**，后跟内容直到下一个标记或文本结束
    pattern = r'^\*\*(user|assistant|usesr)\**\s*[:：]?\s*\*\*\s*$'
    
    lines = text.splitlines(keepends=True)  # 保留换行符以便拼接内容
    
    current_role = None
    current_content_lines = []
    
    def finalize_current_block():
        nonlocal current_role, current_content_lines
        if current_role is not None:
            content = ''.join(current_content_lines).strip()
            if content:
                # 规范化角色名称
                role = 'user' if current_role.lower().startswith('user') else 'assistant'
                history.append(AgentHistory(role=role, content=content))
        current_role = None
        current_content_lines = []
    
    for line in lines:
        # 检查是否为角色标记行
        match = re.match(pattern, line.strip())
        if match:
            # 遇到新角色标记，先保存上一个块
            finalize_current_block()
            # 设置新角色
            role_label = match.group(1).lower()
            if role_label.startswith('user'):
                current_role = 'user'
            else:
                current_role = 'assistant'
        else:
            # 当前行属于内容部分
            if current_role is not None:
                current_content_lines.append(line)
    
    # 处理最后一个块
    finalize_current_block()
    
    return history




def print_history_stats(history: list[AgentHistory]):
    """打印历史记录统计信息"""
    user_count = sum(1 for h in history if h.role == "user")
    assistant_count = sum(1 for h in history if h.role == "assistant")
    total_chars = sum(len(h.content) for h in history)
    
    print(f"历史记录统计:")
    print(f"  - 总消息数: {len(history)}")
    print(f"  - 用户消息: {user_count}")
    print(f"  - 助手消息: {assistant_count}")
    print(f"  - 对话轮数: {len(history) // 2}")
    print(f"  - 总字符数: {total_chars}")
