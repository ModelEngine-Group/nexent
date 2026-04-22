import json
import pytest

from factories import make_cm, make_memory_with_steps, make_original_messages, make_pair
from loader import ContextManager, SummaryTaskStep, TaskStep, ActionStep



class TestPureFunctions:

    # ---- _format_summary ----

    def test_format_summary_valid_json(self):
        cm = make_cm()
        raw = '{"task_overview": "做了某件事", "completed_work": "完成了"}'
        result = cm._format_summary(raw)
        parsed = json.loads(result)
        assert parsed["task_overview"] == "做了某件事"

    def test_format_summary_strips_markdown_fence(self):
        cm = make_cm()
        raw = '```json\n{"task_overview": "x"}\n```'
        result = cm._format_summary(raw)
        assert result is not None
        assert "```" not in result

    def test_format_summary_invalid_json_returns_plain_text(self):
        cm = make_cm()
        raw = "这不是 JSON 格式的文本内容"
        result = cm._format_summary(raw)
        assert result == raw

    def test_format_summary_empty_string_returns_none(self):
        cm = make_cm()
        assert cm._format_summary("") is None
        assert cm._format_summary("   ") is None

    # ---- _extract_pairs ----

    def test_extract_pairs_basic(self):
        cm = make_cm()
        t1, a1 = make_pair("任务1", "结果1", 1)
        t2, a2 = make_pair("任务2", "结果2", 2)
        steps = [t1, a1, t2, a2]
        pairs = cm._extract_pairs(steps)
        assert len(pairs) == 2
        assert pairs[0][0].task == "任务1"
        assert pairs[1][0].task == "任务2"

    def test_extract_pairs_skips_summary_task_step(self):
        cm = make_cm()
        summary = SummaryTaskStep(task="已有摘要")
        t1, a1 = make_pair("任务1", "结果1", 1)
        steps = [summary, t1, a1]
        pairs = cm._extract_pairs(steps)
        # SummaryTaskStep 应被跳过
        assert len(pairs) == 1
        assert pairs[0][0].task == "任务1"

    def test_extract_pairs_ignores_orphan_task(self):
        """一个 TaskStep 后没有 ActionStep，不应成对"""
        cm = make_cm()
        t1, a1 = make_pair("任务1", "结果1", 1)
        t_orphan = TaskStep(task="孤儿任务")
        steps = [t1, a1, t_orphan]
        pairs = cm._extract_pairs(steps)
        assert len(pairs) == 1

    def test_extract_pairs_empty_steps(self):
        cm = make_cm()
        assert cm._extract_pairs([]) == []

    # ---- fingerprint 稳定性 ----

    def test_pair_fingerprint_is_deterministic(self):
        cm = make_cm()
        fp1 = cm._pair_fingerprint("task content", "action content")
        fp2 = cm._pair_fingerprint("task content", "action content")
        assert fp1 == fp2

    def test_pair_fingerprint_differs_on_content_change(self):
        cm = make_cm()
        fp1 = cm._pair_fingerprint("task A", "action A")
        fp2 = cm._pair_fingerprint("task A", "action B")
        assert fp1 != fp2

    def test_action_fingerprint_is_deterministic(self):
        a = ActionStep(step_number=3, model_output="output", action_output="result")
        fp1 = ContextManager._action_fingerprint(a)
        fp2 = ContextManager._action_fingerprint(a)
        assert fp1 == fp2

    def test_action_fingerprint_differs_on_output_change(self):
        a1 = ActionStep(step_number=1, model_output="output A", action_output="result A")
        a2 = ActionStep(step_number=1, model_output="output A", action_output="result B")
        assert ContextManager._action_fingerprint(a1) != ContextManager._action_fingerprint(a2)

    # ---- _pairs_to_text ----

    def test_pairs_to_text_format(self):
        cm = make_cm()
        t, a = make_pair("用户问题", "模型回答", 1)
        text = cm._pairs_to_text([(t, a)])
        assert "用户问题" in text
        assert "模型回答" in text
        assert "user:" in text
        assert "assistant:" in text

    def test_pairs_to_text_multiple_pairs_joined_by_blank_line(self):
        cm = make_cm()
        pair1 = make_pair("问1", "答1", 1)
        pair2 = make_pair("问2", "答2", 2)
        text = cm._pairs_to_text([pair1, pair2])
        assert "\n\n" in text
