import json

from smolagents.memory import ActionStep, TaskStep
from smolagents.monitoring import Timing

from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig


class _SystemPrompt:
    def __init__(self, system_prompt):
        self.system_prompt = system_prompt
    def to_messages(self):
        return [{"role": "system", "content": [{"type": "text", "text": self.system_prompt}]}]


class _Memory:
    def __init__(self, steps=None):
        self.system_prompt = None
        self.steps = list(steps or ())


class _Response:
    content = json.dumps({
        "task_overview": "task", "completed_work": "work",
        "key_decisions": "decision", "pending_items": "pending",
        "context_to_preserve": "context",
    })
    token_usage = None


class _SummaryModel:
    def __init__(self):
        self.calls = []
    def __call__(self, messages, stop_sequences=None):
        self.calls.append(messages)
        return _Response()


def _summary_and_turns():
    return [
        ContextItemInput(id="summary:10", type="history_summary", content={
            "unit_id": 10, "summary": {"task_overview": "old"},
            "covered_through_message_id": 20,
        }),
        ContextItemInput(id="turn:21:22", type="conversation_turn", content={
            "user_message": "new question " * 20,
            "assistant_final_answer": "new answer " * 20,
            "attachments": [], "user_message_id": 21, "assistant_message_id": 22,
        }),
    ]


def test_passthrough_uses_checkpoint_without_creating_a_new_one(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    persisted = []
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=10, hard_input_budget_tokens=20,
        policy_layers={"request": {"processing_mode": "passthrough"}},
        history_summary_sink=persisted.append,
    ))
    memory = _Memory([TaskStep(task="current")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())
    model = _SummaryModel()
    result = manager.assemble_final_context(
        model=model, memory=memory, current_run_start_idx=0, run_context=run,
    )
    assert model.calls == []
    assert persisted == []
    assert result.evidence.history_compression_triggered is False
    assert result.evidence.loaded_summary_unit_id == 10


def test_adaptive_incrementally_compresses_only_summary_and_completed_turns(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    persisted = []
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20, hard_input_budget_tokens=100,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
        history_summary_sink=persisted.append,
    ))
    memory = _Memory([TaskStep(task="CURRENT RUN MUST NOT ENTER SUMMARY")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())
    model = _SummaryModel()
    result = manager.assemble_final_context(
        model=model, memory=memory, current_run_start_idx=0, run_context=run,
    )
    prompt = " ".join(
        part.get("text", "") for message in model.calls[0]
        for part in message.content if isinstance(part, dict)
    )
    assert "old" in prompt and "new question" in prompt and "new answer" in prompt
    assert "CURRENT RUN MUST NOT ENTER SUMMARY" not in prompt
    assert len(persisted) == 1
    assert persisted[0].covered_through_message_id == 22
    assert persisted[0].previous_summary_unit_id == 10
    assert result.evidence.new_summary_coverage == 22
    assert result.evidence.summary_persist_status == "succeeded"
    assert result.evidence.representation_cache_misses == 0
    assert all(
        representation == "raw"
        for _, representation in result.evidence.item_representations
    )


def test_summary_failure_and_plaintext_fallback_are_not_persisted(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    class PlainModel:
        def __call__(self, messages, stop_sequences=None):
            return type("Response", (), {"content": "lossy fallback", "token_usage": None})()
    persisted = []
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20, max_summary_reduce_tokens=20,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
        history_summary_sink=persisted.append,
    ))
    memory = _Memory([TaskStep(task="current")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())
    result = manager.assemble_final_context(
        model=PlainModel(), memory=memory, current_run_start_idx=0, run_context=run,
    )
    assert persisted == []
    assert result.evidence.summary_persist_status == "not_attempted"
    assert result.evidence.new_summary_coverage is None
    rendered = str(result.messages)
    assert "history limited" in rendered
    assert _summary_and_turns()[1].content["user_message"] == "new question " * 20


def test_current_action_compaction_does_not_mutate_agent_memory(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    actions = [ActionStep(
        step_number=index + 1, timing=Timing(start_time=0),
        tool_calls=[], observations="observation " * 1000,
        action_output="result", model_output="reasoning " * 1000,
    ) for index in range(6)]
    memory = _Memory([TaskStep(task="current"), *actions])
    before = [(action.observations, action.model_output) for action in actions]
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=100, hard_input_budget_tokens=200,
        keep_recent_steps=4,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    run = manager.prepare_run_context(memory, "", [])
    result = manager.assemble_final_context(
        model=_SummaryModel(), memory=memory, current_run_start_idx=0, run_context=run,
    )
    assert [(action.observations, action.model_output) for action in actions] == before
    states = dict(result.evidence.item_representations)
    assert states["current_action:0"] == "compact"
    assert states["current_action:1"] == "compact"
    assert all(states[f"current_action:{index}"] == "raw" for index in range(2, 6))
    assert result.evidence.current_action_compact_count == 2


def test_persistence_failure_does_not_block_current_context(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    def fail(_candidate):
        raise RuntimeError("db unavailable")
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
        history_summary_sink=fail,
    ))
    memory = _Memory([TaskStep(task="current")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())
    result = manager.assemble_final_context(
        model=_SummaryModel(), memory=memory, current_run_start_idx=0, run_context=run,
    )
    assert result.messages
    assert result.evidence.summary_persist_status == "failed"
    assert result.evidence.new_summary_coverage == 22


def test_no_drop_over_hard_budget_is_explicit_in_evidence(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=5, hard_input_budget_tokens=6,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    memory = _Memory([TaskStep(task="required current task " * 50)])
    run = manager.prepare_run_context(memory, "", [])
    result = manager.assemble_final_context(
        model=_SummaryModel(), memory=memory, current_run_start_idx=0, run_context=run,
    )
    assert "required current task" in str(result.messages)
    assert result.evidence.over_hard_budget is True
    assert result.evidence.compact_exhausted is True
    assert result.evidence.final_token_estimate > result.evidence.hard_budget
