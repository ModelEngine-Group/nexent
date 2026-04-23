from factories import make_cm, make_pair
from loader import AgentMemory, SummaryTaskStep, SystemPromptStep


class TestBuildMessages:

    def test_build_messages_no_summary(self):
        cm = make_cm()
        t, a = make_pair("task", "action")
        memory = AgentMemory(steps=[])
        msgs = cm._build_messages(memory, None, [], [t, a])
        all_text = " ".join(
            b.get("text", "")
            for m in msgs for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        )
        assert "task" in all_text
        assert "action" in all_text

    def test_build_messages_with_prev_summary_comes_first(self):
        cm = make_cm()
        summary = SummaryTaskStep(task="history summary content")
        t, a = make_pair("current task", "current result", 1)
        memory = AgentMemory(steps=[])
        msgs = cm._build_messages(memory, summary, [], [t, a])
        all_texts = [
            b.get("text", "")
            for m in msgs for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        ]
        summary_idx = next(i for i, t in enumerate(all_texts) if "history summary content" in t)
        curr_idx = next(i for i, t in enumerate(all_texts) if "current task" in t)
        assert summary_idx < curr_idx

    def test_build_messages_with_system_prompt(self):
        cm = make_cm()
        memory = AgentMemory(steps=[], system_prompt=SystemPromptStep(system_prompt="system prompt"))
        msgs = cm._build_messages(memory, None, [], [])
        all_text = " ".join(
            b.get("text", "")
            for m in msgs for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        )
        assert "system prompt" in all_text