"""Verify the stable_bypass baseline refresh (manager.py).

Scenario:
  Call 1 (full compression): big previous-run history -> over budget, no cache
          -> full path runs, summarizes history, sets _previous_summary_cache,
          and sets _last_uncompressed_token_count = |orig1|.
  Call 2 (stable_bypass):    memory grew by one small current step; raw still
          over budget but effective (summary + 1 uncovered pair + small current)
          under budget and cache valid -> stable_bypass (cache hit, no LLM).

Before the fix, call 2 did NOT refresh _last_uncompressed_token_count, so the
reported baseline stayed frozen at |orig1|. After the fix it must equal |orig2|
(and thus be strictly larger than |orig1|).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smolagents.memory import AgentMemory, TaskStep, ActionStep
from smolagents.monitoring import Timing
from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.utils.token_estimation import msg_token_count


class _Usage:
    input_tokens = 10
    output_tokens = 5


class _Resp:
    def __init__(self, text):
        self.content = text
        self.token_usage = _Usage()


class FakeModel:
    def __call__(self, messages, stop_sequences=None):
        # Short valid summary so the previous cache is small.
        return _Resp(
            '{"task_overview":"t","completed_work":"c","key_decisions":"k",'
            '"pending_items":"","context_to_preserve":"p"}'
        )


def add_prev_pairs(mem, n, big):
    for i in range(n):
        mem.steps.append(TaskStep(task=f"previous task {i}"))
        a = ActionStep(step_number=i + 1, timing=Timing(start_time=0.0))
        a.action_output = big
        a.model_output = big
        mem.steps.append(a)


def orig_messages(mem):
    msgs = []
    msgs += mem.system_prompt.to_messages()
    for s in mem.steps:
        msgs += s.to_messages()
    return msgs


def main():
    # soft budget 1000, hard 1100. Big prev pairs drive raw over budget; small
    # current keeps effective under budget once the prev cache exists.
    cfg = ContextManagerConfig(enabled=True, token_threshold=1000, keep_recent_pairs=1)
    cm = ContextManager(config=cfg, max_steps=10)
    model = FakeModel()

    big = "x" * 4000  # ~1000 tokens per action (non-CJK /4)
    small = "y" * 40  # ~10 tokens

    # --- Call 1: 3 big prev pairs + small current (TaskStep + Action#1) ---
    mem = AgentMemory(system_prompt="SYSTEM PROMPT")
    add_prev_pairs(mem, 3, big)
    current_run_start_idx = len(mem.steps)  # current run starts here
    mem.steps.append(TaskStep(task="current query"))
    a1 = ActionStep(step_number=100, timing=Timing(start_time=0.0))
    a1.action_output = small
    a1.model_output = small
    mem.steps.append(a1)

    orig1 = orig_messages(mem)
    cm.compress_if_needed(model, mem, orig1, current_run_start_idx, context_overhead_tokens=0)
    stats1 = cm.get_step_compression_stats()
    lu1 = cm.get_token_counts()["last_uncompressed"]
    raw1 = msg_token_count(orig1, cfg.chars_per_token)
    print(f"Call 1 (full):  cache_hit={stats1['cache_hits']>0}  last_uncompressed={lu1}  raw={raw1}")
    assert stats1["cache_hits"] == 0, "call 1 must be a real compression, not a hit"
    assert lu1 == raw1, "full path must set last_uncompressed = raw memory size"

    # --- Call 2: append one more small current step -> memory grows ---
    a2 = ActionStep(step_number=101, timing=Timing(start_time=0.0))
    a2.action_output = small
    a2.model_output = small
    mem.steps.append(a2)
    orig2 = orig_messages(mem)
    cm.compress_if_needed(model, mem, orig2, current_run_start_idx, context_overhead_tokens=0)
    stats2 = cm.get_step_compression_stats()
    lu2 = cm.get_token_counts()["last_uncompressed"]
    raw2 = msg_token_count(orig2, cfg.chars_per_token)
    print(f"Call 2 (bypass): cache_hit={stats2['cache_hits']>0}  last_uncompressed={lu2}  raw={raw2}")

    # 1. Call 2 took the stable_bypass path (cache hit, no LLM compression).
    assert stats2["cache_hits"] >= 1, "call 2 must be a stable_bypass cache hit"
    # 2. The baseline refreshed to this step's raw memory (not frozen at lu1).
    assert lu2 == raw2, f"bypass must refresh baseline to raw ({lu2} != {raw2})"
    # 3. And therefore grew, since memory grew between calls.
    assert lu2 > lu1, f"baseline must grow on bypass ({lu2} <= {lu1})"

    print(f"\nGrowth: {lu1} -> {lu2} (delta {lu2 - lu1}), matches raw growth {raw1} -> {raw2}")
    print("RESULT: PASS (stable_bypass now refreshes the uncompressed baseline)")


if __name__ == "__main__":
    main()
