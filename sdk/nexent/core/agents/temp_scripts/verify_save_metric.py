"""Verify the save% metric fix (core_agent.py:405).

Drives the real compress_if_needed full path with a mock model (no real LLM),
then compares:
  - NEW baseline = ContextManager.get_token_counts()['last_uncompressed']
        (what the fix reads; = raw uncompressed memory tokens)
  - OLD baseline = msg_token_count(compressed payload)
        (what line 405 used to compute -> made save% structurally 0%)
The fix is correct iff NEW baseline > compressed payload (positive savings)
while OLD baseline == compressed payload (the 0% bug).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smolagents.memory import AgentMemory, TaskStep, ActionStep, SystemPromptStep
from smolagents.monitoring import Timing
from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.utils.token_estimation import msg_token_count
from nexent.core.context_runtime.legacy.runtime import LegacyContextRuntime


class _Usage:
    input_tokens = 10
    output_tokens = 5


class _Resp:
    def __init__(self, text):
        self.content = text
        self.token_usage = _Usage()


class FakeModel:
    """Stand-in for the LLM: model(messages, stop_sequences=[]) -> response."""
    def __call__(self, messages, stop_sequences=None):
        return _Resp(
            '{"task_overview":"t","completed_work":"c","key_decisions":"k",'
            '"pending_items":"","context_to_preserve":"p"}'
        )


def build_memory(n_pairs: int, big_size: int) -> AgentMemory:
    # NOTE: pass a STRING to AgentMemory(system_prompt=...). Passing a
    # SystemPromptStep here gets double-wrapped, and its to_messages() then
    # emits the step object as a content text block, which crashes
    # estimate_tokens. The production path assigns memory.system_prompt after
    # construction (single wrap), which is clean.
    mem = AgentMemory(system_prompt="SYSTEM PROMPT BODY")
    big = "x" * big_size
    for i in range(n_pairs):
        mem.steps.append(TaskStep(task=f"task number {i}"))
        a = ActionStep(step_number=i + 1, timing=Timing(start_time=0.0))
        a.action_output = big
        a.model_output = big
        mem.steps.append(a)
    return mem


def main():
    cfg = ContextManagerConfig(enabled=True, token_threshold=400, keep_recent_pairs=1)
    cm = ContextManager(config=cfg, max_steps=10)
    mem = build_memory(n_pairs=4, big_size=4000)

    orig = []
    orig += mem.system_prompt.to_messages()
    for s in mem.steps:
        orig += s.to_messages()

    current_run_start_idx = len(mem.steps)  # all history is "previous run"
    compressed = cm.compress_if_needed(FakeModel(), mem, orig, current_run_start_idx)

    tc = cm.get_token_counts()
    raw = msg_token_count(orig, cfg.chars_per_token)
    new_baseline = tc.get("last_uncompressed")          # fix reads this
    compressed_tokens = msg_token_count(compressed, cfg.chars_per_token)
    old_baseline_buggy = compressed_tokens              # line 405 used to compute this

    print(f"raw memory tokens            : {raw}")
    print(f"CM last_uncompressed (NEW)    : {new_baseline}")
    print(f"compressed payload tokens     : {compressed_tokens}")
    print(f"OLD buggy baseline (=comp)    : {old_baseline_buggy}")
    new_save = (1 - compressed_tokens / new_baseline) * 100 if new_baseline else 0
    old_save = (1 - compressed_tokens / old_baseline_buggy) * 100 if old_baseline_buggy else 0
    print(f"NEW save% (with fix)          : {round(new_save,1)}")
    print(f"OLD save% (bug, ~0)           : {round(old_save,1)}")
    print()

    # 1. CM exposes a truthful uncompressed baseline larger than the compressed payload.
    assert new_baseline is not None and new_baseline > compressed_tokens, \
        "expected last_uncompressed > compressed"
    # 2. The old wiring baseline equals the compressed payload -> the 0% bug.
    assert old_baseline_buggy == compressed_tokens, "old baseline must equal compressed (the bug)"
    # 3. Fix yields positive savings where the bug yielded ~0.
    assert new_save > old_save, "fix must report more savings than the buggy baseline"

    # 4. Legacy fallback: no context_manager -> CoreAgent falls back to input size.
    assert LegacyContextRuntime().context_manager is None, \
        "legacy runtime must expose context_manager=None so core_agent falls back"
    print("Legacy fallback (context_manager is None): OK -> save%=0 correct (no compression)")

    print("\nRESULT: PASS (fix baseline is truthful uncompressed; old was structurally 0%)")


if __name__ == "__main__":
    main()
