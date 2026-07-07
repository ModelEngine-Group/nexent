"""
unit/test_step_renderer.py
Tests for StepRenderer methods not covered by other test files:
  - truncate_text_to_tokens
  - pairs_to_steps
  - render_steps_with_truncation
  - _truncate_text / _reduce_budgets / _actions_to_text_with_limit
  - compress_history_offline (standalone function)
"""

import json

import pytest
from unittest.mock import MagicMock

from factories import make_cm, make_pair, make_model
from loader import (
    ActionStep,
    ContextManagerConfig,
    compress_history_offline as cho,
)


# truncate_text_to_tokens

class TestTruncateTextToTokens:

    @pytest.mark.parametrize("max_tokens", [0, -1])
    def test_zero_or_negative_returns_empty(self, max_tokens):
        cm = make_cm()
        assert cm._renderer.truncate_text_to_tokens("hello world", max_tokens) == ""

    def test_within_budget_returns_unchanged(self):
        cm = make_cm()
        text = "short text"
        assert cm._renderer.truncate_text_to_tokens(text, 99999) == text

    def test_over_budget_truncates_keeping_newest(self):
        cm = make_cm()
        paragraphs = [f"paragraph {i}: " + "X" * 100 for i in range(20)]
        text = "\n\n".join(paragraphs)
        result = cm._renderer.truncate_text_to_tokens(text, max_tokens=10)
        assert len(result) < len(text)
        assert "Earlier content truncated" in result

    def test_very_small_budget_uses_char_fallback(self):
        cm = make_cm()
        text = "A" * 5000
        result = cm._renderer.truncate_text_to_tokens(text, max_tokens=1)
        assert len(result) < 5000
        assert "Earlier content truncated" in result


# pairs_to_steps

class TestPairsToSteps:

    def test_converts_pairs_to_flat_list(self):
        cm = make_cm()
        t1, a1 = make_pair("task1", "action1", 1)
        t2, a2 = make_pair("task2", "action2", 2)
        assert cm._renderer.pairs_to_steps([(t1, a1), (t2, a2)]) == [t1, a1, t2, a2]

    def test_empty_and_single(self):
        cm = make_cm()
        assert cm._renderer.pairs_to_steps([]) == []
        t, a = make_pair("only", "only", 1)
        assert cm._renderer.pairs_to_steps([(t, a)]) == [t, a]


# render_steps_with_truncation

class TestRenderStepsWithTruncation:

    def test_within_budget_returns_full_text(self):
        cm = make_cm()
        t, a = make_pair("short task", "short action", 1)
        text = cm._renderer.render_steps_with_truncation(
            [(t, a)], fmt="pairs", max_tokens=99999
        )
        assert "short task" in text

    def test_over_budget_truncates(self):
        cm = make_cm()
        actions = [
            ActionStep(step_number=i, model_output="X" * 500, action_output="Y" * 500)
            for i in range(10)
        ]
        text = cm._renderer.render_steps_with_truncation(
            actions, fmt="action", max_tokens=1,
            min_budget_chars=20, task_budget_chars=30, action_budget_chars=40,
        )
        assert len(text) > 0

    def test_default_max_tokens_from_config(self):
        cm = make_cm()
        cm._renderer.config.max_summary_input_tokens = 1
        actions = [
            ActionStep(step_number=i, model_output="X" * 200, action_output="Y" * 200)
            for i in range(5)
        ]
        text = cm._renderer.render_steps_with_truncation(actions, fmt="action")
        assert len(text) < 200 * 5

    def test_empty_steps_returns_empty(self):
        cm = make_cm()
        assert cm._renderer.render_steps_with_truncation([], fmt="action") == ""

    def test_pairs_fmt_uses_user_assistant_prefix(self):
        cm = make_cm()
        t, a = make_pair("user question", "assistant answer", 1)
        text = cm._renderer.render_steps_with_truncation(
            [(t, a)], fmt="pairs", max_tokens=99999
        )
        assert "user:" in text
        assert "assistant:" in text


# _truncate_text / _reduce_budgets / _actions_to_text_with_limit

class TestTruncateText:

    def test_within_limit_returns_unchanged(self):
        cm = make_cm()
        assert cm._renderer._truncate_text("hello", max_len=100) == "hello"

    def test_over_limit_truncates_with_mark(self):
        cm = make_cm()
        result = cm._renderer._truncate_text("a" * 50, max_len=20)
        assert "...[Truncated]" in result
        assert len(result) == 20


class TestReduceBudgets:

    def test_reduces_action_budget_first(self):
        cm = make_cm()
        t, a = cm._renderer._reduce_budgets(800, 400, 80)
        assert a == 320
        assert t == 800

    def test_reduces_task_budget_when_action_at_min(self):
        cm = make_cm()
        t, a = cm._renderer._reduce_budgets(800, 80, 80)
        assert t == 640
        assert a == 80

    def test_both_at_min_no_reduction(self):
        cm = make_cm()
        t, a = cm._renderer._reduce_budgets(80, 80, 80)
        assert t == 80
        assert a == 80


class TestActionsToTextWithLimit:

    def test_returns_content_with_fallback(self):
        cm = make_cm()
        actions = [
            ActionStep(step_number=i, model_output="X" * 300, action_output="Y" * 300)
            for i in range(5)
        ]
        result = cm._renderer._actions_to_text_with_limit(actions, prefill_tokens=0)
        assert len(result) > 0


# compress_history_offline (standalone function)

class TestCompressHistoryOffline:

    def test_empty_pairs_and_no_prev_summary(self):
        result = cho([], MagicMock())
        assert result["summary"] is None
        assert result["is_incremental"] is False
        assert result["is_fallback"] is False

    def test_basic_compression_success(self):
        model = make_model('{"task_overview": "test overview"}')
        pairs = [("user question", "assistant answer")]
        result = cho(pairs, model)
        assert result["summary"] is not None
        parsed = json.loads(result["summary"])
        assert parsed["task_overview"] == "test overview"
        assert not result["is_fallback"]
        assert "user question" in result["input_text"]

    def test_incremental_with_previous_summary(self):
        model = make_model('{"task_overview": "updated summary"}')
        pairs = [("new question", "new answer")]
        result = cho(pairs, model, previous_summary="old summary text")
        assert result["summary"] is not None
        assert result["is_incremental"] is True

    def test_prompt_varies_by_mode(self):
        model = MagicMock()
        response = MagicMock()
        response.content = '{"task_overview": "x"}'
        model.return_value = response
        cho([("q", "a")], model, previous_summary=None)
        call_args = model.call_args[0][0]
        user_text = next(m for m in call_args if m.role == "user").content[0]["text"]
        assert "Create a structured checkpoint summary" in user_text

    def test_llm_exception_falls_back(self):
        model = MagicMock()
        model.side_effect = Exception("unrecoverable error")
        result = cho([("task", "answer")], model)
        assert result["is_fallback"] is True
        assert "[CONTEXT COMPACTION" in result["summary"]

    def test_multiple_pairs_rendered(self):
        model = make_model('{"task_overview": "summary"}')
        pairs = [("q1", "a1"), ("q2", "a2"), ("q3", "a3")]
        result = cho(pairs, model)
        assert "q1" in result["input_text"]
        assert "q3" in result["input_text"]
