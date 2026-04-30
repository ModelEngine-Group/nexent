from factories import make_cm, make_pair
from loader import PreviousSummaryCache, CurrentSummaryCache, ActionStep, ContextManager


class TestCacheValidation:

    def test_prev_cache_none_returns_false(self):
        cm = make_cm()
        t, a = make_pair()
        valid, idx = cm._is_prev_cache_valid([(t, a)])
        assert valid is False
        assert idx == 0

    def test_prev_cache_empty_pairs_returns_false(self):
        cm = make_cm()
        cm._previous_summary_cache = PreviousSummaryCache("summary", 1, "fp")
        valid, idx = cm._is_prev_cache_valid([])
        assert valid is False

    def test_prev_cache_covered_exceeds_pairs_returns_false(self):
        cm = make_cm()
        t, a = make_pair("task", "action")
        fp = cm._pair_fingerprint("task", "action")
        cm._previous_summary_cache = PreviousSummaryCache("summary", 5, fp)
        valid, _ = cm._is_prev_cache_valid([(t, a)])
        assert valid is False

    def test_prev_cache_fingerprint_mismatch_returns_false(self):
        cm = make_cm()
        t, a = make_pair("task A", "action A")
        cm._previous_summary_cache = PreviousSummaryCache(
            "summary", 1, "wrong_fingerprint_xyz"
        )
        valid, _ = cm._is_prev_cache_valid([(t, a)])
        assert valid is False

    def test_prev_cache_valid_hit(self):
        cm = make_cm()
        t, a = make_pair("task", "action")
        fp = cm._pair_fingerprint("task", "action")
        cm._previous_summary_cache = PreviousSummaryCache("summary text", 1, fp)
        valid, covered_idx = cm._is_prev_cache_valid([(t, a)])
        assert valid is True
        assert covered_idx == 1

    def test_prev_cache_valid_partial_coverage(self):
        """Cache covers first 2 pairs, total 3 pairs -> valid, return covered=2."""
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        t1, a1 = pairs[1]
        fp = cm._pair_fingerprint(t1.task, a1.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("summary", 2, fp)
        valid, covered_idx = cm._is_prev_cache_valid(pairs)
        assert valid is True
        assert covered_idx == 2

    def test_curr_cache_none_returns_false(self):
        cm = make_cm()
        a = ActionStep(step_number=1, model_output="x", action_output="y")
        valid, idx = cm._is_curr_cache_valid([a])
        assert valid is False

    def test_curr_cache_fingerprint_mismatch_returns_false(self):
        cm = make_cm()
        a = ActionStep(step_number=1, model_output="x", action_output="y")
        cm._current_summary_cache = CurrentSummaryCache("summary", 1, "wrong_fp")
        valid, _ = cm._is_curr_cache_valid([a])
        assert valid is False

    def test_curr_cache_end_steps_exceeds_list_returns_false(self):
        cm = make_cm()
        a = ActionStep(step_number=1, model_output="x", action_output="y")
        fp = ContextManager._action_fingerprint(a)
        cm._current_summary_cache = CurrentSummaryCache("summary", 5, fp)
        valid, _ = cm._is_curr_cache_valid([a])
        assert valid is False

    def test_curr_cache_valid_hit(self):
        cm = make_cm()
        a = ActionStep(step_number=1, model_output="output", action_output="result")
        fp = ContextManager._action_fingerprint(a)
        cm._current_summary_cache = CurrentSummaryCache("summary text", 1, fp)
        valid, end_steps = cm._is_curr_cache_valid([a])
        assert valid is True
        assert end_steps == 1