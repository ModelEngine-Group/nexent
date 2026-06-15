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
    """Create parent ModuleType entries with __path__ so sub-package imports work.

    If a package is already registered (e.g. pytest discovers ``test/sdk/``
    as a real ``sdk`` package), we prepend the real SDK directory to its
    ``__path__`` so that ``sdk.nexent.*`` resolves through the real source tree.
    """
    for name, pkg_dir in [
        ("sdk",                    _SDK_ROOT),
        ("sdk.nexent",             os.path.join(_SDK_ROOT, "nexent")),
        ("sdk.nexent.core",        os.path.join(_SDK_ROOT, "nexent", "core")),
        ("sdk.nexent.core.agents", _AGENTS_DIR),
        ("sdk.nexent.core.utils",  os.path.join(_SDK_ROOT, "nexent", "core", "utils")),
    ]:
        if name in sys.modules:
            mod = sys.modules[name]
            # Prepend so the real SDK directory is searched FIRST
            if hasattr(mod, "__path__") and pkg_dir not in mod.__path__:
                mod.__path__.insert(0, pkg_dir)
        else:
            mod = ModuleType(name)
            mod.__path__ = [pkg_dir]
            mod.__package__ = name
            sys.modules[name] = mod

    # Stub for agent_model classes used by manager.py (lazy imports).
    # These classes are referenced inside manager._get_strategy() and
    # manager.build_system_prompt(). Create minimal stubs so that the
    # test harness can exercise those code paths.
    _agent_model_stub = ModuleType("sdk.nexent.core.agents.agent_model")

    class _BaseStrategy:
        """Minimal strategy base that passes through all components."""
        def select_components(self, components, budget, component_budgets):
            return components

    class _FullStrategy(_BaseStrategy):
        @staticmethod
        def get_strategy_name():
            return "full"

    class _TokenBudgetStrategy(_BaseStrategy):
        @staticmethod
        def get_strategy_name():
            return "token_budget"

    class _BufferedStrategy(_BaseStrategy):
        def __init__(self, buffer_size=5):
            self.buffer_size = buffer_size

        @staticmethod
        def get_strategy_name():
            return "buffered"

    class _PriorityWeightedStrategy(_BaseStrategy):
        def __init__(self, relevance_threshold=0.5):
            self.relevance_threshold = relevance_threshold

        @staticmethod
        def get_strategy_name():
            return "priority"

    _agent_model_stub.FullStrategy             = _FullStrategy
    _agent_model_stub.TokenBudgetStrategy      = _TokenBudgetStrategy
    _agent_model_stub.BufferedStrategy         = _BufferedStrategy
    _agent_model_stub.PriorityWeightedStrategy = _PriorityWeightedStrategy
    _agent_model_stub.ContextStrategy          = _BaseStrategy

    # ContextComponent stubs used by build_system_prompt / tests
    class _ContextComponent:
        component_type: str = ""
        priority: int = 10
        token_estimate: int = 0
        _content: str = ""
        metadata: dict = {}

    class _SystemPromptComponent(_ContextComponent):
        pass

    _agent_model_stub.ContextComponent      = _ContextComponent
    _agent_model_stub.SystemPromptComponent = _SystemPromptComponent
    _agent_model_stub.ToolsComponent         = _ContextComponent
    _agent_model_stub.SkillsComponent        = _ContextComponent
    _agent_model_stub.MemoryComponent        = _ContextComponent
    _agent_model_stub.KnowledgeBaseComponent = _ContextComponent
    _agent_model_stub.ManagedAgentsComponent = _ContextComponent
    _agent_model_stub.ExternalAgentsComponent = _ContextComponent

    sys.modules["sdk.nexent.core.agents.agent_model"] = _agent_model_stub

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


_load_file_module("sdk.nexent.core.agents.summary_cache",
                   _agents_file("summary_cache.py"), "sdk.nexent.core.agents")
_load_file_module("sdk.nexent.core.agents.summary_config",
                   _agents_file("summary_config.py"), "sdk.nexent.core.agents")


# ── 6. Load agent_context submodules in dependency order ────────────

# Submodules must be loaded in topological (dependency) order.
# Each module uses relative imports (from .X import ...) that we
# satisfy by pre-loading dependencies into sys.modules first.
#
# Dependency graph (no circular deps):
#   offload_store, summary_step (leaf, no intra-package deps)
#   budget (imports from summary_step)
#   step_renderer (imports from budget, offload_store)
#   llm_summary (imports from step_renderer)
#   previous_compression (imports from budget, step_renderer, llm_summary)
#   current_compression (imports from budget, step_renderer, llm_summary)
#   stats_export (no intra-package deps beyond summary_cache)
#   manager (imports from all above)

_AC_PREFIX = "sdk.nexent.core.agents.agent_context"
_AC_PKG    = _AC_PREFIX

# Leaf modules (no intra-package dependencies)
_load_file_module(f"{_AC_PREFIX}.offload_store", _ac_file("offload_store.py"), _AC_PKG)
_load_file_module(f"{_AC_PREFIX}.summary_step",   _ac_file("summary_step.py"),   _AC_PKG)

# Core modules (depend on leaf modules)
_load_file_module(f"{_AC_PREFIX}.budget",                _ac_file("budget.py"),                _AC_PKG)
_load_file_module(f"{_AC_PREFIX}.step_renderer",         _ac_file("step_renderer.py"),         _AC_PKG)
_load_file_module(f"{_AC_PREFIX}.llm_summary",           _ac_file("llm_summary.py"),           _AC_PKG)
_load_file_module(f"{_AC_PREFIX}.previous_compression",  _ac_file("previous_compression.py"),  _AC_PKG)
_load_file_module(f"{_AC_PREFIX}.current_compression",   _ac_file("current_compression.py"),   _AC_PKG)
_load_file_module(f"{_AC_PREFIX}.stats_export",          _ac_file("stats_export.py"),          _AC_PKG)

# Manager depends on all above
_load_file_module(f"{_AC_PREFIX}.manager", _ac_file("manager.py"), _AC_PKG)

# Create the agent_context package module that re-exports public names
_ctx_mod = ModuleType(_AC_PREFIX)
_ctx_mod.__package__ = _AC_PKG
_ctx_mod.__path__ = [_AC_DIR]
# Re-export key names from manager so that ``agent_context.ContextManager`` works
_manager_mod = sys.modules[f"{_AC_PREFIX}.manager"]
_ctx_mod.ContextManager        = _manager_mod.ContextManager
_ctx_mod.ContextManagerConfig  = _manager_mod.ContextManagerConfig
_ctx_mod.CompressionCallRecord = sys.modules["sdk.nexent.core.agents.summary_cache"].CompressionCallRecord
_ctx_mod.PreviousSummaryCache  = sys.modules["sdk.nexent.core.agents.summary_cache"].PreviousSummaryCache
_ctx_mod.CurrentSummaryCache   = sys.modules["sdk.nexent.core.agents.summary_cache"].CurrentSummaryCache
_ctx_mod.SummaryTaskStep       = sys.modules[f"{_AC_PREFIX}.summary_step"].SummaryTaskStep
_ctx_mod.format_summary_output = sys.modules[f"{_AC_PREFIX}.llm_summary"].format_summary_output
_ctx_mod._is_context_length_error = sys.modules[f"{_AC_PREFIX}.llm_summary"]._is_context_length_error
_ctx_mod.compress_history_offline = sys.modules[f"{_AC_PREFIX}.step_renderer"].compress_history_offline
_ctx_mod.OffloadStore          = sys.modules[f"{_AC_PREFIX}.offload_store"].OffloadStore
sys.modules[_AC_PREFIX] = _ctx_mod


# ── 7. Re-export public names (mirrors original monolithic imports) ──

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
