# -*- coding: utf-8 -*-
"""
Shared utilities for building and running nexent agents in benchmarks.

Provides:
1. Fine-grained context-item and prompt-template construction
2. AgentRunInfo construction (standard and custom-prompt variants)
3. Message-stream processing and statistics
"""
import json
import logging
import os
import re
import sys
import time
from typing import Callable, Optional

from dotenv import load_dotenv  # noqa: E402


# ============ Environment Setup ============
# Add parent directory to sys.path so paths.py can be found, then import it.
# paths.py resolves PROJECT_ROOT/SDK_DIR/BACKEND_DIR via .git discovery and
# injects them into sys.path automatically - no manual path manipulation needed.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402, F401 - side-effect: adds sdk/, backend/ to sys.path
from utils.context_utils import build_context_inputs  # noqa: E402
from utils.prompt_template_utils import get_agent_prompt_template  # noqa: E402

from nexent.core.agents.agent_model import (  # noqa: E402
    AgentConfig,
    AgentHistory,
    AgentRunInfo,
    ModelConfig,
    ToolConfig,
)
from nexent.core.agents.context import (
    ContextItemInput,  # noqa: E402
    ContextManagerConfig,  # noqa: E402
)
from nexent.core.agents.run_agent import agent_run  # noqa: E402
from nexent.core.utils.observer import MessageObserver  # noqa: E402


logging.getLogger("smolagents").setLevel(logging.WARNING)
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

# ============ Default Prompt Templates ============
DEFAULT_DUTY_PROMPT = """You are an intelligent assistant focused on helping users solve problems. You need to:
1. Understand the user's needs and provide accurate answers
2. Maintain a friendly and professional attitude
3. Remember key information from the conversation"""

DEFAULT_CONSTRAINT_PROMPT = """1. Do not generate harmful content
2. Comply with laws and regulations
3. Be honest with users when uncertain"""

DEFAULT_FEW_SHOTS_PROMPT = ""

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
    "tool",                    # real tool name and arguments
    "search_content",          # detailed search result records
}


def build_prompt_templates(
    language: str = "zh",
    is_manager: bool = False
) -> dict:
    """Build non-context templates required by CoreAgent."""
    prompt_templates = get_agent_prompt_template(is_manager=is_manager, language=language)
    prompt_templates["system_prompt"] = ""
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
    current_time: Optional[str] = None,
    model_factory: Optional[str] = None,
    prompt_components: Optional[dict] = None,
) -> AgentRunInfo:
    """
    Construct AgentRunInfo with ContextManager-based stable context.

    Args:
        query: User query
        history: Conversation history
        duty_prompt: Duty prompt (empty uses default)
        constraint_prompt: Constraint prompt (empty uses default)
        few_shots_prompt: Few-shot prompt
        fallback_prompt: Optional single custom system component used when no
                         segmented prompt fields are supplied
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
        model_factory=model_factory,
    )

    context_items = build_context_inputs(
        duty=duty,
        constraint=constraint,
        few_shots=few_shots,
        language=language,
        is_manager=is_manager,
        tools={tool.name: tool for tool in tools},
        skills=skills or [],
        managed_agents={agent.name: agent for agent in managed_agents},
        external_a2a_agents={},
        memory_list=[],
        knowledge_base_summary="",
    )
    if prompt_components:
        component_item_ids = {
            "basic_information": "system:header",
            "duty_prompt": "system:duty",
            "constraint_prompt": "system:constraint",
            "execution_prompt": "system:execution_flow",
            "resource_prompt": "system:available_resources_header",
            "code_rules_prompt": "system:code_norms",
        }
        by_item_id = {
            item_id: component_name
            for component_name, item_id in component_item_ids.items()
        }
        context_items = [
            item.model_copy(update={
                "content": {
                    "text": (
                        prompt_components[by_item_id[item.id]].get("content", "")
                        if isinstance(prompt_components[by_item_id[item.id]], dict)
                        else str(prompt_components[by_item_id[item.id]])
                    )
                }
            })
            if item.id in by_item_id and by_item_id[item.id] in prompt_components
            else item
            for item in context_items
        ]
    if fallback_prompt and not any((duty_prompt, constraint_prompt, few_shots_prompt)):
        context_items = [ContextItemInput(
            id="system:fallback",
            type="system",
            content={"text": fallback_prompt},
        )]

    prompt_templates = build_prompt_templates(language=language, is_manager=is_manager)
    if "final_answer_contract" in (prompt_components or {}):
        final_contract = prompt_components["final_answer_contract"]
        prompt_templates["final_answer"] = (
            final_contract.get("content", {})
            if isinstance(final_contract, dict)
            else final_contract
        )

    # Set context manager config
    cm_config = context_manager_config or ContextManagerConfig()


    agent_config = AgentConfig(
        name=agent_name,
        description=agent_description,
        tools=tools,
        max_steps=max_steps,
        model_name="main_model",
        prompt_templates=prompt_templates,
        managed_agents=managed_agents,
        context_manager_config=cm_config,
        context_items=context_items,
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
    model_factory: Optional[str] = None,
) -> AgentRunInfo:
    """
    Build AgentRunInfo with a custom system context item.

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
        model_factory=model_factory,
    )

    prompt_templates = build_prompt_templates(language=language, is_manager=is_manager)

    agent_config = AgentConfig(
        name=agent_name,
        description=agent_description,
        tools=tools,
        max_steps=max_steps,
        model_name="main_model",
        prompt_templates=prompt_templates,
        managed_agents=managed_agents,
        context_manager_config=context_manager_config or ContextManagerConfig(),
        context_items=[
            ContextItemInput(
                id="system:custom",
                type="system",
                content={"text": system_prompt},
            )
        ],
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


_METADATA_UNSUPPORTED_TOOLS = {
    "KnowledgeBaseSearchTool",
    "DifySearchTool",
    "DataMateSearchTool",
    "HaotianSearchTool",
    "StoreMemoryTool",
    "SearchMemoryTool",
}
_ANALYZE_TOOL_CLASSES = {
    "AnalyzeTextFileTool",
    "AnalyzeImageTool",
    "ExtractImageTextTool",
    "AnalyzeAudioTool",
    "AnalyzeVideoTool",
}


def _build_storage_client():
    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    if not all([endpoint, access_key, secret_key]):
        return None
    from nexent.storage.minio import MinIOStorageClient
    return MinIOStorageClient(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        region=os.getenv("MINIO_REGION"),
        default_bucket=os.getenv("MINIO_DEFAULT_BUCKET"),
        secure=os.getenv("MINIO_SECURE", "true").lower() == "true",
    )


def _build_vlm_model():
    api_url = os.getenv("VLM_API_URL") or os.getenv("LLM_API_URL")
    api_key = os.getenv("VLM_API_KEY") or os.getenv("LLM_API_KEY")
    model_name = os.getenv("VLM_MODEL_NAME") or os.getenv("LLM_MODEL_NAME")
    temperature = float(os.getenv("VLM_TEMPERATURE", "0"))
    if not all([api_url, api_key, model_name]):
        return None
    from nexent.core.models.openai_vlm import OpenAIVLModel
    return OpenAIVLModel(
        observer=MessageObserver(),
        model_id=model_name,
        api_base=api_url,
        api_key=api_key,
        temperature=temperature,
        ssl_verify=False,
    )


def _build_llm_model():
    api_url = os.getenv("LLM_API_URL")
    api_key = os.getenv("LLM_API_KEY")
    model_name = os.getenv("LLM_MODEL_NAME")
    if not all([api_url, api_key, model_name]):
        return None
    from nexent.core.models.openai_long_context_model import OpenAILongContextModel
    max_tokens = os.getenv("LLM_MAX_TOKENS")
    return OpenAILongContextModel(
        observer=MessageObserver(),
        model_id=model_name,
        api_base=api_url,
        api_key=api_key,
        max_context_tokens=int(max_tokens) if max_tokens else 128000,
        ssl_verify=False,
    )


def _build_analyze_tool_metadata(class_name: str) -> dict:
    metadata = {}
    storage_client = _build_storage_client()
    if storage_client:
        metadata["storage_client"] = storage_client
    if class_name == "AnalyzeTextFileTool":
        llm_model = _build_llm_model()
        if llm_model:
            metadata["llm_model"] = llm_model
        data_process_url = os.getenv("DATA_PROCESS_SERVICE")
        if data_process_url:
            metadata["data_process_service_url"] = data_process_url
    else:
        vlm_model = _build_vlm_model()
        if vlm_model:
            metadata["vlm_model"] = vlm_model
    return metadata


def build_tools_from_yaml(
    tools_yaml: list,
    *,
    include_runtime_metadata: bool = True,
) -> list[ToolConfig]:
    """Reconstruct ToolConfig objects from exported YAML.

    Snapshot-only callers disable runtime metadata so exporting schemas never
    initializes storage or model clients.
    """
    tool_configs = []
    skipped = []
    for entry in tools_yaml or []:
        if not entry.get("enabled", True):
            continue
        class_name = entry.get("tool_class", "")
        tool_name = entry.get("tool_name", "")
        if class_name in _METADATA_UNSUPPORTED_TOOLS:
            skipped.append(f"{tool_name} ({class_name})")
            continue
        metadata = (
            _build_analyze_tool_metadata(class_name)
            if include_runtime_metadata and class_name in _ANALYZE_TOOL_CLASSES
            else None
        )
        tool_configs.append(ToolConfig(
            class_name=class_name,
            name=tool_name,
            description=entry.get("tool_description", ""),
            inputs=entry.get("tool_inputs"),
            output_type=entry.get("tool_output_type"),
            params=entry.get("tool_params", {}),
            source=entry.get("tool_source", "local"),
            usage=entry.get("tool_usage"),
            metadata=metadata,
        ))
    if skipped:
        print(
            f"  WARNING: Skipped {len(skipped)} tools requiring external services: "
            f"{', '.join(skipped)}"
        )
    return tool_configs


def inject_production_managed_tools(
    tools: list[ToolConfig],
    *,
    agent_id: int,
    tenant_id: str,
    version_no: int,
    local_skills_dir: str | None,
) -> list[ToolConfig]:
    """Mirror production's passive parallel and builtin skill-tool assembly."""
    from nexent.core.tools.parallel_executor import ParallelExecutorTool

    existing_names = {tool.name for tool in tools}
    skill_context = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "version_no": version_no,
        "_benchmark_assembly_origin": "injected_builtin",
    }
    params = {"local_skills_dir": local_skills_dir}
    definitions = (
        (
            "RunSkillScriptTool",
            "run_skill_script",
            "Execute a skill script with given parameters. Use this to run "
            "Python or shell scripts that are part of a skill.",
            '{"skill_name": "str", "script_path": "str", "params": "str"}',
        ),
        (
            "ReadSkillMdTool",
            "read_skill_md",
            "Read skill execution guide and optional additional files. Always "
            "reads SKILL.md first, then optionally reads additional files.",
            '{"skill_name": "str", "additional_files": "list[str]"}',
        ),
        (
            "ReadSkillConfigTool",
            "read_skill_config",
            "Read the config.yaml file from a skill directory. Returns JSON "
            "containing configuration variables needed for skill workflows.",
            '{"skill_name": "str"}',
        ),
        (
            "WriteSkillFileTool",
            "write_skill_file",
            "Write content to a file within a skill directory. Creates parent "
            "directories if they do not exist.",
            '{"skill_name": "str", "file_path": "str", "content": "str"}',
        ),
    )
    injected: list[ToolConfig] = []
    if ParallelExecutorTool.name not in existing_names:
        injected.append(ToolConfig(
            class_name=ParallelExecutorTool.__name__,
            name=ParallelExecutorTool.name,
            description=ParallelExecutorTool.description,
            inputs=json.dumps(ParallelExecutorTool.inputs, ensure_ascii=False),
            output_type=ParallelExecutorTool.output_type,
            params={},
            source="local",
            metadata={"_benchmark_assembly_origin": "injected_system"},
        ))
    injected.extend(
        ToolConfig(
            class_name=class_name,
            name=name,
            description=description,
            inputs=inputs,
            output_type="string",
            params=params,
            source="builtin",
            usage="builtin",
            metadata=skill_context,
        )
        for class_name, name, description, inputs in definitions
        if name not in existing_names
    )
    return [*tools, *injected]


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


def _parse_agent_message(chunk: str) -> tuple[str, object, dict]:
    """Parse a stream chunk while preserving optional observer metadata."""
    try:
        data = json.loads(chunk)
        if not isinstance(data, dict):
            return "", chunk, {}
        return data.get("type", ""), data.get("content", ""), data
    except json.JSONDecodeError:
        return "", chunk, {}


class AgentRunResult:
    """Store an agent run result and its benchmark metrics."""

    def __init__(self):
        self.final_answer: str = ""
        self.full_response: str = ""
        self.message_type_count: dict = {}
        self.step_count: int = 0
        self.errors: list = []
        self.total_input_tokens: int = 0
        self.total_api_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.steps: list = []
        self.compression_calls: int = 0
        # ContextManager distinguishes model-based history summarization from
        # deterministic item compaction. ``compression_calls`` only covers the
        # former, so track the latter separately for benchmark evidence.
        self.deterministic_compaction_calls: int = 0
        self.compression_input_tokens: int = 0
        self.compression_output_tokens: int = 0
        self.compression_cache_hits: int = 0
        self.compression_cache_types: list = []
        self.summary_cache_hits: int = 0
        self.summary_cache_types: list = []
        self.total_uncompressed_est_tokens: int = 0
        self.provider_cache_available_calls: int = 0
        self.provider_cache_hit_calls: int = 0
        self.provider_cached_input_tokens: int = 0
        self.provider_uncached_input_tokens: int = 0
        self.provider_cache_statuses: set[str] = set()
        self.provider_cache_metrics_sources: set[str] = set()

        # Compute net token savings from the collected context metrics.
        self.net_token_saving: int = 0

        # Track wall-clock latency for the complete agent run.
        self.wall_clock_seconds: float = 0.0
        self.step_durations: list = []

        # Track the largest estimated context observed during the run.
        self.peak_context_tokens: int = 0
        self.peak_context_step: int = 0
        self.processing_mode: str = ""
        self.soft_budget_tokens: int = 0
        self.hard_budget_tokens: int = 0
        self.max_raw_context_tokens: int = 0
        self.over_soft_budget: bool = False
        self.over_hard_budget: bool = False

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
    _wall_start = time.monotonic()
    current_step = None
    initial_query = agent_run_info.query
    agent_config = getattr(agent_run_info, "agent_config", None)
    context_config = getattr(agent_config, "context_manager_config", None)
    if context_config is not None:
        result.processing_mode = str(
            getattr(context_config, "processing_mode", "") or ""
        )
        result.soft_budget_tokens = int(
            getattr(context_config, "soft_input_budget_tokens", 0)
            or getattr(context_config, "token_threshold", 0)
            or 0
        )
        result.hard_budget_tokens = int(
            getattr(context_config, "hard_input_budget_tokens", 0) or 0
        )

    async for chunk in agent_run(agent_run_info):
        if not chunk:
            continue

        msg_type, msg_content, msg_data = _parse_agent_message(chunk)

        if debug:
            print(f"[DEBUG] Type={msg_type}, Content Length={len(msg_content)}",
                  file=sys.stderr, flush=True)

        # Count message types
        if msg_type in TRACKED_MESSAGE_TYPES:
            result.message_type_count[msg_type] = result.message_type_count.get(msg_type, 0) + 1

            if msg_type == "step_count":
                result.step_count += 1
                current_step = {
                    "step_number": result.step_count,
                    "query": initial_query if result.step_count == 1 else "",
                    "thinking": "",
                    "deep_thinking": "",
                    "main_output": "",
                    "code": "",
                    "tool_call": "",
                    "observation": "",
                    "web_events": [],
                    "token_usage": None,
                }
                result.steps.append(current_step)

        if msg_type == "model_output_thinking" and current_step is not None:
            current_step["thinking"] += msg_content
        elif msg_type == "model_output_deep_thinking" and current_step is not None:
            current_step["deep_thinking"] += msg_content
        elif msg_type == "model_output" and current_step is not None:
            current_step["main_output"] += msg_content
        elif msg_type == "model_output_code" and current_step is not None:
            current_step["code"] += msg_content
        elif msg_type == "parse" and current_step is not None:
            current_step["tool_call"] += msg_content
        elif msg_type == "execution_logs" and current_step is not None:
            current_step["observation"] += msg_content
        elif msg_type == "tool" and current_step is not None:
            current_step["web_events"].append({
                "event_type": "tool_call",
                "tool_name": msg_data.get("tool_name", ""),
                "tool_arguments": msg_data.get("tool_arguments", {}),
            })
        elif msg_type == "search_content" and current_step is not None:
            current_step["web_events"].append({
                "event_type": "search_content",
                "content": msg_content,
            })

        # Handle final answer
        if msg_type == "final_answer":
            result.final_answer = msg_content
            result.full_response += msg_content
            result.steps.append({
                "step_number": "final_answer",
                "query": initial_query,
                "thinking": "",
                "deep_thinking": "",
                "main_output": msg_content,
                "code": "",
                "tool_call": "",
                "observation": "",
                "web_events": [],
                "token_usage": None,
            })
            if on_final_answer:
                on_final_answer(msg_content)

        # Handle error
        elif msg_type == "error":
            result.errors.append(msg_content)
            hard_budget_match = re.search(
                r"after compaction:\s*(\d+)\s*>\s*(\d+)\s*tokens",
                msg_content,
            )
            if hard_budget_match:
                actual_tokens, hard_budget = map(int, hard_budget_match.groups())
                result.over_hard_budget = True
                result.hard_budget_tokens = hard_budget
                if actual_tokens > result.peak_context_tokens:
                    result.peak_context_tokens = actual_tokens
                    result.peak_context_step = result.step_count
            if current_step is not None:
                separator = "\n" if current_step["observation"] else ""
                current_step["observation"] += f"{separator}Error:\n{msg_content}"
            if on_error:
                on_error(msg_content)

        # Handle token_count - accumulate real main-LLM token usage
        elif msg_type == "token_count":
            try:
                token_data = json.loads(msg_content)
                api_input = token_data.get("step_input_tokens", 0) or 0
                processing_mode = token_data.get("context_processing_mode")
                if processing_mode:
                    result.processing_mode = processing_mode
                soft_budget = token_data.get("soft_input_budget_tokens")
                if soft_budget is None and not result.soft_budget_tokens:
                    soft_budget = token_data.get("token_threshold")
                hard_budget = token_data.get("hard_input_budget_tokens")
                if soft_budget:
                    result.soft_budget_tokens = int(soft_budget)
                if hard_budget:
                    result.hard_budget_tokens = int(hard_budget)
                result.total_input_tokens += (
                    token_data.get("estimated_context_tokens") or api_input
                )
                result.total_api_input_tokens += api_input
                result.total_output_tokens += token_data.get("step_output_tokens", 0) or 0
                if current_step is not None:
                    current_step["token_usage"] = {
                        "input_tokens": (
                            token_data.get("estimated_context_tokens") or api_input
                        ),
                        "api_input_tokens": api_input,
                        "output_tokens": token_data.get("step_output_tokens", 0) or 0,
                    }
                result.compression_calls += token_data.get("compression_calls", 0) or 0
                result.compression_input_tokens += token_data.get("compression_input_tokens", 0) or 0
                result.compression_output_tokens += token_data.get("compression_output_tokens", 0) or 0
                result.compression_cache_hits += token_data.get("compression_cache_hits", 0) or 0
                result.total_uncompressed_est_tokens += token_data.get("uncompressed_est_tokens", 0) or 0
                raw_context = token_data.get("uncompressed_est_tokens", 0) or 0
                result.max_raw_context_tokens = max(
                    result.max_raw_context_tokens, raw_context
                )
                if result.soft_budget_tokens and raw_context > result.soft_budget_tokens:
                    result.over_soft_budget = True
                    estimated_context = (
                        token_data.get("estimated_context_tokens", 0) or 0
                    )
                    if (
                        result.processing_mode == "adaptive_compact"
                        and estimated_context
                        and estimated_context < raw_context
                        and not (token_data.get("compression_calls", 0) or 0)
                    ):
                        result.deterministic_compaction_calls += 1
                cache_types = token_data.get("compression_cache_types", []) or []
                for cache_type in cache_types:
                    if cache_type not in result.compression_cache_types:
                        result.compression_cache_types.append(cache_type)
                    if cache_type in {"previous_cache_hit", "current_cache_hit"}:
                        result.summary_cache_hits += 1
                        if cache_type not in result.summary_cache_types:
                            result.summary_cache_types.append(cache_type)
                if current_step is not None:
                    current_step["compression"] = {
                        "calls": token_data.get("compression_calls", 0) or 0,
                        "input_tokens": token_data.get("compression_input_tokens", 0) or 0,
                        "output_tokens": token_data.get("compression_output_tokens", 0) or 0,
                        "summary_cache_hits": sum(
                            cache_type in {"previous_cache_hit", "current_cache_hit"}
                            for cache_type in cache_types
                        ),
                        "summary_cache_types": [
                            cache_type
                            for cache_type in cache_types
                            if cache_type in {"previous_cache_hit", "current_cache_hit"}
                        ],
                        "ratio": token_data.get("compression_ratio", 0.0),
                        "uncompressed_est_tokens": token_data.get(
                            "uncompressed_est_tokens", 0
                        ),
                        "estimated_context_tokens": token_data.get(
                            "estimated_context_tokens"
                        ),
                        "token_threshold": token_data.get("token_threshold"),
                    }
                provider_status = token_data.get("provider_cache_status")
                if provider_status:
                    result.provider_cache_statuses.add(provider_status)
                    result.provider_cache_metrics_sources.add(
                        token_data.get("provider_cache_metrics_source", "capability_unknown")
                    )
                    if provider_status == "available":
                        result.provider_cache_available_calls += 1
                        result.provider_cache_hit_calls += int(
                            bool(token_data.get("provider_cache_hit", False))
                        )
                        result.provider_cached_input_tokens += (
                            token_data.get("provider_cached_input_tokens", 0) or 0
                        )
                        result.provider_uncached_input_tokens += (
                            token_data.get("provider_uncached_input_tokens", 0) or 0
                        )
                    if current_step is not None:
                        current_step["provider_cache"] = {
                            "status": provider_status,
                            "metrics_source": token_data.get(
                                "provider_cache_metrics_source",
                                "capability_unknown",
                            ),
                            "hit": bool(token_data.get("provider_cache_hit", False)),
                            "cached_input_tokens": token_data.get(
                                "provider_cached_input_tokens", 0
                            ) or 0,
                            "uncached_input_tokens": token_data.get(
                                "provider_uncached_input_tokens", 0
                            ) or 0,
                        }

                # Record the duration reported for this step.
                step_duration = token_data.get("duration", 0.0) or 0.0
                if step_duration > 0:
                    result.step_durations.append(step_duration)
                    if current_step is not None:
                        current_step["duration_seconds"] = step_duration

                # Track the largest estimated context observed during the run. tracking
                estimated_ctx = token_data.get("estimated_context_tokens", 0) or 0
                if estimated_ctx > result.peak_context_tokens:
                    result.peak_context_tokens = estimated_ctx
                    result.peak_context_step = result.step_count
            except (json.JSONDecodeError, TypeError):
                pass

    # Fallback when no final answer
    if not result.final_answer:
        result.final_answer = result.full_response if result.full_response else "(No response received)"

    # Record total wall-clock time.
    result.wall_clock_seconds = round(time.monotonic() - _wall_start, 3)

    # Compute the net token saving for adaptive compaction.
    compression_overhead = (
        result.compression_input_tokens + result.compression_output_tokens
    )
    if (
        result.processing_mode == "adaptive_compact"
        and (
            result.compression_calls > 0
            or result.deterministic_compaction_calls > 0
        )
    ):
        result.net_token_saving = max(
            0,
            result.total_uncompressed_est_tokens
            - result.total_input_tokens
            - compression_overhead,
        )
    else:
        # Passthrough does not perform context compaction.  Differences between
        # raw estimates and provider/API token counts are measurement deltas,
        # not compression savings.
        result.net_token_saving = 0

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
