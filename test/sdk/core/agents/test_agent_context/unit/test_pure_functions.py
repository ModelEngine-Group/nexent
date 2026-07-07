import json
import pytest

from factories import make_cm, make_memory_with_steps, make_original_messages, make_pair
from loader import (
    ContextManager, SummaryTaskStep, TaskStep, ActionStep,
    extract_pairs, pair_fingerprint, action_fingerprint,
    format_summary_output,
    has_invoked_tools, message_role,
    trim_pairs_to_budget,
)
from sdk.nexent.core.agents.agent_context.budget import _is_context_length_error


class TestPureFunctions:

    def test_format_summary_valid_json(self):
        raw = '{"task_overview": "did something", "completed_work": "completed"}'
        result = format_summary_output(raw)
        parsed = json.loads(result)
        assert parsed["task_overview"] == "did something"

    def test_format_summary_strips_markdown_fence(self):
        raw = '```json\n{"task_overview": "x"}\n```'
        result = format_summary_output(raw)
        assert result is not None
        assert "```" not in result

    def test_format_summary_invalid_json_returns_plain_text(self):
        raw = "This is not JSON format text content"
        result = format_summary_output(raw)
        assert result == raw

    def test_format_summary_empty_string_returns_none(self):
        assert format_summary_output("") is None
        assert format_summary_output("   ") is None

    def test_extract_pairs_basic(self):
        t1, a1 = make_pair("task1", "result1", 1)
        t2, a2 = make_pair("task2", "result2", 2)
        steps = [t1, a1, t2, a2]
        pairs = extract_pairs(steps)
        assert len(pairs) == 2
        assert pairs[0][0].task == "task1"
        assert pairs[1][0].task == "task2"

    def test_extract_pairs_skips_summary_task_step(self):
        summary = SummaryTaskStep(task="existing summary")
        t1, a1 = make_pair("task1", "result1", 1)
        steps = [summary, t1, a1]
        pairs = extract_pairs(steps)
        assert len(pairs) == 1
        assert pairs[0][0].task == "task1"

    def test_extract_pairs_ignores_orphan_task(self):
        """A TaskStep without following ActionStep should not form a pair."""
        t1, a1 = make_pair("task1", "result1", 1)
        t_orphan = TaskStep(task="orphan task")
        steps = [t1, a1, t_orphan]
        pairs = extract_pairs(steps)
        assert len(pairs) == 1

    def test_extract_pairs_empty_steps(self):
        assert extract_pairs([]) == []

    def test_pair_fingerprint_is_deterministic(self):
        fp1 = pair_fingerprint("task content", "action content")
        fp2 = pair_fingerprint("task content", "action content")
        assert fp1 == fp2

    def test_pair_fingerprint_differs_on_content_change(self):
        fp1 = pair_fingerprint("task A", "action A")
        fp2 = pair_fingerprint("task A", "action B")
        assert fp1 != fp2

    def test_action_fingerprint_is_deterministic(self):
        a = ActionStep(step_number=3, model_output="output", action_output="result")
        fp1 = action_fingerprint(a)
        fp2 = action_fingerprint(a)
        assert fp1 == fp2

    def test_action_fingerprint_differs_on_output_change(self):
        a1 = ActionStep(step_number=1, model_output="output A", action_output="result A")
        a2 = ActionStep(step_number=1, model_output="output A", action_output="result B")
        assert action_fingerprint(a1) != action_fingerprint(a2)

    def test_pairs_to_text_format(self):
        cm = make_cm()
        t, a = make_pair("user question", "model response", 1)
        text = cm._renderer.pairs_to_text([(t, a)])
        assert "user question" in text
        assert "model response" in text
        assert "user:" in text
        assert "assistant:" in text

    def test_pairs_to_text_multiple_pairs_joined_by_blank_line(self):
        cm = make_cm()
        pair1 = make_pair("question1", "answer1", 1)
        pair2 = make_pair("question2", "answer2", 2)
        text = cm._renderer.pairs_to_text([pair1, pair2])
        assert "\n\n" in text

    # ── _is_context_length_error ──────────────────────────────

    def test_context_length_error_detected(self):
        assert _is_context_length_error(ValueError("context_length exceeded"))
        assert _is_context_length_error(ValueError("maximum context length reached"))
        assert _is_context_length_error(ValueError("prompt is too long"))
        assert _is_context_length_error(ValueError("token limit exceeded"))

    def test_context_length_error_not_detected(self):
        assert not _is_context_length_error(ValueError("connection timeout"))
        assert not _is_context_length_error(ValueError("out of memory"))

    # ── has_invoked_tools ─────────────────────────────────────

    def test_has_invoked_tools_with_none(self):
        assert not has_invoked_tools(None)

    # ── message_role ──────────────────────────────────────────

    def test_message_role_from_dict(self):
        assert message_role({"role": "user", "content": "hi"}) == "user"

    def test_message_role_from_object(self):
        from smolagents.models import ChatMessage
        msg = ChatMessage(role="assistant", content=[{"type": "text", "text": "ok"}])
        role = message_role(msg)
        assert role is not None

    # ── trim_pairs_to_budget keep_first ───────────────────────

    def test_trim_pairs_to_budget_keep_first(self):
        cm = make_cm()
        pairs = [make_pair(f"task {i}", f"ans {i}", i) for i in range(1, 6)]
        # 5 pairs, keep_first=True, budget small enough to trim
        result = trim_pairs_to_budget(
            pairs, max_tokens=100, render_fn=cm._renderer.pairs_to_text,
            keep_first=True,
        )
        assert len(result) >= 1
        assert result[0] == pairs[0]  # first pair always kept

    def test_trim_pairs_to_budget_drops_overflow(self):
        cm = make_cm()
        pairs = [make_pair(f"task {i}", f"ans {i}", i) for i in range(1, 4)]
        result = trim_pairs_to_budget(
            pairs, max_tokens=100, render_fn=cm._renderer.pairs_to_text,
            keep_first=False,
        )
        assert len(result) >= 1
