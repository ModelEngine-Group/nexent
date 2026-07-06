from factories import make_cm, make_pair
from loader import (
    PreviousSummaryCache, CurrentSummaryCache, ActionStep, ContextManager,
    is_prev_cache_valid, is_curr_cache_valid, pair_fingerprint, action_fingerprint,
)


class TestCacheValidation:

    def test_prev_cache_none_returns_false(self):
        t, a = make_pair()
        valid, idx = is_prev_cache_valid([(t, a)], None)
        assert valid is False
        assert idx == 0

    def test_prev_cache_empty_pairs_returns_false(self):
        cache = PreviousSummaryCache("summary", 1, "fp")
        valid, idx = is_prev_cache_valid([], cache)
        assert valid is False

    def test_prev_cache_covered_exceeds_pairs_returns_false(self):
        t, a = make_pair("task", "action")
        fp = pair_fingerprint("task", "action")
        cache = PreviousSummaryCache("summary", 5, fp)
        valid, _ = is_prev_cache_valid([(t, a)], cache)
        assert valid is False

    def test_prev_cache_fingerprint_mismatch_returns_false(self):
        t, a = make_pair("task A", "action A")
        cache = PreviousSummaryCache("summary", 1, "wrong_fingerprint_xyz")
        valid, _ = is_prev_cache_valid([(t, a)], cache)
        assert valid is False

    def test_prev_cache_valid_hit(self):
        t, a = make_pair("task", "action")
        fp = pair_fingerprint("task", "action")
        cache = PreviousSummaryCache("summary text", 1, fp)
        valid, covered_idx = is_prev_cache_valid([(t, a)], cache)
        assert valid is True
        assert covered_idx == 1

    def test_prev_cache_valid_partial_coverage(self):
        """Cache covers first 2 pairs, total 3 pairs -> valid, return covered=2."""
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        t1, a1 = pairs[1]
        fp = pair_fingerprint(t1.task, a1.action_output)
        cache = PreviousSummaryCache("summary", 2, fp)
        valid, covered_idx = is_prev_cache_valid(pairs, cache)
        assert valid is True
        assert covered_idx == 2

    def test_curr_cache_none_returns_false(self):
        a = ActionStep(step_number=1, model_output="x", action_output="y")
        valid, idx = is_curr_cache_valid([a], None)
        assert valid is False

    def test_curr_cache_fingerprint_mismatch_returns_false(self):
        a = ActionStep(step_number=1, model_output="x", action_output="y")
        cache = CurrentSummaryCache("summary", 1, "wrong_fp")
        valid, _ = is_curr_cache_valid([a], cache)
        assert valid is False

    def test_curr_cache_end_steps_exceeds_list_returns_false(self):
        a = ActionStep(step_number=1, model_output="x", action_output="y")
        fp = action_fingerprint(a)
        cache = CurrentSummaryCache("summary", 5, fp)
        valid, _ = is_curr_cache_valid([a], cache)
        assert valid is False

    def test_curr_cache_valid_hit(self):
        a = ActionStep(step_number=1, model_output="output", action_output="result")
        fp = action_fingerprint(a)
        cache = CurrentSummaryCache("summary text", 1, fp)
        valid, end_steps = is_curr_cache_valid([a], cache)
        assert valid is True
        assert end_steps == 1
