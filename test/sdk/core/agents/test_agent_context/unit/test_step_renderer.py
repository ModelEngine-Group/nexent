"""
unit/test_step_renderer.py
Tests for StepRenderer methods not covered by other test files:
  - render_action_step / _render_segment
  - truncate_text_to_tokens
  - pairs_to_steps
  - render_steps_with_truncation
  - compress_history_offline (standalone function)
"""

import json

import pytest
from unittest.mock import MagicMock, patch

from factories import make_cm, make_pair, make_model
from loader import (
    ActionStep,
    ContextManagerConfig,
    OffloadStore,
    StepRenderer,
    compress_history_offline as cho,
    estimate_tokens_text,
)
from stubs import _SystemPromptStep as SystemPromptStep


# ──────────────────────────────────────────────────────────────
# render_action_step
# ──────────────────────────────────────────────────────────────

class TestRenderActionStep:

    def test_renders_model_output(self):
        cm = make_cm()
        action = ActionStep(step_number=1, model_output="hello world")
        text = cm._renderer.render_action_step(action)
        assert "hello world" in text

    def test_renders_observation(self):
        """Stub ActionStep puts model_output in to_messages();
        'Observation:' prefix triggers observation-specific rendering."""
        cm = make_cm()
        action = ActionStep(step_number=1,
                            model_output="Observation:\nobserved result text here")
        text = cm._renderer.render_action_step(action)
        assert "observed result text here" in text

    def test_tool_call_kept_verbatim(self):
        cm = make_cm()
        action = ActionStep(step_number=1, model_output="Calling tools: tool1, tool2",
                            tool_calls=[{"name": "tool1"}])
        text = cm._renderer.render_action_step(action)
        assert "Calling tools:" in text

    def test_no_offload_when_limit_zero(self):
        """per_step_render_limit=0 disables offload — full text kept."""
        cm = make_cm()
        cm._renderer._config.per_step_render_limit = 0
        action = ActionStep(step_number=1, model_output="x" * 5000)
        text = cm._renderer.render_action_step(action)
        assert "x" * 5000 in text
        assert "OBS_OFFLOAD" not in text
        assert "CONTENT_OFFLOAD" not in text

    def test_no_offload_when_offload_store_none(self):
        cm = make_cm()
        cm._renderer._config.per_step_render_limit = 100
        action = ActionStep(step_number=1, model_output="x" * 200)
        text = cm._renderer.render_action_step(action, offload_store=None)
        assert "x" * 200 in text
        assert "CONTENT_OFFLOAD" not in text

    def test_offload_triggered_when_over_limit(self):
        cm = make_cm()
        cm._renderer._config.per_step_render_limit = 20
        store = OffloadStore()
        action = ActionStep(step_number=1, model_output="abcdefghijklmnopqrstuvwxyz" * 3)
        text = cm._renderer.render_action_step(action, offload_store=store)
        assert "CONTENT_OFFLOAD" in text
        assert "handle=" in text
        assert len(store) >= 1

    def test_offload_observation_uses_obs_offload_marker(self):
        """Model output starting with 'Observation:' gets OBS_OFFLOAD marker."""
        cm = make_cm()
        cm._renderer._config.per_step_render_limit = 10
        store = OffloadStore()
        action = ActionStep(step_number=1,
                            model_output="Observation:\n" + "x" * 200)
        text = cm._renderer.render_action_step(action, offload_store=store)
        assert "OBS_OFFLOAD" in text

    def test_raw_observation_used_for_offload(self):
        """When _raw_observation exists, offload archives the raw content."""
        cm = make_cm()
        cm._renderer._config.per_step_render_limit = 10
        store = OffloadStore()
        action = ActionStep(step_number=1,
                            model_output="Observation: short")
        action._raw_observation = "Observation: " + "R" * 500
        text = cm._renderer.render_action_step(action, offload_store=store)
        assert "OBS_OFFLOAD" in text
        handles = [h for h, _ in store.list_active()]
        assert len(handles) == 1
        reloaded = store.reload(handles[0])
        assert "R" * 500 in reloaded

    def test_reloaded_content_skips_re_offload(self):
        """Content containing 'offload_handle' near the start is not re-offloaded."""
        cm = make_cm()
        cm._renderer._config.per_step_render_limit = 10
        store = OffloadStore()
        # "offload_handle" inside first 300 chars of model_output triggers skip
        action = ActionStep(step_number=1,
                            model_output='{"offload_handle": "abc123", "data": "' + "y" * 500 + '"}')
        text = cm._renderer.render_action_step(action, offload_store=store)
        assert "OBS_OFFLOAD" not in text
        assert len(store) == 0

    def test_content_too_large_for_offload_store_falls_back_to_truncation(self):
        cm = make_cm()
        cm._renderer._config.per_step_render_limit = 10
        store = OffloadStore(max_entry_chars=20)
        action = ActionStep(step_number=1, model_output="x" * 500)
        text = cm._renderer.render_action_step(action, offload_store=store)
        assert "CONTENT_TOO_LARGE_TO_OFFLOAD" in text


# ──────────────────────────────────────────────────────────────
# truncate_text_to_tokens
# ──────────────────────────────────────────────────────────────

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

    def test_empty_string_returns_empty(self):
        cm = make_cm()
        assert cm._renderer.truncate_text_to_tokens("", 100) == ""

    def test_very_small_budget_uses_char_fallback(self):
        cm = make_cm()
        text = "A" * 5000
        result = cm._renderer.truncate_text_to_tokens(text, max_tokens=1)
        assert len(result) < 5000
        assert "Earlier content truncated" in result


# ──────────────────────────────────────────────────────────────
# pairs_to_steps
# ──────────────────────────────────────────────────────────────

class TestPairsToSteps:

    def test_converts_pairs_to_flat_list(self):
        cm = make_cm()
        t1, a1 = make_pair("task1", "action1", 1)
        t2, a2 = make_pair("task2", "action2", 2)
        assert cm._renderer.pairs_to_steps([(t1, a1), (t2, a2)]) == [t1, a1, t2, a2]

    def test_empty_and_single_pair_edge_cases(self):
        cm = make_cm()
        assert cm._renderer.pairs_to_steps([]) == []
        t, a = make_pair("only", "only", 1)
        assert cm._renderer.pairs_to_steps([(t, a)]) == [t, a]


# ──────────────────────────────────────────────────────────────
# render_steps_with_truncation
# ──────────────────────────────────────────────────────────────

class TestRenderStepsWithTruncation:

    def test_within_budget_returns_full_text(self):
        cm = make_cm()
        t, a = make_pair("short task", "short action", 1)
        pairs = [(t, a)]
        text = cm._renderer.render_steps_with_truncation(
            pairs, fmt="pairs", max_tokens=99999
        )
        assert "short task" in text
        assert "short action" in text

    def test_action_fmt_within_budget(self):
        cm = make_cm()
        actions = [ActionStep(step_number=1, model_output="hello")]
        text = cm._renderer.render_steps_with_truncation(
            actions, fmt="action", max_tokens=99999
        )
        assert "hello" in text

    def test_over_budget_truncates_with_fallback(self):
        cm = make_cm()
        actions = [
            ActionStep(step_number=i, model_output="X" * 500, action_output="Y" * 500)
            for i in range(10)
        ]
        text = cm._renderer.render_steps_with_truncation(
            actions, fmt="action", max_tokens=1,
            min_budget_chars=20, task_budget_chars=30, action_budget_chars=40,
        )
        assert len(text) < 500 * 10
        assert len(text) > 0

    def test_default_max_tokens_from_config(self):
        cm = make_cm()
        cm._renderer._config.max_summary_input_tokens = 1
        actions = [
            ActionStep(step_number=i, model_output="X" * 200, action_output="Y" * 200)
            for i in range(5)
        ]
        text = cm._renderer.render_steps_with_truncation(actions, fmt="action")
        assert len(text) < 200 * 5

    def test_empty_steps_returns_empty(self):
        cm = make_cm()
        text = cm._renderer.render_steps_with_truncation([], fmt="action")
        assert text == ""

    def test_pairs_fmt_uses_user_assistant_prefix(self):
        cm = make_cm()
        t, a = make_pair("user question", "assistant answer", 1)
        text = cm._renderer.render_steps_with_truncation(
            [(t, a)], fmt="pairs", max_tokens=99999
        )
        assert "user:" in text
        assert "assistant:" in text


# ──────────────────────────────────────────────────────────────
# _truncate_text and _reduce_budgets (private, critical logic)
# ──────────────────────────────────────────────────────────────

class TestTruncateText:

    def test_within_or_at_limit_returns_unchanged(self):
        cm = make_cm()
        assert cm._renderer._truncate_text("hello", max_len=100) == "hello"
        assert cm._renderer._truncate_text("abcde", max_len=5) == "abcde"

    def test_over_limit_truncates_with_mark(self):
        cm = make_cm()
        result = cm._renderer._truncate_text("a" * 50, max_len=20)
        assert "...[Truncated]" in result and len(result) == 20


class TestReduceBudgets:

    def test_reduces_action_budget_first(self):
        cm = make_cm()
        t, a = cm._renderer._reduce_budgets(800, 400, 80)
        assert a == 320  # 400 * 0.8
        assert t == 800

    def test_reduces_task_budget_when_action_at_min(self):
        cm = make_cm()
        t, a = cm._renderer._reduce_budgets(800, 80, 80)
        assert t == 640  # 800 * 0.8
        assert a == 80

    def test_both_at_min_no_reduction(self):
        cm = make_cm()
        t, a = cm._renderer._reduce_budgets(80, 80, 80)
        assert t == 80
        assert a == 80

    def test_action_above_min_clamped_to_min(self):
        cm = make_cm()
        t, a = cm._renderer._reduce_budgets(800, 100, 80)
        assert a == 80  # max(min, 100*0.8) = max(80, 80)
        assert t == 800


# ──────────────────────────────────────────────────────────────
# compress_history_offline (standalone function)
# ──────────────────────────────────────────────────────────────

class TestCompressHistoryOffline:

    def test_empty_pairs_and_no_prev_summary_returns_none(self):
        result = cho([], MagicMock())
        assert result["summary"] is None
        assert result["is_incremental"] is False
        assert result["is_fallback"] is False

    def test_basic_compression_success(self):
        model = make_model('{"task_overview": "test overview"}')
        pairs = [("user question", "assistant answer")]
        result = cho(pairs, model)
        # format_summary_output reformats JSON — check content, not exact string
        assert result["summary"] is not None
        parsed = json.loads(result["summary"])
        assert parsed["task_overview"] == "test overview"
        assert result["is_incremental"] is False
        assert result["is_fallback"] is False
        assert "user question" in result["input_text"]
        assert result["input_chars"] > 0

    def test_incremental_with_previous_summary(self):
        model = make_model('{"task_overview": "updated summary"}')
        pairs = [("new question", "new answer")]
        result = cho(pairs, model, previous_summary="old summary text")
        assert result["summary"] is not None
        assert result["is_incremental"] is True
        assert "old summary text" in result["input_text"]
        assert "new question" in result["input_text"]

    @pytest.mark.parametrize("prev_summary, expected_phrase", [
        (None, "Create a structured checkpoint summary"),
        ("existing summary", "Update the summary"),
    ])
    def test_prompt_varies_by_mode(self, prev_summary, expected_phrase):
        model = MagicMock()
        response = MagicMock()
        response.content = '{"task_overview": "x"}'
        model.return_value = response

        cho([("q", "a")], model, previous_summary=prev_summary)
        call_args = model.call_args[0][0]
        roles = [m.role for m in call_args]
        assert "system" in roles and "user" in roles
        user_text = next(m for m in call_args if m.role == "user").content[0]["text"]
        assert expected_phrase in user_text

    def test_llm_exception_falls_back_to_truncation(self):
        """When LLM raises an unrecoverable exception, fallback summary is produced."""
        model = MagicMock()
        model.side_effect = Exception("unrecoverable error")

        result = cho([("task", "answer")], model)

        assert result["summary"] is not None
        assert result["is_fallback"] is True
        assert "[CONTEXT COMPACTION" in result["summary"]

    def test_multiple_pairs_rendered(self):
        model = make_model('{"task_overview": "summary"}')
        pairs = [
            ("question 1", "answer 1"),
            ("question 2", "answer 2"),
            ("question 3", "answer 3"),
        ]
        result = cho(pairs, model)
        assert "question 1" in result["input_text"]
        assert "question 2" in result["input_text"]
        assert "question 3" in result["input_text"]

    @pytest.mark.parametrize("config", [None, ContextManagerConfig(max_summary_input_tokens=100)])
    def test_config_default_and_custom(self, config):
        model = make_model('{"task_overview": "x"}')
        result = cho([("q", "a")], model, config=config)
        assert result["summary"] is not None
