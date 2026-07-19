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


class PlanningStep:
    """Minimal PlanningStep-shaped value accepted by the non-destructive projector."""

    def __init__(self, text):
        self.text = text

    def to_messages(self):
        return [{"role": "assistant", "content": [{"type": "text", "text": self.text}]}]


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


def test_summary_two_uses_summary_one_and_only_turns_after_its_coverage(monkeypatch):
    """A later checkpoint must not reintroduce raw turns covered by Summary 1."""
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    summary_two_model = _SummaryModel()
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20, hard_input_budget_tokens=100,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    inputs = [
        ContextItemInput(id="summary:one", type="history_summary", content={
            "unit_id": 101,
            "summary": {"task_overview": "SUMMARY ONE CHECKPOINT"},
            "covered_through_message_id": 12,
        }),
        ContextItemInput(id="turn:13:14", type="conversation_turn", content={
            "user_message": "ONLY NEW TURN QUESTION " * 10,
            "assistant_final_answer": "ONLY NEW TURN ANSWER " * 10,
            "user_message_id": 13, "assistant_message_id": 14,
        }),
    ]
    memory = _Memory([TaskStep(task="CURRENT RUN")])
    run = manager.prepare_run_context(memory, "", inputs)
    result = manager.assemble_final_context(
        model=summary_two_model, memory=memory, current_run_start_idx=0,
        run_context=run,
    )

    prompt = str(summary_two_model.calls[0])
    assert "SUMMARY ONE CHECKPOINT" in prompt
    assert "ONLY NEW TURN QUESTION" in prompt
    assert "ONLY NEW TURN ANSWER" in prompt
    assert "RAW TURN COVERED BY SUMMARY ONE" not in prompt
    assert "CURRENT RUN" not in prompt
    assert result.evidence.loaded_summary_unit_id == 101
    assert result.evidence.loaded_summary_coverage == 12
    assert result.evidence.new_history_turn_count == 1
    assert result.evidence.new_summary_coverage == 14
    assert result.evidence.selected_item_types.count("history_summary") == 1
    assert "conversation_turn" not in result.evidence.selected_item_types


def test_projects_planning_and_multiple_actions_in_stable_run_order(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    actions = [ActionStep(
        step_number=index + 1, timing=Timing(start_time=0),
        tool_calls=[], observations=f"observation {index + 1}",
        action_output=f"result {index + 1}", model_output=f"reasoning {index + 1}",
    ) for index in range(2)]
    memory = _Memory([
        TaskStep(task="CURRENT TASK"),
        PlanningStep("CURRENT PLAN"),
        *actions,
    ])
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=10000,
        policy_layers={"request": {"processing_mode": "passthrough"}},
    ))
    run = manager.prepare_run_context(memory, "", [])
    result = manager.assemble_final_context(
        model=None, memory=memory, current_run_start_idx=0, run_context=run,
    )

    assert result.evidence.selected_item_ids == (
        "current_task:0", "current_planning:0",
        "current_action:0", "current_action:1",
    )
    assert result.evidence.selected_item_types == (
        "current_task", "current_planning", "current_action", "current_action",
    )
    rendered = str(result.messages)
    positions = [rendered.index(marker) for marker in (
        "CURRENT TASK", "CURRENT PLAN", "reasoning 1", "reasoning 2",
    )]
    assert positions == sorted(positions)
    assert result.evidence.item_representations == (
        ("current_task:0", "raw"), ("current_planning:0", "raw"),
        ("current_action:0", "raw"), ("current_action:1", "raw"),
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


def test_compact_stages_old_actions_before_other_items(monkeypatch):
    """The documented action-first stage must win over a larger KB saving."""
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    action = ActionStep(
        step_number=1, timing=Timing(start_time=0), tool_calls=[],
        observations="old observation " * 500, action_output="old result",
        model_output="old reasoning " * 500,
    )
    memory = _Memory([TaskStep(task="task"), action])
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=50, hard_input_budget_tokens=10000,
        keep_recent_steps=0,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    run = manager.prepare_run_context(memory, "", [ContextItemInput(
        id="kb:large", type="knowledge_base",
        content={"text": "knowledge " * 3000},
    )])
    original_estimator = manager._estimate_items

    def stage_observer(items, stable, dynamic, tools):
        states = {item.id: item.metadata.get("representation", "raw") for item in items}
        if states.get("current_action:0") == "compact":
            return 1
        return max(51, original_estimator(items, stable, dynamic, tools))

    monkeypatch.setattr(manager, "_estimate_items", stage_observer)
    result = manager.assemble_final_context(
        model=_SummaryModel(), memory=memory, current_run_start_idx=0,
        run_context=run,
    )

    states = dict(result.evidence.item_representations)
    assert states["current_action:0"] == "compact"
    assert states["kb:large"] == "raw"
    assert result.evidence.current_action_compact_count == 1
    rendered = str(result.messages)
    assert "old observation" in rendered
    assert "old reasoning" not in rendered
    assert "knowledge knowledge" in rendered


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
