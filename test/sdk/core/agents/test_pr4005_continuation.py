"""Acceptance tests for request-only format reminders and bare-text continuation."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from test_core_agent import TestRunStreamRealExecution as _CoreAgentFixtures
from test_core_agent import core_agent_module


def _text(message):
    return "".join(part.get("text", "") for part in message.content)


def _agent_with_responses(contents, *, strict, monkeypatch):
    class FakeActionOutput:
        def __init__(self, output, is_final_answer):
            self.output = output
            self.is_final_answer = is_final_answer

    monkeypatch.setattr(core_agent_module, "ActionOutput", FakeActionOutput)
    monkeypatch.setattr(core_agent_module, "AgentError", Exception)
    monkeypatch.setattr(
        core_agent_module,
        "ChatMessage",
        lambda role, content: SimpleNamespace(role=role, content=content),
    )
    monkeypatch.setattr(
        core_agent_module, "ActionStep", lambda **kwargs: SimpleNamespace(**kwargs)
    )
    monkeypatch.setattr(
        core_agent_module,
        "FinalAnswerStep",
        lambda output: SimpleNamespace(output=output),
    )
    monkeypatch.setattr(
        core_agent_module, "handle_agent_output_types", lambda output: output
    )
    agent, _, _ = _CoreAgentFixtures()._create_cmsr_007_step_agent(contents[0])
    responses = [
        SimpleNamespace(
            content=content,
            token_usage=None,
            model_attempt_id=f"attempt-{index}",
            model_attempt_number=1,
            model_attempt_commit_deferred=True,
        )
        for index, content in enumerate(contents)
    ]
    agent.model.side_effect = responses
    agent.enable_protocol_repair_retry = strict
    agent.enable_planning = False
    agent.verification_config = SimpleNamespace(
        enabled=False, final_verification_enabled=False
    )
    agent.final_answer_checks = []
    agent._finalize_step = MagicMock()
    agent._collect_step_metrics = MagicMock()
    agent._record_output_protocol = MagicMock()
    agent.python_executor = MagicMock(
        return_value=SimpleNamespace(
            output="done",
            is_final_answer=True,
            logs="",
        )
    )

    base = [
        SimpleNamespace(
            role="system", content=[{"type": "text", "text": "base system"}]
        ),
        SimpleNamespace(role="user", content=[{"type": "text", "text": "task"}]),
    ]

    def assemble(**kwargs):
        system = list(kwargs.get("request_system_messages", ()))
        tail = list(kwargs.get("request_tail_messages", ()))
        return SimpleNamespace(
            messages=[base[0], *system, base[1], *tail],
            memory_messages=base,
            evidence=MagicMock(),
        )

    agent.context_runtime.prepare_step.side_effect = assemble
    agent.context_runtime.recover_step.side_effect = assemble
    return agent, responses, base


@pytest.mark.parametrize("strict", [False, True])
def test_oc_022_bare_generation_continues_to_explicit_final(strict, monkeypatch):
    agent, responses, base = _agent_with_responses(
        ["The answer is ready.", '<code>final_answer("done")</code>'],
        strict=strict,
        monkeypatch=monkeypatch,
    )

    outputs = list(agent._run_stream("task", max_steps=2))

    assert outputs[-1].output == "done"
    assert agent.model.call_count == 2
    first = agent.model.call_args_list[0].args[0]
    second = agent.model.call_args_list[1].args[0]
    if strict:
        assert [_text(message) for message in first].count(
            core_agent_module._ACTION_FORMAT_REMINDER
        ) == 2
        assert _text(first[-1]) == core_agent_module._ACTION_FORMAT_REMINDER
        assert _text(second[-2]) == core_agent_module._ACTION_FORMAT_REMINDER
    else:
        assert all(
            core_agent_module._ACTION_FORMAT_REMINDER != _text(message)
            for message in first
        )
    assert "no action ran" in _text(second[-1])
    assert all("no action ran" not in _text(message) for message in base)
    assert all("The answer is ready" not in _text(message) for message in second)
    assert len(agent.memory.steps) == 1
    agent.observer.rollback_model_attempt.assert_called_once_with("attempt-0", 1)
    assert responses[0].model_attempt_commit_deferred is False


def test_oc_024_three_bare_generations_end_without_max_step_summary(monkeypatch):
    agent, _, _ = _agent_with_responses(
        ["thought one", "thought two", "thought three"],
        strict=True,
        monkeypatch=monkeypatch,
    )
    agent._handle_max_steps_reached = MagicMock()

    with pytest.raises(
        core_agent_module.ModelOutputProtocolExhaustedError, match="three generations"
    ):
        list(agent._run_stream("task", max_steps=2))

    assert agent.model.call_count == 3
    assert len(agent.memory.steps) == 0
    agent._handle_max_steps_reached.assert_not_called()


def test_oc_024_alternating_malformed_and_bare_share_limit(monkeypatch):
    agent, _, _ = _agent_with_responses(
        ["<code>final_answer(", "just thinking", "<code>final_answer("],
        strict=True,
        monkeypatch=monkeypatch,
    )
    agent._handle_max_steps_reached = MagicMock()

    with pytest.raises(core_agent_module.ModelOutputProtocolExhaustedError):
        list(agent._run_stream("task", max_steps=2))

    assert agent.model.call_count == 3
    assert len(agent.memory.steps) == 0
    agent._handle_max_steps_reached.assert_not_called()


def test_oc_014_protocol_repair_precedes_single_fixed_reminder(monkeypatch):
    agent, _, _ = _agent_with_responses(
        ["<code>final_answer(", '<code>final_answer("done")</code>'],
        strict=True,
        monkeypatch=monkeypatch,
    )

    outputs = list(agent._run_stream("task", max_steps=2))

    assert outputs[-1].output == "done"
    repaired_input = agent.model.call_args_list[1].args[0]
    texts = [_text(message) for message in repaired_input]
    assert texts[-1] == core_agent_module._ACTION_FORMAT_REMINDER
    assert "malformed_action" in texts[-2]
    assert texts.count(core_agent_module._ACTION_FORMAT_REMINDER) == 2
    assert all(
        "<code>final_answer(" not in text
        or text == core_agent_module._ACTION_FORMAT_REMINDER
        for text in texts
    )


def test_oc_024_stop_after_bare_does_not_dispatch_continuation(monkeypatch):
    agent, responses, _ = _agent_with_responses(
        ["thought"], strict=True, monkeypatch=monkeypatch
    )

    def stop_after_generation(*args, **kwargs):
        agent.stop_event.set()
        return responses[0]

    agent.model.side_effect = stop_after_generation
    with pytest.raises(core_agent_module.RunTerminated):
        list(agent._run_stream("task", max_steps=2))

    assert agent.model.call_count == 1


def test_oc_023_continuation_mentions_only_existing_unfinished_steps(monkeypatch):
    agent, _, _ = _agent_with_responses(
        ["thought"], strict=False, monkeypatch=monkeypatch
    )
    agent.current_plan = SimpleNamespace(
        steps=[
            SimpleNamespace(title="Done step", status="completed"),
            SimpleNamespace(title="Pending step", status="pending"),
        ]
    )

    message = agent._thought_continuation_message()

    assert "Pending step (pending)" in _text(message)
    assert "Done step" not in _text(message)


def test_chinese_request_only_reminders_and_continuation(monkeypatch):
    agent, _, base = _agent_with_responses(
        ["先想一下", '<code>final_answer("完成")</code>'],
        strict=True,
        monkeypatch=monkeypatch,
    )
    agent.lang = "zh-CN"

    outputs = list(agent._run_stream("task", max_steps=2))

    assert outputs[-1].output == "done"
    first = agent.model.call_args_list[0].args[0]
    second = agent.model.call_args_list[1].args[0]
    assert [_text(message) for message in first].count(
        core_agent_module._ACTION_FORMAT_REMINDER_ZH
    ) == 2
    assert _text(second[-2]) == core_agent_module._ACTION_FORMAT_REMINDER_ZH
    assert "没有执行动作" in _text(second[-1])
    assert all("没有执行动作" not in _text(message) for message in base)
