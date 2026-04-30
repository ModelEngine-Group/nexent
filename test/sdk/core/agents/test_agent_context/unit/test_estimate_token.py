"""
unit/test_estimate_token.py
Verify ContextManager._estimate_tokens(memory) and
ContextManager._msg_token_count(flat_messages) result consistency.
"""

import pytest

from factories import make_cm, make_memory_with_steps, make_original_messages, make_pair
from loader import AgentMemory, PreviousSummaryCache
from stubs import _SystemPromptStep


class TestEstimateTokenConsistency:
    """_estimate_tokens and _msg_token_count(flat) must return the same value."""

    def test_msg_token_count_equal_estimate_token_for_memory(self):
        cm = make_cm(enabled=True, threshold=10)
        memory = make_memory_with_steps(3)
        original = make_original_messages(memory)
        assert cm._estimate_tokens(memory) == cm._msg_token_count(original)


class TestEffectiveTokens:

    def test_effective_prev_tokens_no_cache(self):
        """No cache should equal raw estimation."""
        cm = make_cm()
        t, a = make_pair("task", "action")
        steps = [t, a]
        raw = cm._estimate_tokens_for_steps(steps)
        effective = cm._effective_prev_tokens(steps)
        assert effective == raw

    def test_effective_prev_tokens_with_valid_cache_less_than_raw(self):
        """Valid cache exists, effective tokens should be <= raw (summary shorter than full text)."""
        cm = make_cm()
        t, a = make_pair("X" * 200, "Y" * 200, 1)
        pairs = [(t, a)]
        fp = cm._pair_fingerprint(t.task, a.model_output)
        cm._previous_summary_cache = PreviousSummaryCache("short summary", 1, fp)
        steps = [t, a]
        raw = cm._estimate_tokens_for_steps(steps)
        effective = cm._effective_prev_tokens(steps)
        assert effective < raw

    def test_effective_curr_tokens_empty(self):
        cm = make_cm()
        assert cm._effective_curr_tokens([]) == 0

    def test_effective_tokens_sums_prev_and_curr(self):
        cm = make_cm()
        t1, a1 = make_pair("prev task", "prev action", 1)
        t2, a2 = make_pair("curr task", "curr action", 2)
        memory = AgentMemory(steps=[t1, a1, t2, a2])
        total = cm._effective_tokens(memory, current_run_start_idx=2)
        prev = cm._effective_prev_tokens([t1, a1])
        curr = cm._effective_curr_tokens([t2, a2])
        assert total == prev + curr