"""
loader.py
─────────
Loads sdk/nexent/core/agents/agent_context.py in isolation via importlib,
bypassing __init__.py chains that drag in unrelated heavy dependencies.

Also injects a fully-functional token_estimation stub so that the module
under test executes its real estimation logic without any external imports.

Public names re-exported from this module are the same names that test files
used to import at the top of the original monolithic test file.


"""

import importlib.util
import os
import sys
from types import ModuleType
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stubs import register_smolagents_mocks

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


# ── 3. Register stub package hierarchy ───────────────────────

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


# ── 3.5. Load summary_cache and summary_config modules ────────────────────

def _locate_module(module_name: str) -> str:
    """Resolve the absolute path to a module in sdk/nexent/core/agents."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here)))))
    filename = module_name + ".py"
    target = os.path.join(repo, "sdk", "nexent", "core", "agents", filename)
    if not os.path.exists(target):
        raise FileNotFoundError(f"Cannot locate {filename}. Expected: {target}")
    return target


def _load_summary_modules():
    """Load summary_cache.py and summary_config.py before agent_context.py."""
    for module_name in ["summary_cache", "summary_config"]:
        full_name = f"sdk.nexent.core.agents.{module_name}"
        if full_name in sys.modules:
            continue
        target = _locate_module(module_name)
        spec = importlib.util.spec_from_file_location(full_name, target)
        module = importlib.util.module_from_spec(spec)
        module.__package__ = "sdk.nexent.core.agents"
        sys.modules[full_name] = module
        spec.loader.exec_module(module)


_load_summary_modules()


# ── 4. Load agent_context.py via importlib ────────────────────

def _locate_agent_context() -> str:
    """
    Resolve the absolute path to agent_context.py.

    Directory layout assumed:
        <repo_root>/
            sdk/nexent/core/agents/agent_context.py
            tests/sdk/core/agents/         ← this file lives here
    """
    here   = os.path.dirname(os.path.abspath(__file__))
    # tests/sdk/core/agents → tests/sdk/core → tests/sdk → tests → repo_root
    repo   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here)))))
    target = os.path.join(repo, "sdk", "nexent", "core", "agents", "agent_context.py")
    if not os.path.exists(target):
        raise FileNotFoundError(
            f"Cannot locate agent_context.py.\n"
            f"Expected: {target}\n"
            f"Check the number of os.path.dirname levels in loader.py."
        )
    return target


def _load_agent_context():
    module_name = "sdk.nexent.core.agents.agent_context"
    if module_name in sys.modules:
        return sys.modules[module_name]

    target = _locate_agent_context()
    spec   = importlib.util.spec_from_file_location(module_name, target)
    module = importlib.util.module_from_spec(spec)
    module.__package__              = "sdk.nexent.core.agents"
    sys.modules[module_name]        = module
    spec.loader.exec_module(module)
    return module


_ctx_mod = _load_agent_context()

# ── 5. Re-export public names (mirrors original monolithic imports) ──

ContextManager        = _ctx_mod.ContextManager
ContextManagerConfig  = _ctx_mod.ContextManagerConfig
PreviousSummaryCache  = _ctx_mod.PreviousSummaryCache
CurrentSummaryCache   = _ctx_mod.CurrentSummaryCache
SummaryTaskStep       = _ctx_mod.SummaryTaskStep
TaskStep              = _ctx_mod.TaskStep
ActionStep            = _ctx_mod.ActionStep
AgentMemory           = _ctx_mod.AgentMemory
ChatMessage           = _ctx_mod.ChatMessage
MessageRole           = _ctx_mod.MessageRole
CompressionCallRecord = _ctx_mod.CompressionCallRecord
from stubs import _SystemPromptStep as SystemPromptStep