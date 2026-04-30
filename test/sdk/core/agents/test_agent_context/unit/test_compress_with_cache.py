from factories import make_cm, make_pair, make_model
from loader import ActionStep, PreviousSummaryCache, ContextManager, CurrentSummaryCache, TaskStep


class TestCompressPreviousWithCache:

    def _make_pairs_with_cache(self, n=2):
        """Generate n pairs and preset full cache hit."""
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(n)]
        last_t, last_a = pairs[-1]
        fp = cm._pair_fingerprint(last_t.task, last_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache(
            summary_text="existing summary", covered_pairs=n, anchor_fingerprint=fp
        )
        return cm, pairs

    def test_previous_full_cache_hit_no_llm_call(self):
        cm, pairs = self._make_pairs_with_cache(n=2)
        model = make_model()
        result = cm._compress_previous_with_cache(pairs, model)
        assert result == "existing summary"
        model.assert_not_called()

    def test_previous_incremental_calls_llm_with_old_summary(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = cm._pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache(
            summary_text="old summary", covered_pairs=2, anchor_fingerprint=fp
        )
        model = make_model('{"task_overview": "incremental summary"}')
        result = cm._compress_previous_with_cache(pairs, model)
        assert result is not None
        model.assert_called_once()
        call_args = model.call_args[0][0]
        full_text = " ".join(
            b.get("text", "") for m in call_args for b in (m.content if isinstance(m.content, list) else [])
        )
        assert "old summary" in full_text

    def test_previous_fresh_compress_writes_cache(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(2)]
        model = make_model('{"task_overview": "full summary"}')
        result = cm._compress_previous_with_cache(pairs, model)
        assert result is not None
        assert cm._previous_summary_cache is not None
        assert cm._previous_summary_cache.covered_pairs == 2

    def test_previous_incremental_updates_cache_to_full_coverage(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = cm._pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("old summary", 2, fp)
        model = make_model('{"task_overview": "new summary"}')
        cm._compress_previous_with_cache(pairs, model)
        assert cm._previous_summary_cache.covered_pairs == 3
        assert "new summary" in cm._previous_summary_cache.summary_text

    def test_previous_fingerprint_mismatch_falls_through_to_fresh(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        cm._previous_summary_cache = PreviousSummaryCache("old summary", 2, "wrong_fp")
        model = make_model('{"task_overview": "fresh summary"}')
        result = cm._compress_previous_with_cache(pairs, model)
        assert result is not None
        call_args = model.call_args[0][0]
        full_text = " ".join(
            b.get("text", "") for m in call_args for b in (m.content if isinstance(m.content, list) else [])
        )
        assert "old summary" not in full_text
        assert cm._previous_summary_cache.covered_pairs == 3

    def test_previous_empty_pairs_returns_none(self):
        cm = make_cm()
        model = make_model()
        assert cm._compress_previous_with_cache([], model) is None
        model.assert_not_called()


class TestCompressCurrentWithCache:

    def _make_actions_with_cache(self, n=2):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}") for i in range(n)]
        fp = ContextManager._action_fingerprint(actions[-1])
        cm._current_summary_cache = CurrentSummaryCache("existing step summary", n, fp)
        return cm, actions

    def test_current_full_cache_hit_no_llm_call(self):
        cm, actions = self._make_actions_with_cache(n=2)
        model = make_model()
        task = TaskStep(task="current task")
        result = cm._compress_current_with_cache(task, actions, model)
        assert result == "existing step summary"
        model.assert_not_called()

    def test_current_incremental_calls_llm(self):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}") for i in range(3)]
        fp = ContextManager._action_fingerprint(actions[1])
        cm._current_summary_cache = CurrentSummaryCache("old step summary", 2, fp)
        model = make_model('{"task_overview": "incremental step summary"}')
        task = TaskStep(task="task")
        result = cm._compress_current_with_cache(task, actions, model)
        assert "incremental step" in result
        assert "old step" not in result
        assert cm._current_summary_cache.end_steps == 3
        model.assert_called_once()

    def test_current_fresh_writes_cache(self):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}") for i in range(2)]
        model = make_model('{"task_overview": "fresh step summary"}')
        task = TaskStep(task="task")
        cm._compress_current_with_cache(task, actions, model)
        assert cm._current_summary_cache is not None
        assert cm._current_summary_cache.end_steps == 2

    def test_current_no_task_step(self):
        cm = make_cm()
        actions = [ActionStep(step_number=1, model_output="output", action_output="result")]
        model = make_model('{"task_overview": "summary"}')
        result = cm._compress_current_with_cache(None, actions, model)
        assert result is not None

    def test_current_empty_actions_returns_none(self):
        cm = make_cm()
        model = make_model()
        assert cm._compress_current_with_cache(TaskStep(task="t"), [], model) is None
        model.assert_not_called()

    def test_current_incremental_updates_anchor_fingerprint(self):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"o{i}", action_output=f"r{i}") for i in range(3)]
        fp_old = ContextManager._action_fingerprint(actions[1])
        cm._current_summary_cache = CurrentSummaryCache("old summary", 2, fp_old)
        model = make_model('{"task_overview": "new summary"}')
        cm._compress_current_with_cache(TaskStep(task="t"), actions, model)
        fp_new = ContextManager._action_fingerprint(actions[2])
        assert cm._current_summary_cache.anchor_fingerprint == fp_new