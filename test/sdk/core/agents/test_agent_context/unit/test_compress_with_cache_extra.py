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
    pair_fingerprint,
    action_fingerprint,
    SummaryResult,
    PreviousCompressResult,
    CurrentCompressResult,
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


def _compress_previous_with_cache(cm, pairs, model):
    """Helper: call prev compressor and apply cache, return summary_text."""
    result = cm._prev_compressor.compress(pairs, cm._previous_summary_cache, model)
    if result.new_cache is not None:
        cm._previous_summary_cache = result.new_cache
    return result.summary_text


def _compress_current_with_cache(cm, task, actions, model):
    """Helper: call curr compressor and apply cache, return summary_text."""
    result = cm._curr_compressor.compress(task, actions, cm._current_summary_cache, model)
    if result.new_cache is not None:
        cm._current_summary_cache = result.new_cache
    return result.summary_text


class TestCompressPreviousExtra:

    def test_p1_full_hit_fp_mismatch_goes_to_fresh(self):
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
        result = _compress_previous_with_cache(cm, pairs, model)

        assert result is not None
        model.assert_called_once()
        assert "old summary" not in _llm_text(model)
        assert cm._previous_summary_cache.covered_pairs == 2

    def test_p2_incremental_over_budget_falls_through_to_fresh(self):
        """Incremental input token count exceeds max_summary_input_tokens,
        should skip incremental and go to fresh, still call LLM once (fresh).
        """
        cm = make_cm()
        cm.config.max_summary_input_tokens = 0

        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("old summary", 2, fp)

        model = make_model('{"task_overview": "fresh summary"}')

        result = _compress_previous_with_cache(cm, pairs, model)
        assert result is not None
        model.assert_called_once()
        assert "old summary" not in _llm_text(model)
        assert "task2" in _llm_text(model)
        assert "fresh" in result

    def test_p3_incremental_llm_none_returns_empty_result(self):
        """When generate_summary returns SummaryResult(summary_text=None) in incremental path,
        v2 compressor returns PreviousCompressResult(summary_text=None) immediately (no fall-through to fresh).
        LLM is called exactly once.
        """
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("old summary", 2, fp)

        with patch.object(cm._llm, 'generate_summary', return_value=SummaryResult(summary_text=None, records=[])):
            result = _compress_previous_with_cache(cm, pairs, MagicMock())

        assert result is None

    def test_p4_fresh_llm_none_returns_none_and_preserves_old_cache(self):
        """When _summarize_pairs returns PreviousCompressResult(summary_text=None):
        - function returns None (no summary produced)
        - existing _previous_summary_cache not modified
        """
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(2)]
        cm._previous_summary_cache = PreviousSummaryCache("old summary", 99, "bad_fp")

        with patch.object(cm._prev_compressor, '_summarize_pairs', return_value=PreviousCompressResult(summary_text=None, new_cache=None)):
            result = _compress_previous_with_cache(cm, pairs, MagicMock())

        assert result is None
        assert cm._previous_summary_cache.summary_text == "old summary"

    def test_p4_fresh_llm_none_no_cache_remains_none(self):
        """Initial no cache, fresh _summarize_pairs returns None -> cache still None."""
        cm = make_cm()
        pairs = [make_pair("task", "action", 0)]
        assert cm._previous_summary_cache is None

        with patch.object(cm._prev_compressor, '_summarize_pairs', return_value=PreviousCompressResult(summary_text=None, new_cache=None)):
            result = _compress_previous_with_cache(cm, pairs, MagicMock())

        assert result is None
        assert cm._previous_summary_cache is None


class TestCompressCurrentExtra:

    def _make_actions(self, n):
        return [
            ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}")
            for i in range(n)
        ]

    def test_c1_full_hit_fp_mismatch_goes_to_fresh(self):
        """end_steps == len(actions) but anchor_fingerprint wrong.
        Incremental condition 0 < end_steps < len not met, go directly to fresh.
        """
        cm = make_cm()
        actions = self._make_actions(2)
        cm._current_summary_cache = CurrentSummaryCache(
            summary_text="old summary", end_steps=2, anchor_fingerprint="WRONG"
        )
        model = make_model('{"task_overview": "fresh summary"}')
        result = _compress_current_with_cache(cm, TaskStep(task="t"), actions, model)

        assert result is not None
        assert "fresh summary" in result
        assert "old summary" not in result
        model.assert_called_once()
        real_fp = action_fingerprint(actions[-1])
        assert cm._current_summary_cache.anchor_fingerprint == real_fp

    def test_c2_incremental_anchor_fp_mismatch_goes_to_fresh(self):
        """cache.end_steps < len(actions) (incremental condition met),
        but anchor action fingerprint mismatch with cache -> fall-through to fresh.
        """
        cm = make_cm()
        actions = self._make_actions(3)
        cm._current_summary_cache = CurrentSummaryCache(
            summary_text="old summary", end_steps=2, anchor_fingerprint="WRONG"
        )
        model = make_model('{"task_overview": "fresh summary"}')
        result = _compress_current_with_cache(cm, TaskStep(task="t"), actions, model)

        assert result is not None
        model.assert_called_once()
        assert "old summary" not in _llm_text(model)
        assert "fresh summary" in result

    def test_c4_incremental_llm_none_returns_empty_result(self):
        """When generate_summary returns SummaryResult(summary_text=None) in incremental path,
        v2 compressor returns CurrentCompressResult(summary_text=None) immediately (no fall-through to fresh).
        LLM is called exactly once.
        """
        cm = make_cm()
        actions = self._make_actions(3)
        fp = action_fingerprint(actions[1])
        cm._current_summary_cache = CurrentSummaryCache("old summary", 2, fp)

        with patch.object(cm._llm, 'generate_summary', return_value=SummaryResult(summary_text=None, records=[])):
            result = _compress_current_with_cache(cm, TaskStep(task="t"), actions, MagicMock())

        assert result is None

    def test_c5_fresh_actions_trimmed_cache_uses_original_len(self):
        """trim_actions_to_budget trimmed some actions,
        but end_steps should still record original len(actions_to_compress),
        ensuring next call cache covers same range.
        """
        cm = make_cm()
        actions = self._make_actions(4)

        with patch.object(cm._renderer, 'actions_to_text', return_value="short text"):
            model = make_model('{"task_overview": "trimmed summary"}')
            result = _compress_current_with_cache(cm, TaskStep(task="t"), actions, model)

        assert result is not None
        assert cm._current_summary_cache.end_steps == 4
        real_fp = action_fingerprint(actions[-1])
        assert cm._current_summary_cache.anchor_fingerprint == real_fp

    def test_c5_fresh_partial_trim_still_calls_llm_once(self):
        """After trim still only call LLM once (no retry)."""
        cm = make_cm()
        actions = self._make_actions(3)

        with patch.object(cm._renderer, 'actions_to_text', return_value="short text"):
            model = make_model('{"task_overview": "summary"}')
            _compress_current_with_cache(cm, TaskStep(task="t"), actions, model)

        model.assert_called_once()

    def test_c6_fresh_llm_none_writes_none_to_cache(self):
        """Current fresh path if LLM call fails, no cache.
        Only truncation performed.
        """
        cm = make_cm()
        actions = self._make_actions(2)

        with patch.object(cm._llm, 'generate_summary', return_value=SummaryResult(summary_text=None, records=[])):
            result = _compress_current_with_cache(cm, TaskStep(task="t"), actions, MagicMock())

        assert "[CONTEXT COMPACTION" in result
        assert cm._current_summary_cache is None

    def test_c6_vs_previous_asymmetry(self):
        """Regression test: clarify asymmetry between previous and current behavior when LLM=None.
        previous _summarize_pairs=None -> cache not written (preserve old value)
        current  generate_summary=None -> cache not written (L3 fallback produces summary, no cache)
        """
        cm = make_cm()
        pairs = [make_pair("task", "action", 0)]
        actions = [ActionStep(step_number=0, model_output="out", action_output="r")]

        old_prev_cache = PreviousSummaryCache("old prev", 99, "bad")
        cm._previous_summary_cache = old_prev_cache

        with patch.object(cm._prev_compressor, '_summarize_pairs', return_value=PreviousCompressResult(summary_text=None, new_cache=None)):
            _compress_previous_with_cache(cm, pairs, MagicMock())
        assert cm._previous_summary_cache is old_prev_cache

        with patch.object(cm._llm, 'generate_summary', return_value=SummaryResult(summary_text=None, records=[])):
            _compress_current_with_cache(cm, TaskStep(task="t"), actions, MagicMock())
        assert cm._current_summary_cache is None
