import json
import logging

import pytest

from smolagents.memory import ActionStep, TaskStep, ToolCall
from smolagents.monitoring import Timing
from nexent.core.utils.observer import MessageObserver

from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig
from nexent.core.agents.context.evidence import ContextEvidenceCollector
from nexent.core.context_runtime.contracts import ContextEvidence
from nexent.core.agents.context.history_compression import (
    HistorySummaryInput,
    _validate_summary_contract,
)
from nexent.core.agents.context.llm_summary import LLMSummary


def _rendered_text(messages):
    texts = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else message.content
        if isinstance(content, str):
            texts.append(content)
        else:
            texts.extend(
                part.get("text", "") for part in content or () if isinstance(part, dict)
            )
    return "\n".join(texts)


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
    content = (
        "# Compact Result of History\n\n"
        "## Task Overview\n\ntask\n\n"
        "## Completed Work\n\nwork\n\n"
        "## Key Decisions\n\ndecision\n\n"
        "## Unresolved Issues\n\nunresolved\n\n"
        "## Pending Items\n\npending\n\n"
        "## Next Steps\n\nnext\n\n"
        "## Context To Preserve\n\ncontext"
    )
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
            "unit_id": 10, "summary": "old summary text",
            "covered_through_message_id": 20,
        }),
        ContextItemInput(id="turn:21:22", type="conversation_turn", content={
            "user_message": "new question " * 100,
            "assistant_final_answer": "new answer " * 100,
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


def test_proactive_compaction_uses_previous_result_and_persists_only_final(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)

    class ShrinkingModel:
        def __init__(self):
            self.calls = 0

        def __call__(self, messages, stop_sequences=None):
            self.calls += 1
            sizes = (12000, 10000, 1000)
            content = _Response.content.replace(
                "## Task Overview\n\ntask",
                "## Task Overview\n\n" + "x" * sizes[self.calls - 1],
            )
            return type("Response", (), {"content": content, "token_usage": None})()

    persisted = []
    manager = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=10000,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
        history_summary_sink=persisted.append,
    ))
    large_turns = [
        ContextItemInput(id="turn:21:22", type="conversation_turn", content={
            "user_message": "question " * 6000,
            "assistant_final_answer": "answer " * 6000,
            "attachments": [], "user_message_id": 21, "assistant_message_id": 22,
        })
    ]
    model = ShrinkingModel()
    run = manager.prepare_run_context(_Memory([]), "", large_turns)
    result = manager.assemble_final_context(
        model=model, memory=_Memory([]), current_run_start_idx=0, run_context=run,
    )

    assert model.calls == 3
    assert len(persisted) == 1
    snapshot = persisted[0]
    assert snapshot.compaction_attempts == 3
    assert snapshot.history_tokens_before > snapshot.history_tokens_after
    assert snapshot.compaction_trigger_threshold_tokens == 8000
    assert snapshot.compaction_target_tokens == 6000
    assert result.evidence.compaction_attempts == 3


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
            "summary": "SUMMARY ONE CHECKPOINT",
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
        "CURRENT TASK", "CURRENT PLAN", "observation 1", "observation 2",
    )]
    assert positions == sorted(positions)
    assert '<completed_action_history read_only="true">' in rendered
    assert "Calling tools:" not in rendered
    assert "Observation:" not in rendered

    assert "reasoning 1" not in rendered
    assert "reasoning 2" not in rendered
    assert result.evidence.item_representations == (
        ("current_task:0", "raw"), ("current_planning:0", "raw"),
        ("current_action:0", "raw"), ("current_action:1", "raw"),
    )


def test_projects_tool_calls_as_json_serializable_payloads(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    monkeypatch.setattr(
        ActionStep,
        "to_messages",
        lambda _step: (_ for _ in ()).throw(
            AssertionError("current action history must use neutral structured rendering")
        ),
    )
    tool_call = ToolCall(name="python_interpreter", arguments="print('ok')", id="call_1")
    action = ActionStep(
        step_number=1, timing=Timing(start_time=0), tool_calls=[tool_call],
        observations="ok", action_output="done", model_output="reasoning",
    )
    memory = _Memory([TaskStep(task="current"), action])
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=10000,
        policy_layers={"request": {"processing_mode": "passthrough"}},
    ))

    projected = manager._project_current_run(memory, 0)
    action_item = next(item for item in projected if item.type.value == "current_action")
    assert "messages" not in action_item.content
    assert action_item.content["tool_calls"] == [{
        "name": "python_interpreter", "arguments": "print('ok')", "id": "call_1",
    }]
    json.dumps(action_item.content)

    run = manager.prepare_run_context(memory, "", [])
    result = manager.assemble_final_context(
        model=None, memory=memory, current_run_start_idx=0, run_context=run,
    )
    rendered = _rendered_text(result.messages)
    assert "tool: python_interpreter" in rendered
    assert "print('ok')" in rendered
    assert "outcome:\nok" in rendered
    assert "recorded_result:\ndone" in rendered
    assert "Calling tools:" not in rendered
    assert "Observation:" not in rendered

    summary_rendered = _rendered_text(manager.render_memory_messages(memory))
    assert "tool: python_interpreter" in summary_rendered
    assert "outcome:\nok" in summary_rendered
    assert "Calling tools:" not in summary_rendered
    assert "Observation:" not in summary_rendered


def test_summary_failure_and_plaintext_fallback_are_not_persisted(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    class PlainModel:
        def __call__(self, messages, stop_sequences=None):
            return type("Response", (), {"content": "lossy fallback", "token_usage": None})()
    persisted = []
    statuses = []
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20, max_summary_reduce_tokens=20,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
        history_summary_sink=persisted.append,
        history_summary_status_sink=statuses.append,
    ))
    memory = _Memory([TaskStep(task="current")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())
    result = manager.assemble_final_context(
        model=PlainModel(), memory=memory, current_run_start_idx=0, run_context=run,
    )
    assert persisted == []
    assert statuses == [{"status": "compacting"}, {"status": "idle"}]
    assert result.evidence.summary_persist_status == "not_attempted"
    assert result.evidence.new_summary_coverage is None
    rendered = str(result.messages)
    assert "history limited" in rendered
    assert _summary_and_turns()[1].content["user_message"] == "new question " * 100


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
    assert all(states[f"current_action:{index}"] == "compact" for index in range(6))
    assert result.evidence.current_action_compact_count == 6


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


def test_recent_actions_are_compacted_as_last_resort(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    action = ActionStep(
        step_number=1, timing=Timing(start_time=0), tool_calls=[],
        observations="database row " * 1000, action_output="database result " * 1000,
        model_output="reasoning " * 1000,
    )
    memory = _Memory([TaskStep(task="task"), action])
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=50, hard_input_budget_tokens=10000,
        keep_recent_steps=4,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    run = manager.prepare_run_context(memory, "", [])

    result = manager.assemble_final_context(
        model=_SummaryModel(), memory=memory, current_run_start_idx=0,
        run_context=run,
    )

    states = dict(result.evidence.item_representations)
    assert states["current_action:0"] == "compact"
    assert result.evidence.current_action_compact_count == 1


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


def test_input_limit_excess_is_evidence_and_does_not_drop_required_content(monkeypatch):
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
    assert result.evidence.exceeds_effective_input_limit is True
    assert result.evidence.final_token_estimate > result.evidence.effective_input_limit_tokens


def test_new_history_summary_event_is_consumed_once(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    statuses = []
    manager = ContextManager(ContextManagerConfig(
        soft_input_budget_tokens=20, hard_input_budget_tokens=100,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
        history_summary_status_sink=statuses.append,
    ))
    memory = _Memory([TaskStep(task="current")])
    run = manager.prepare_run_context(memory, "", _summary_and_turns())

    manager.assemble_final_context(
        model=_SummaryModel(), memory=memory, current_run_start_idx=0, run_context=run,
    )

    event = manager.consume_history_summary_event()
    assert event is not None
    assert event["covered_through_message_id"] == 22
    assert event["summary"]
    assert event["status"] == "accepted"
    assert statuses == [{"status": "compacting"}]
    assert manager.consume_history_summary_event() is None


def test_target_sized_checkpoint_is_not_recompressed_for_fixed_context(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    manager = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=1000,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    inputs = [ContextItemInput(id="summary:10", type="history_summary", content={
        "unit_id": 10,
        "summary": {"markdown": _Response.content},
        "covered_through_message_id": 20,
    })]
    memory = _Memory([TaskStep(task="fixed request context " * 1000)])
    run = manager.prepare_run_context(memory, "", inputs)
    model = _SummaryModel()

    result = manager.assemble_final_context(
        model=model, memory=memory, current_run_start_idx=0, run_context=run,
    )

    assert model.calls == []
    assert result.evidence.compaction_stop_reason == "history_target_reached"
    assert result.evidence.history_compression_triggered is False


def test_small_increment_is_not_recompressed_when_fixed_context_makes_target_unreachable(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)
    manager = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=1000,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    inputs = [
        ContextItemInput(id="summary:10", type="history_summary", content={
            "unit_id": 10,
            "summary": {"markdown": "accepted checkpoint"},
            "covered_through_message_id": 20,
        }),
        ContextItemInput(id="turn:21:22", type="conversation_turn", content={
            "user_message": "small increment",
            "assistant_final_answer": "small answer",
            "user_message_id": 21,
            "assistant_message_id": 22,
        }),
    ]
    memory = _Memory([TaskStep(task="fixed request context " * 55)])
    run = manager.prepare_run_context(memory, "", inputs)
    model = _SummaryModel()

    result = manager.assemble_final_context(
        model=model, memory=memory, current_run_start_idx=0, run_context=run,
    )

    assert result.evidence.raw_token_estimate >= 800
    assert result.evidence.non_history_tokens >= 600
    assert model.calls == []
    assert result.evidence.compaction_stop_reason == "history_target_reached"
    assert result.evidence.history_compression_triggered is False


def test_history_summary_input_ignores_runtime_fields():
    turn = ContextItemInput(id="turn:21:22", type="conversation_turn", content={
        "user_message": "question",
        "assistant_final_answer": "answer",
        "user_message_id": 21,
        "assistant_message_id": 22,
        "reasoning": "MUST NOT APPEAR",
        "deep_thinking": "MUST NOT APPEAR",
        "tool": "MUST NOT APPEAR",
        "token_count": "MUST NOT APPEAR",
        "ui_event": "MUST NOT APPEAR",
    })
    rendered = HistorySummaryInput.from_items(None, [turn]).render()
    assert "question" in rendered and "answer" in rendered
    assert "MUST NOT APPEAR" not in rendered


def test_summary_call_uses_isolated_dynamic_output_budget(monkeypatch):
    monkeypatch.setattr("smolagents.memory.SystemPromptStep", _SystemPrompt)

    class BudgetAwareModel:
        def __init__(self):
            self.observer = MessageObserver()
            self.context_budget_snapshot = {"requested_output_tokens": 512}
            self.extra_body = {"existing": True}
            self.max_tokens_seen = []

        def __call__(self, messages, stop_sequences=None, **kwargs):
            assert self.context_budget_snapshot is None
            assert self.extra_body == {
                "existing": True,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            self.max_tokens_seen.append(kwargs["max_tokens"])
            self.observer.add_model_new_token("MUST NOT STREAM")
            return _Response()

    manager = ContextManager(ContextManagerConfig(
        effective_input_limit_tokens=1000,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    model = BudgetAwareModel()
    original_observer = model.observer
    run = manager.prepare_run_context(_Memory([]), "", _summary_and_turns())

    manager.assemble_final_context(
        model=model, memory=_Memory([]), current_run_start_idx=0, run_context=run,
    )

    assert model.max_tokens_seen
    assert all(limit > 0 for limit in model.max_tokens_seen)
    assert model.context_budget_snapshot == {"requested_output_tokens": 512}
    assert model.extra_body == {"existing": True}
    assert model.observer is original_observer
    assert original_observer.message_query == []


@pytest.mark.parametrize("mutate", [
    lambda text: text.replace("## Task Overview", "## Completed Work", 1),
    lambda text: text.replace("## Pending Items\n\npending\n\n", ""),
    lambda text: text + "\n\n## Extra Section\n\nextra",
    lambda text: text.rsplit("## Context To Preserve", 1)[0],
    lambda text: text + "\n\nWord count: 42",
    lambda text: text.replace("context", "As an AI: I thought about this"),
])
def test_summary_contract_rejects_noncanonical_output(mutate):
    keys = tuple(ContextManagerConfig().summary_json_schema)
    assert _validate_summary_contract(mutate(_Response.content), keys) is None


def test_summary_contract_rejects_omitted_protected_fact_literal():
    keys = tuple(ContextManagerConfig().summary_json_schema)
    source = (
        "验证事实 E2E-3-063：巡检码为星河-324。\n"
        "验证事实 E2E-3-064：巡检码为星河-377。"
    )
    lossy = _Response.content.replace(
        "context",
        "E2E-3-063 through E2E-3-064 use 星河 codes; for example E2E-3-063=星河-324",
    )
    assert _validate_summary_contract(lossy, keys, source_text=source) is None


def test_summary_contract_accepts_compact_protected_fact_ledger():
    keys = tuple(ContextManagerConfig().summary_json_schema)
    source = (
        "验证事实 E2E-3-063：巡检码为星河-324。\n"
        "验证事实 E2E-3-064：巡检码为星河-377。"
    )
    lossless = _Response.content.replace(
        "context",
        "- E2E-3-063 = 星河-324\n- E2E-3-064 = 星河-377",
    )
    assert _validate_summary_contract(lossless, keys, source_text=source) == lossless


def test_summary_prompt_forbids_range_example_and_formula_substitution():
    model = _SummaryModel()
    LLMSummary(ContextManagerConfig(), renderer=None).generate_summary(
        "验证事实 E2E-3-064：巡检码为星河-377。",
        model,
    )
    prompt = _rendered_text(model.calls[0])
    assert "Preserve every explicit fact identifier" in prompt
    assert "ranges, selected examples, inferred patterns, or formulas" in prompt


def test_context_evidence_log_is_pretty_printed(caplog):
    collector = ContextEvidenceCollector()
    collector.record_call(ContextEvidence(
        processing_mode="adaptive_compact",
        raw_token_estimate=120,
        final_token_estimate=80,
    ))

    with caplog.at_level(logging.INFO, logger="context_evidence"):
        collector.finalize(status="completed")

    assert "Agent loop context evidence:\n{" in caplog.text
    assert '\n  "final_token_estimate": 80,' in caplog.text
    assert '\n  "processing_mode": "adaptive_compact",' in caplog.text
