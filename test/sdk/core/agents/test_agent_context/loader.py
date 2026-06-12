"""
loader.py
─────────
Loads the agent_context package in isolation via importlib,
bypassing __init__.py chains that drag in unrelated heavy dependencies.

Also injects a fully-functional token_estimation stub so that the module
under test executes its real estimation logic without any external imports.

Since agent_context/ is now a package (directory), we load each submodule
manually via importlib in dependency order, then wire them together as
``sdk.nexent.core.agents.agent_context.*`` in ``sys.modules``.

Public names re-exported from this module are the same names that test files
used to import at the top of the original monolithic test file.
"""

import importlib.util
import os
import sys
from types import ModuleType
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stubs import register_smolagents_mocks, restore_real_smolagents

# ── 1. Register smolagents mocks (idempotent) ──────────────────
register_smolagents_mocks()


# ── 2. Build token_estimation stub ────────────────────────────

def _build_token_estimation_stub() -> ModuleType:
    """
    Return a ModuleType that mirrors sdk.nexent.core.utils.token_estimation,
    implementing every function used by agent_context.py.
    The logic here is identical to what was inlined in the original test file.
    """
    stub = ModuleType("sdk.nexent.core.utils.token_estimation")

    # ── helpers ──────────────────────────────────────────────

    def _is_cjk(char: str) -> bool:
        cp = ord(char)
        return (
            (0x4E00 <= cp <= 0x9FFF)
            or (0x3400 <= cp <= 0x4DBF)
            or (0x20000 <= cp <= 0x2A6DF)
            or (0x2A700 <= cp <= 0x2B73F)
            or (0x2B740 <= cp <= 0x2B81F)
            or (0x2B820 <= cp <= 0x2CEAF)
            or (0xF900 <= cp <= 0xFAFF)
            or (0x2F800 <= cp <= 0x2FA1F)
            or (0x3000 <= cp <= 0x303F)
        )

    def estimate_tokens_text(text: str) -> int:
        if not text:
            return 0
        cjk_count     = sum(1 for c in text if _is_cjk(c))
        non_cjk_count = len(text) - cjk_count
        return max(1, int((non_cjk_count / 4.0) + (cjk_count / 1.1)))

    def _extract_text_from_chat_message(msg):
        if isinstance(msg.content, str):
            return msg.content
        if isinstance(msg.content, list):
            parts = [
                block.get("text", "")
                for block in msg.content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "".join(parts) if parts else None
        return None

    def _extract_text_from_messages(msgs):
        parts = []
        for msg in msgs:
            t = _extract_text_from_chat_message(msg)
            if t is not None:
                parts.append(t)
        return "".join(parts) if parts else None

    def msg_char_count(msg):
        if isinstance(msg, list):
            return sum(msg_char_count(m) for m in msg)
        text = _extract_text_from_chat_message(msg)
        if text is not None:
            return len(text)
        return 0

    def msg_token_count(msg, chars_per_token=1.5):
        if isinstance(msg, list):
            text           = ""
            fallback_chars = 0
            for m in msg:
                t = _extract_text_from_chat_message(m)
                if t is not None:
                    text += t
                else:
                    fallback_chars += msg_char_count(m)
            tokens = estimate_tokens_text(text) if text else 0
            if fallback_chars:
                tokens += int(fallback_chars / chars_per_token)
            return tokens
        text = _extract_text_from_chat_message(msg)
        if text is not None:
            return estimate_tokens_text(text)
        return int(msg_char_count(msg) / chars_per_token)

    def estimate_tokens_for_steps(steps, chars_per_token=1.5):
        return sum(msg_token_count(step.to_messages(), chars_per_token) for step in steps)

    def estimate_tokens_for_system_prompt(memory, chars_per_token=1.5):
        if not memory.system_prompt:
            return 0
        sys_msgs = memory.system_prompt.to_messages()
        text     = _extract_text_from_messages(sys_msgs)
        if text is not None:
            return estimate_tokens_text(text)
        return int(msg_char_count(sys_msgs) / chars_per_token)

    def estimate_tokens(memory, chars_per_token=1.5):
        """
        Collect ALL messages into one flat list, then call estimate_tokens_text
        exactly once. This eliminates per-step int() truncation drift and
        keeps the result consistent with msg_token_count(flat_list).
        """
        all_msgs = []
        if memory.system_prompt:
            all_msgs.extend(memory.system_prompt.to_messages())
        for step in memory.steps:
            all_msgs.extend(step.to_messages())

        text = _extract_text_from_messages(all_msgs)
        if text is not None:
            return estimate_tokens_text(text)
        return int(msg_char_count(all_msgs) / chars_per_token)

    # ── wire into the stub module ─────────────────────────────
    stub.estimate_tokens_text              = estimate_tokens_text
    stub.estimate_tokens                   = estimate_tokens
    stub.estimate_tokens_for_steps         = estimate_tokens_for_steps
    stub.estimate_tokens_for_system_prompt = estimate_tokens_for_system_prompt
    stub.msg_char_count                    = msg_char_count
    stub.msg_token_count                   = msg_token_count
    stub._extract_text_from_messages       = _extract_text_from_messages

    return stub


# ── 3. Path helpers ─────────────────────────────────────────────

_HERE_DIR   = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE_DIR)))))
_SDK_ROOT   = os.path.join(_REPO_ROOT, "sdk")
_AGENTS_DIR = os.path.join(_SDK_ROOT, "nexent", "core", "agents")
_AC_DIR     = os.path.join(_AGENTS_DIR, "agent_context")


def _agents_file(filename: str) -> str:
    """Absolute path to a file in sdk/nexent/core/agents/."""
    return os.path.join(_AGENTS_DIR, filename)


def _ac_file(filename: str) -> str:
    """Absolute path to a file in sdk/nexent/core/agents/agent_context/."""
    return os.path.join(_AC_DIR, filename)


# ── 4. Register stub package hierarchy ───────────────────────

def _register_stub_packages():
    """Create empty parent ModuleType entries so the dotted import chain resolves."""
    for name in [
        "sdk",
        "sdk.nexent",
        "sdk.nexent.core",
        "sdk.nexent.core.agents",
        "sdk.nexent.core.utils",
    ]:
        if name not in sys.modules:
            sys.modules[name] = ModuleType(name)

    token_est_key = "sdk.nexent.core.utils.token_estimation"
    if token_est_key not in sys.modules:
        sys.modules[token_est_key] = _build_token_estimation_stub()


_register_stub_packages()


# ── 5. Load summary_cache and summary_config modules ────────────────────

def _load_file_module(full_name: str, filepath: str, package: str):
    """Load a single .py file as a module via importlib."""
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, filepath)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = package
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_ctx_mod = _load_agent_context()

# ── 5. Re-export public names (mirrors original monolithic imports) ──

ContextManager        = _ctx_mod.ContextManager
ContextManagerConfig  = _ctx_mod.ContextManagerConfig
PreviousSummaryCache  = _ctx_mod.PreviousSummaryCache
CurrentSummaryCache   = _ctx_mod.CurrentSummaryCache
SummaryTaskStep       = _ctx_mod.SummaryTaskStep
TaskStep              = _manager_mod.TaskStep
ActionStep            = _manager_mod.ActionStep
AgentMemory           = _manager_mod.AgentMemory
ChatMessage           = _manager_mod.ChatMessage
MessageRole           = sys.modules["smolagents.models"].MessageRole
CompressionCallRecord = _ctx_mod.CompressionCallRecord

# Export ContextComponent classes
ContextComponent         = _agent_model_mod.ContextComponent
SystemPromptComponent    = _agent_model_mod.SystemPromptComponent
ToolsComponent           = _agent_model_mod.ToolsComponent
SkillsComponent          = _agent_model_mod.SkillsComponent
MemoryComponent          = _agent_model_mod.MemoryComponent
KnowledgeBaseComponent   = _agent_model_mod.KnowledgeBaseComponent
ManagedAgentsComponent   = _agent_model_mod.ManagedAgentsComponent
ExternalAgentsComponent  = _agent_model_mod.ExternalAgentsComponent

# Export ContextStrategy classes
ContextStrategy          = _agent_model_mod.ContextStrategy
FullStrategy             = _agent_model_mod.FullStrategy
TokenBudgetStrategy      = _agent_model_mod.TokenBudgetStrategy
BufferedStrategy         = _agent_model_mod.BufferedStrategy
PriorityWeightedStrategy = _agent_model_mod.PriorityWeightedStrategy

from stubs import _SystemPromptStep as SystemPromptStep

# ── 7a. Re-export OffloadStore ──────────────────────────────────
OffloadStore = _ctx_mod.OffloadStore

# ── 8. Re-export new standalone functions and classes ──────────────

from sdk.nexent.core.agents.agent_context.budget import (
    extract_pairs, action_content, pair_fingerprint, action_fingerprint,
    has_invoked_tools, is_observation_step, is_tool_call_step,
    is_prev_cache_valid, is_curr_cache_valid,
    trim_pairs_to_budget, trim_actions_to_budget,
)
from sdk.nexent.core.utils.token_estimation import (
    estimate_tokens, estimate_tokens_text, estimate_tokens_for_steps,
    estimate_tokens_for_system_prompt, msg_token_count, msg_char_count,
)
from sdk.nexent.core.agents.agent_context.step_renderer import StepRenderer, compress_history_offline
from sdk.nexent.core.agents.agent_context.llm_summary import LLMSummary, SummaryResult, format_summary_output
from sdk.nexent.core.agents.agent_context.previous_compression import PreviousCompressor, PreviousCompressResult
from sdk.nexent.core.agents.agent_context.current_compression import CurrentCompressor, CurrentCompressResult
from sdk.nexent.core.agents.agent_context.stats_export import (
    get_step_compression_stats, get_all_compression_stats,
    export_summary as export_summary_fn, get_token_counts,
)


# ── 9. Restore real smolagents for sibling test trees ───────────
# Restore real smolagents in sys.modules so sibling test trees (e.g.
# test/backend/utils/test_context_utils.py) that import the real
# nexent.core.agents path can do "from smolagents.memory import AgentMemory"
# without picking up our mock. The mock classes captured above as
# module-level attributes stay valid for our own unit tests, which
# never touch sys.modules['smolagents.*'] at runtime.
restore_real_smolagents()
