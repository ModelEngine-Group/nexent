import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from unittest.mock import MagicMock, patch

from factories import make_cm, make_pair, make_model
from loader import (
    ActionStep,
    ContextManager,
    CurrentSummaryCache,
    PreviousSummaryCache,
    TaskStep,
)


def _llm_text(model) -> str:
    """Extract concatenated user prompt text from mock model's last call."""
    call_args = model.call_args[0][0]
    return " ".join(
        b.get("text", "")
        for m in call_args
        for b in (m.content if isinstance(m.content, list) else [])
        if isinstance(b, dict)
    )


def _all_texts(messages):
    return [
        b.get("text", "")
        for m in messages
        for b in (m.content if isinstance(m.content, list) else [])
        if isinstance(b, dict)
    ]


def _joined(messages):
    return " ".join(_all_texts(messages))


class TestCompressPreviousExtra:

    def test_P1_full_hit_fp_mismatch_goes_to_fresh(self):
        """covered_pairs == len(pairs) but fingerprint wrong.
        Should not take incremental path (covered < len condition not met),
        go directly to fresh full compression.
        """
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(2)]
        cm._previous_summary_cache = PreviousSummaryCache(
            summary_text="old summary", covered_pairs=2, anchor_fingerprint="WRONG"
        )
        model = make_model('{"task_overview": "fresh summary"}')
        result = cm._compress_previous_with_cache(pairs, model)

        assert result is not None
        model.assert_called_once()
        assert "old summary" not in _llm_text(model)
        assert cm._previous_summary_cache.covered_pairs == 2

    def test_P2_incremental_over_budget_falls_through_to_fresh(self):
        """Incremental input token count exceeds max_summary_input_tokens,
        should skip incremental and go to fresh, still call LLM once (fresh).
        """
        cm = make_cm()
        cm.config.max_summary_input_tokens = 0

        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = cm._pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("old summary", 2, fp)

        model = make_model('{"task_overview": "fresh summary"}')

        result = cm._compress_previous_with_cache(pairs, model)
        assert result is not None
        model.assert_called_once()
        assert "old summary" not in _llm_text(model)
        assert "task2" in _llm_text(model)
        assert "fresh" in result

    def test_P3_incremental_llm_none_falls_through_to_fresh(self):
        """When _generate_summary returns None in incremental path,
        code fall-through to fresh, should call LLM again.
        """
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = cm._pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("old summary", 2, fp)

        call_count = [0]
        def side_effect(text, model_, call_type="summary"):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return '{"task_overview": "fresh summary"}'

        with patch.object(cm, '_generate_summary', side_effect=side_effect):
            result = cm._compress_previous_with_cache(pairs, MagicMock())

        assert call_count[0] == 2
        assert result is not None

    def test_P4_fresh_llm_none_returns_none_and_preserves_old_cache(self):
        """When _summarize_pairs returns (None, False):
        - function returns None
        - existing _previous_summary_cache not modified
        """
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(2)]
        cm._previous_summary_cache = PreviousSummaryCache("old summary", 99, "bad_fp")

        with patch.object(cm, '_summarize_pairs', return_value=(None, False)):
            result = cm._compress_previous_with_cache(pairs, MagicMock())

        assert result is None
        assert cm._previous_summary_cache.summary_text == "old summary"

    def test_P4_fresh_llm_none_no_cache_remains_none(self):
        """Initial no cache, fresh LLM returns None -> cache still None."""
        cm = make_cm()
        pairs = [make_pair("task", "action", 0)]
        assert cm._previous_summary_cache is None

        with patch.object(cm, '_summarize_pairs', return_value=(None, False)):
            result = cm._compress_previous_with_cache(pairs, MagicMock())

        assert result is None
        assert cm._previous_summary_cache is None


class TestCompressCurrentExtra:

    def _make_actions(self, n):
        return [
            ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}")
            for i in range(n)
        ]

    def test_C1_full_hit_fp_mismatch_goes_to_fresh(self):
        """end_steps == len(actions) but anchor_fingerprint wrong.
        Incremental condition 0 < end_steps < len not met, go directly to fresh.
        """
        cm = make_cm()
        actions = self._make_actions(2)
        cm._current_summary_cache = CurrentSummaryCache(
            summary_text="old summary", end_steps=2, anchor_fingerprint="WRONG"
        )
        model = make_model('{"task_overview": "fresh summary"}')
        result = cm._compress_current_with_cache(TaskStep(task="t"), actions, model)

        assert result is not None
        assert "fresh summary" in result
        assert "old summary" not in result
        model.assert_called_once()
        real_fp = ContextManager._action_fingerprint(actions[-1])
        assert cm._current_summary_cache.anchor_fingerprint == real_fp

    def test_C2_incremental_anchor_fp_mismatch_goes_to_fresh(self):
        """cache.end_steps < len(actions) (incremental condition met),
        but anchor action fingerprint mismatch with cache -> fall-through to fresh.
        """
        cm = make_cm()
        actions = self._make_actions(3)
        cm._current_summary_cache = CurrentSummaryCache(
            summary_text="old summary", end_steps=2, anchor_fingerprint="WRONG"
        )
        model = make_model('{"task_overview": "fresh summary"}')
        result = cm._compress_current_with_cache(TaskStep(task="t"), actions, model)

        assert result is not None
        model.assert_called_once()
        assert "old summary" not in _llm_text(model)
        assert "fresh summary" in result

    def test_C4_incremental_llm_none_falls_through_to_fresh(self):
        cm = make_cm()
        actions = self._make_actions(3)
        fp = ContextManager._action_fingerprint(actions[1])
        cm._current_summary_cache = CurrentSummaryCache("old summary", 2, fp)

        call_count = [0]
        def side_effect(text, model_, call_type="summary"):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return '{"task_overview": "fresh summary"}'

        with patch.object(cm, '_generate_summary', side_effect=side_effect):
            result = cm._compress_current_with_cache(TaskStep(task="t"), actions, MagicMock())

        assert call_count[0] == 2
        assert result is not None
        assert cm._current_summary_cache.end_steps == len(actions)

    def test_C5_fresh_actions_trimmed_cache_uses_original_len(self):
        """_trim_actions_to_budget trimmed some actions,
        but end_steps should still record original len(actions_to_compress),
        ensuring next call cache covers same range.
        """
        cm = make_cm()
        actions = self._make_actions(4)

        with patch.object(cm, '_trim_actions_to_budget', return_value=[actions[-1]]):
            model = make_model('{"task_overview": "trimmed summary"}')
            result = cm._compress_current_with_cache(TaskStep(task="t"), actions, model)

        assert result is not None
        assert cm._current_summary_cache.end_steps == 4
        real_fp = ContextManager._action_fingerprint(actions[-1])
        assert cm._current_summary_cache.anchor_fingerprint == real_fp

    def test_C5_fresh_partial_trim_still_calls_llm_once(self):
        """After trim still only call LLM once (no retry)."""
        cm = make_cm()
        actions = self._make_actions(3)

        with patch.object(cm, '_trim_actions_to_budget', return_value=[actions[-1]]):
            model = make_model('{"task_overview": "summary"}')
            cm._compress_current_with_cache(TaskStep(task="t"), actions, model)

        model.assert_called_once()

    def test_C6_fresh_llm_none_writes_none_to_cache(self):
        """Current fresh path if LLM call fails, no cache.
        Only truncation performed.
        """
        cm = make_cm()
        actions = self._make_actions(2)

        with patch.object(cm, '_generate_summary', return_value=None):
            result = cm._compress_current_with_cache(TaskStep(task="t"), actions, MagicMock())

        assert "Truncated" in result
        assert cm._current_summary_cache is None

    def test_C6_vs_previous_asymmetry(self):
        """Regression test: clarify asymmetry between previous and current behavior when LLM=None.
        previous fresh=None -> cache not written (preserve old value)
        current  fresh=None -> cache not written
        """
        cm = make_cm()
        pairs = [make_pair("task", "action", 0)]
        actions = [ActionStep(step_number=0, model_output="out", action_output="r")]

        old_prev_cache = PreviousSummaryCache("old prev", 99, "bad")
        cm._previous_summary_cache = old_prev_cache

        with patch.object(cm, '_summarize_pairs', return_value=(None, False)):
            cm._compress_previous_with_cache(pairs, MagicMock())
        assert cm._previous_summary_cache is old_prev_cache

        with patch.object(cm, '_generate_summary', return_value=None):
            cm._compress_current_with_cache(TaskStep(task="t"), actions, MagicMock())
        assert cm._current_summary_cache is None