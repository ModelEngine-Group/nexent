"""CMSR-D1-003: semantic repair uses the same streamed attempt lifecycle."""

import json
import logging
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nexent.core.agents.core_agent import CoreAgent
from nexent.core.agents.output_protocol import ModelOutputProtocolError
from nexent.core.utils.observer import MessageObserver


def _events(observer):
    return [json.loads(raw) for raw in observer.get_cached_message()]


def test_cmsr_d1_003_step_one_semantic_repair_streams_and_commits(caplog):
    caplog.set_level(logging.INFO, logger="nexent.core.agents.core_agent")
    observer = MessageObserver(lang="en")
    first_repair_chunk = threading.Event()
    release_repair = threading.Event()
    calls = []

    class ControlledModel:
        supports_deferred_attempt_commit = True
        last_finish_reason = "stop"

        def __call__(self, _messages, **kwargs):
            assert kwargs["_defer_attempt_commit"] is True
            assert "_suppress_attempt_stream" not in kwargs
            attempt = len(calls) + 1
            calls.append(attempt)
            attempt_id = f"semantic-{attempt}"
            observer.begin_model_attempt(attempt_id, attempt)
            if attempt == 1:
                content = "<code></code>"
                observer.add_model_new_token(content)
            else:
                observer.add_model_new_token("修复后：<code>")
                first_repair_chunk.set()
                assert release_repair.wait(timeout=5)
                observer.add_model_new_token("final_answer('ok')</code>")
                content = "修复后：<code>final_answer('ok')</code>"
            observer.flush_remaining_tokens()
            return SimpleNamespace(
                content=content,
                token_usage=None,
                model_attempt_id=attempt_id,
                model_attempt_number=attempt,
                model_attempt_commit_deferred=True,
            )

    agent = object.__new__(CoreAgent)
    agent.agent_name = "test"
    agent.name = "test"
    agent.observer = observer
    agent.step_number = 1
    agent.memory = SimpleNamespace(steps=[])
    agent.logger = MagicMock()
    agent.model = ControlledModel()
    agent.context_runtime = MagicMock()
    agent.context_runtime.prepare_step.return_value = SimpleNamespace(
        messages=[], evidence=None
    )
    agent.context_runtime.token_counts.return_value = {}
    agent._history_step_count = 0
    agent._context_tools = lambda: []
    agent._emit_history_summary_event = lambda: None
    agent._log_model_call_parameters = lambda *_args, **_kwargs: None
    agent._record_output_protocol = lambda *_args, **_kwargs: None
    agent._use_structured_outputs_internally = False
    agent._protocol_repair_messages = []
    agent._consecutive_protocol_errors = 0
    agent.output_protocol = "code_action"
    agent.verification_controller = None
    agent.stop_event = threading.Event()
    agent.enable_planning = False
    agent.python_executor = MagicMock(
        return_value=SimpleNamespace(output="ok", logs="", is_final_answer=True)
    )

    def step():
        return SimpleNamespace(
            step_number=1,
            model_output=None,
            model_output_message=None,
            token_usage=None,
            model_input_messages=None,
            tool_calls=None,
        )

    with pytest.raises(ModelOutputProtocolError) as failed:
        list(agent._step_stream(step()))
    agent._consecutive_protocol_errors = 1
    agent._append_protocol_repair_context(failed.value)
    events = _events(observer)
    assert [event["type"] for event in events[:2]] == [
        "step_count", "model_attempt_control"
    ]
    assert [event["phase"] for event in events if event["type"] == "model_attempt_control"] == [
        "begin", "rollback"
    ]

    outcome = {}

    def complete_repair():
        try:
            outcome["result"] = list(agent._step_stream(step()))
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=complete_repair)
    thread.start()
    try:
        assert first_repair_chunk.wait(timeout=5)
        paused_events = _events(observer)
        assert any(
            event["type"] == "model_output_thinking"
            and event["content"].startswith("修复后：<code>")
            and event["attempt_id"] == "semantic-2"
            for event in paused_events
        )
        assert not any(
            event.get("phase") == "commit" for event in paused_events
        )
    finally:
        release_repair.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert "error" not in outcome, outcome.get("error")
    assert len(calls) == 2
    assert agent.python_executor.call_count == 1
    events.extend(paused_events)
    events.extend(_events(observer))
    assert [event["phase"] for event in events if event["type"] == "model_attempt_control"] == [
        "begin", "rollback", "begin", "commit"
    ]
    assert len([event for event in events if event["type"] == "parse"]) == 1
    assert len([event for event in events if event["type"] == "step_count"]) == 1
    assert any(
        event["attempt_id"] == "semantic-2"
        for event in events
        if event["type"].startswith("model_output_") and event["content"]
    )
    assert "model_output_protocol_repair_accepted" in caplog.text
    assert "final_answer('ok')" not in caplog.text
