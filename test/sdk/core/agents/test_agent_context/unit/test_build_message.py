from factories import make_cm, make_pair
from loader import AgentMemory, SummaryTaskStep, SystemPromptStep

class TestBuildMessages:

    def test_build_messages_no_summary(self):
        cm = make_cm()
        t, a = make_pair("task", "action")
        memory = AgentMemory(steps=[])
        msgs = cm._build_messages(memory, None, [], [t, a])
        # 应包含 task 和 action 的消息
        all_text = " ".join(
            b.get("text", "")
            for m in msgs for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        )
        assert "task" in all_text
        assert "action" in all_text

    def test_build_messages_with_prev_summary_comes_first(self):
        cm = make_cm()
        summary = SummaryTaskStep(task="历史摘要内容")
        t, a = make_pair("当前任务", "当前结果", 1)
        memory = AgentMemory(steps=[])
        msgs = cm._build_messages(memory, summary, [], [t, a])
        all_texts = [
            b.get("text", "")
            for m in msgs for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        ]
        # 摘要应在当前任务之前出现
        summary_idx = next(i for i, t in enumerate(all_texts) if "历史摘要内容" in t)
        curr_idx = next(i for i, t in enumerate(all_texts) if "当前任务" in t)
        assert summary_idx < curr_idx

    def test_build_messages_with_system_prompt(self):
        cm = make_cm()
        memory = AgentMemory(steps=[], system_prompt=SystemPromptStep(system_prompt="系统提示"))
        msgs = cm._build_messages(memory, None, [], [])
        all_text = " ".join(
            b.get("text", "")
            for m in msgs for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        )
        assert "系统提示" in all_text