"""Exercise the real CodeAgent loop with a deterministic model and executor."""
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from smolagents import Tool
from smolagents.models import ChatMessage, Model

from nexent.core.agents.context import ContextManager, ContextManagerConfig, ManagedContextRuntime
from nexent.core.agents.core_agent import CoreAgent
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.utils.observer import MessageObserver

FORM = [{"id": "scope", "type": "text", "title": "Which region?"}]
CODE = f"ask_user(questions={FORM!r})"


class ScriptedModel(Model):
    def __init__(self, outputs):
        super().__init__()
        self.outputs = iter(outputs)
        self.calls = []
        self.on_call = lambda: None

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        self.on_call()
        return ChatMessage(role="assistant", content=next(self.outputs))


class RecordTool(Tool):
    name = "record"
    description = "Record one action for verification."
    inputs = {}
    output_type = "string"

    def __init__(self):
        super().__init__()
        self.calls = 0

    def forward(self):
        self.calls += 1
        return "recorded"


@pytest.fixture
def build_agent():
    def build(outputs, tools=None, **kwargs):
        observer = MessageObserver()
        model = ScriptedModel(outputs)
        agent = CoreAgent(
            observer=observer, model=model, tools=tools or [], enable_clarification=True,
            context_runtime=ManagedContextRuntime(ContextManager(ContextManagerConfig())),
            verbosity_level=0, **kwargs,
        )
        return agent, model, observer
    return build


def events(observer):
    return [json.loads(message) for message in observer.get_cached_message()]


@pytest.mark.parametrize("prefix", ["", "思考：缺少地区信息，需要询问用户。\n\n代码：\n", "Think: Ask for the region.\nCode:\n"])
def test_clarification_ends_run_without_executor_verifier_or_next_model_call(build_agent, prefix):
    agent, model, observer = build_agent([f"{prefix}<code>{CODE}</code>"])
    executor = MagicMock(wraps=agent.python_executor)
    agent.python_executor = executor
    verifier = MagicMock()
    agent.verification_controller.verify_final_answer = verifier
    result = agent.run("Analyze sales", max_steps=1)
    assert str(result) == "1. Which region?"
    assert len(model.calls) == 1
    executor.assert_not_called()
    verifier.assert_not_called()
    cards = [event for event in events(observer) if event["type"] == "human_interaction"]
    assert len(cards) == 1
    assert isinstance(cards[0]["content"], dict)
    assert cards[0]["content"]["schema_version"] == 1
    assert cards[0]["content"]["questions"][0]["title"] == "Which region?"
    assert agent.step_number == 2
    assert agent.memory.steps[-1].is_final_answer


@pytest.mark.parametrize("output", [f"record(); {CODE}", f"x = {CODE}", f"{CODE}; record()"])
def test_mixed_actions_are_not_partially_executed(build_agent, output):
    tool = RecordTool()
    agent, model, observer = build_agent([f"<code>{output}</code>", f"<code>{CODE}</code>"], [tool])
    assert str(agent.run("Help")) == "1. Which region?"
    assert tool.calls == 0
    assert len(model.calls) == 2
    assert sum(event["type"] == "human_interaction" for event in events(observer)) == 1


def test_structured_model_output_uses_same_terminal_parser(build_agent):
    agent, model, _ = build_agent([json.dumps({"code": CODE})])
    agent._use_structured_outputs_internally = True
    assert str(agent.run("Help")) == "1. Which region?"
    assert len(model.calls) == 1


def test_invalid_options_get_schema_feedback_before_repair(build_agent):
    question = {
        "id": "scope", "type": "single_choice", "title": "Which scope?",
        "options": [{"id": f"item_{index}", "label": f"Item {index}"} for index in range(13)],
    }
    agent, model, observer = build_agent([
        f"思考：需要确认范围。\n代码：\n<code>ask_user(questions={[question]!r})</code>",
        f"<code>{CODE}</code>",
    ])
    assert str(agent.run("Help")) == "1. Which region?"
    assert len(model.calls) == 2
    feedback = str(model.calls[1][-1].content)
    assert "questions.0.options: too_long" in feedback
    assert "2-12 options" in feedback
    assert sum(event["type"] == "human_interaction" for event in events(observer)) == 1


def test_stop_after_generation_publishes_no_card_or_extra_model_call(build_agent):
    agent, model, observer = build_agent([f"<code>{CODE}</code>"])
    model.on_call = agent.stop_event.set
    with pytest.raises(RunTerminated):
        agent.run("Help", max_steps=1)
    assert len(model.calls) == 1
    assert all(event["type"] != "human_interaction" for event in events(observer))


def test_stopped_last_step_never_calls_max_step_summary(build_agent):
    tool = RecordTool()
    agent, model, _ = build_agent(["<code>record()</code>"], [tool])
    tool.forward = lambda: agent.stop_event.set()
    agent._handle_max_steps_reached = MagicMock()
    with pytest.raises(RunTerminated):
        agent.run("Help", max_steps=1)
    assert len(model.calls) == 1
    agent._handle_max_steps_reached.assert_not_called()


def test_planning_form_does_not_advance_unfinished_plan(build_agent):
    agent, model, _ = build_agent([f"<code>{CODE}</code>"], enable_planning=True)
    plan = SimpleNamespace(steps=[SimpleNamespace(status="in_progress")])
    model.on_call = lambda: setattr(agent, "current_plan", plan)
    agent.plan_repo = None
    agent._implicit_advance_step = MagicMock()
    agent.run("Help")
    agent._implicit_advance_step.assert_not_called()
    assert plan.steps[0].status == "in_progress"


def test_cancel_exception_bypasses_ordinary_exception_handlers():
    assert issubclass(RunTerminated, BaseException)
    assert not issubclass(RunTerminated, Exception)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_output", [False, True])
async def test_worker_drains_card_or_terminal_protocol_error(monkeypatch, invalid_output):
    from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.agents.output_protocol import ModelOutputProtocolExhaustedError
    from nexent.core.agents.run_agent import agent_run
    from nexent.core.concurrency import LanePolicy, ThreadManager

    model = ScriptedModel(["bare answer"] * 3 if invalid_output else [f"思考：请用户补充信息。\n代码：\n<code>{CODE}</code>"])
    monkeypatch.setattr(NexentAgent, "create_model", lambda *_: model)
    manager = ThreadManager(service_name="clarification-test", lane_policies={
        "agent-run": LanePolicy(name="agent-run", max_workers=1, max_queue_size=0),
    })
    manager.start()
    info = AgentRunInfo(query="Analyze sales", model_config_list=[], observer=MessageObserver(), stop_event=threading.Event(),
                        agent_config=AgentConfig(name="root", description="test", model_name="test", tools=[]))
    try:
        chunks = []

        async def drain():
            async for chunk in agent_run(info, thread_manager=manager):
                chunks.append(json.loads(chunk))

        await drain()
        if invalid_output:
            assert isinstance(info.thread_future.exception(), ModelOutputProtocolExhaustedError)
            assert info.attempt_outcome == "failed"
            errors = [chunk for chunk in chunks if chunk["type"] == "error"]
            assert len(errors) == 1
            assert errors[0]["error_code"] == "model_output_protocol_exhausted"
            assert errors[0]["retryable"] is False
            assert errors[0]["content"].startswith("模型连续未遵循")
            assert not any(chunk["type"] == "final_answer" for chunk in chunks)
            assert len(model.calls) == 3
        else:
            assert info.attempt_outcome == "completed"
            assert sum(chunk["type"] == "human_interaction" for chunk in chunks) == 1
            assert [chunk["content"] for chunk in chunks if chunk["type"] == "final_answer"] == ["1. Which region?"]
            assert len(model.calls) == 1
        assert info.thread_future.done()
        assert manager.snapshot().active_count == 0
    finally:
        await manager.shutdown(timeout=1)


@pytest.mark.parametrize("action", ["block", "mask"])
def test_clarification_uses_existing_content_guardrail(build_agent, action):
    agent, model, observer = build_agent([f"<code>{CODE}</code>"])
    engine = MagicMock()
    engine.check_input.return_value.effective_action = "pass"
    engine.check_tool_args.return_value = SimpleNamespace(
        effective_action=action, verification_result=SimpleNamespace(), message="filtered",
        matched_texts=["Which region?"], rule_name="test-rule", masked_args=None,
        masked_kwargs={"questions": [{"id": "scope", "type": "text", "title": "Filtered question"}]},
    )
    agent.verification_controller.guardrail_engine = engine
    agent.verification_controller.emit = MagicMock()
    result = str(agent.run("Help"))
    cards = [event for event in events(observer) if event["type"] == "human_interaction"]
    engine.check_tool_args.assert_called_once()
    assert len(model.calls) == 1
    if action == "block":
        assert not cards
        assert "test-rule" in result
        assert agent.verification_controller.pending_tool_block_refusal is None
    else:
        assert len(cards) == 1
        assert cards[0]["content"]["questions"][0]["title"] == "Filtered question"
        assert result == "1. Filtered question"
