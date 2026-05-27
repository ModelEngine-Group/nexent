# -*- coding: utf-8 -*-
"""
Shared utilities for building and running nexent agents in benchmarks.

Provides:
1. Prompt construction (system prompt, prompt templates)
2. AgentRunInfo construction (standard and custom-prompt variants)
3. Message-stream processing and statistics
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
# Add parent directory to sys.path so paths.py can be found, then import it.
# paths.py resolves PROJECT_ROOT/SDK_DIR/BACKEND_DIR via .git discovery and
# injects them into sys.path automatically — no manual path manipulation needed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

# ============ Global Configuration ============
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME")
LLM_API_URL = os.getenv("LLM_API_URL")

# Disable model thinking for benchmark runs. Both vendor dialects are kept in
# one payload so the same agent_runner.py works against either backend without
# code changes: Qwen-on-vLLM/SGLang reads `chat_template_kwargs.enable_thinking`
# and ignores `thinking`; Anthropic reads `thinking.type` and ignores
# `chat_template_kwargs`. Unknown keys are silently dropped by each provider.
THINKING_OFF_EXTRA_BODY = {
    "chat_template_kwargs": {"enable_thinking": False},
    "thinking": {"type": "disabled"},
}

APP_NAME = os.getenv("APP_NAME", "Nexent")
APP_DESCRIPTION = os.getenv("APP_DESCRIPTION", "Nexent is an open-source agent SDK and platform")

# ============ Default Prompt Templates ============
DEFAULT_DUTY_PROMPT = """You are an intelligent assistant focused on helping users solve problems. You need to:
1. Understand the user's needs and provide accurate answers
2. Maintain a friendly and professional attitude
3. Remember key information from the conversation"""

DEFAULT_CONSTRAINT_PROMPT = """1. Do not generate harmful content
2. Comply with laws and regulations
3. Be honest with users when uncertain"""

DEFAULT_FEW_SHOTS_PROMPT = ""

DEFAULT_FALLBACK_PROMPT = """You are a helpful AI assistant that can help users solve various problems. Please remember important information from the conversation."""

# ============ Message Type Constants ============
TRACKED_MESSAGE_TYPES = {
    "agent_new_run",          # task start
    "step_count",              # step count
    "model_output_thinking",   # thinking process
    "model_output",            # model output
    "code_output",             # code execution result
    "final_answer",            # final answer
    "error",                   # error
    "token_count",             # per-step token usage stats
}


# ============ Prompt Construction Functions ============

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
    Build System Prompt

    Args:
        duty: Duty description
        constraint: Constraints
        few_shots: Few-shot examples
        tools: Tool list
        managed_agents: Managed sub-agent list
        memory_list: Memory list
        knowledge_base_summary: Knowledge base summary
        language: Language (zh/en)
        is_manager: Whether this is a manager agent

    Returns:
        Rendered system prompt string
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
    Build complete prompt_templates dict

    Args:
        system_prompt: System prompt string
        language: Language
        is_manager: Whether this is a manager agent

    Returns:
        prompt_templates dict
    """
    prompt_templates = get_agent_prompt_template(is_manager=is_manager, language=language)
    prompt_templates["system_prompt"] = system_prompt
    return prompt_templates


# ============ AgentRunInfo Construction Functions ============

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
    agent_description: str = "Test Agent",
    language: str = "zh",
    is_manager: bool = False,
    context_manager_config: Optional[ContextManagerConfig] = None,
    user_id: str = "",
    skills: list = None,
    max_tokens: Optional[int] = None,
) -> AgentRunInfo:
    """
    Construct AgentRunInfo with template-based system prompt.

    Args:
        query: User query
        history: Conversation history
        duty_prompt: Duty prompt (empty uses default)
        constraint_prompt: Constraint prompt (empty uses default)
        few_shots_prompt: Few-shot prompt
        fallback_prompt: Fallback prompt (empty uses default)
        tools: Tool list
        managed_agents: Managed sub-agent list
        max_steps: Max execution steps
        temperature: Temperature parameter
        agent_name: Agent name
        agent_description: Agent description
        language: Language
        is_manager: Whether this is a manager agent
        context_manager_config: Context manager config (None uses default)
        user_id: User ID
        skills: Skill list
        max_tokens: Per-call completion output cap forwarded to the main LLM.
                    Default None leaves the provider default (unbounded /
                    model max), matching the SDK back-port. Benchmarks that
                    want to bound runaway / degenerate-loop probes set this
                    explicitly (e.g. 4096).

    Returns:
        AgentRunInfo object
    """
    # Use defaults
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
        extra_body=THINKING_OFF_EXTRA_BODY,
        max_tokens=max_tokens,
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

    # Set context manager config
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
        extra_body=THINKING_OFF_EXTRA_BODY,
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


# ============ Message Processing Functions ============

def process_agent_message(chunk: str) -> tuple[str, str]:
    """
    Parse JSON message returned by agent_run

    Args:
        chunk: JSON string

    Returns:
        (message_type, message_content) tuple
    """
    try:
        data = json.loads(chunk)
        return data.get("type", ""), data.get("content", "")
    except json.JSONDecodeError:
        return "", chunk


class AgentRunResult:
    """Agent run result wrapper"""
    def __init__(self):
        self.final_answer: str = ""
        self.full_response: str = ""
        self.message_type_count: dict = {}
        self.step_count: int = 0
        self.errors: list = []
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

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
    Run Agent and track message statistics

    Args:
        agent_run_info: Agent run info
        on_final_answer: Callback when final_answer is received
        on_error: Callback when error is received
        debug: Whether to print debug info

    Returns:
        AgentRunResult object containing final result and statistics

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

        # Count message types
        if msg_type in TRACKED_MESSAGE_TYPES:
            result.message_type_count[msg_type] = result.message_type_count.get(msg_type, 0) + 1

            if msg_type in ["step_count", "final_answer"]:
                result.step_count += 1

        # Handle final answer
        if msg_type == "final_answer":
            result.final_answer = msg_content
            result.full_response += msg_content
            if on_final_answer:
                on_final_answer(msg_content)

        # Handle error
        elif msg_type == "error":
            result.errors.append(msg_content)
            if on_error:
                on_error(msg_content)

        # Handle token_count — accumulate real main-LLM token usage
        elif msg_type == "token_count":
            try:
                token_data = json.loads(msg_content)
                result.total_input_tokens += token_data.get("step_input_tokens", 0) or 0
                result.total_output_tokens += token_data.get("step_output_tokens", 0) or 0
            except (json.JSONDecodeError, TypeError):
                pass

    # Fallback when no final answer
    if not result.final_answer:
        result.final_answer = result.full_response if result.full_response else "(No response received)"

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