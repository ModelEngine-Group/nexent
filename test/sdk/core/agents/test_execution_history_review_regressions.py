# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Regressions for host readers, failed-output masking and standalone compaction."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from smolagents.memory import ActionStep, TaskStep, ToolCall
from smolagents.monitoring import Timing
from smolagents.utils import AgentExecutionError
from test_guardrail_checkpoints import KEYWORD, _make_step_agent, _msg

from nexent.core.agents.agent_model import GuardrailRule
from nexent.core.agents.context import ContextManager, ContextManagerConfig
from nexent.core.agents.context.execution_history import ExecutionHistory, summarize_record
from nexent.core.agents.context.models import ContextItem, ContextItemInput
from nexent.core.agents.context.rendering import ContextItemRenderer
from nexent.core.agents.core_agent import CoreAgent
from nexent.core.agents.sandbox import _install_host_tool_bridge
from nexent.core.tools.read_execution_output_tool import ReadExecutionOutputTool


def test_reader_bridge_keeps_live_history_and_callback_on_host():
    history = ExecutionHistory()
    key = history.register("owner", {"OUTPUT": "original sentinel"})
    history.bind(key, 5, 2)
    on_read = Mock()
    reader = ReadExecutionOutputTool(history, "owner", on_read)
    reader.to_dict = Mock(side_effect=AssertionError("Stateful reader must not be serialized"))
    namespace = {}
    sent_tools = []

    def send_tools(tools):
        sent_tools.append(tools)
        for tool in tools.values():
            tool.to_dict()

    def run_code(code):
        exec(code, namespace)  # noqa: S102 - Execute only the trusted bridge bootstrap under test.
        return SimpleNamespace(logs="")

    executor = SimpleNamespace(send_tools=send_tools, run_code_raise_errors=run_code, cleanup=Mock())
    _install_host_tool_bridge(executor, logging.getLogger(__name__))
    try:
        executor.send_tools({reader.name: reader})
        assert sent_tools == [{}]
        reader.to_dict.assert_not_called()
        bridge = executor._nexent_tool_bridge
        with bridge.execution_context() as execution_id:
            exec(bridge.execution_proxy_code(execution_id), namespace)  # noqa: S102
            result = namespace[reader.name]("message:5/unit-index:2")
            assert json.loads(result)["text"] == history.get(key).text
            on_read.assert_called_once_with()
            with pytest.raises(RuntimeError, match="not authorized"):
                namespace[reader.name]("message:6/unit-index:2")
            assert on_read.call_count == 1
    finally:
        executor.cleanup()


@pytest.mark.parametrize("backend", ["local", "docker"])
@pytest.mark.parametrize("severity", ["mask", "block", "pass", "disabled"])
def test_failed_execution_screens_partial_output_before_history_and_recall(backend, severity):
    rule = GuardrailRule(name="confidential", pattern=KEYWORD,
                         severity="mask" if severity == "disabled" else severity)
    agent = _make_step_agent(rule, [_msg("user", "run")], model_output="<code>fail()</code>")
    if severity == "disabled":
        agent.verification_controller.guardrail_engine = None
    agent.verification_controller.config.step_verification_enabled = False
    partial = "safe head\n" + KEYWORD + "\nsafe tail\n"
    error = RuntimeError("failure: " + KEYWORD)
    agent.python_executor.state = {"_print_outputs": partial} if backend == "local" else {}
    if backend == "docker":
        error.execution_logs = partial
    agent.python_executor.side_effect = error
    step = ActionStep(step_number=1, timing=Timing(start_time=0))
    with pytest.raises(AgentExecutionError) as failure:
        list(agent._step_stream(step))
    step.error = failure.value
    agent._execution_history = ExecutionHistory()
    agent._execution_owner = "owner"
    agent._execution_loaded = False
    agent.step_callbacks = SimpleNamespace(callback=Mock())
    CoreAgent._finalize_step(agent, step)
    record = agent._execution_history.get(step.execution_key)
    agent._execution_history.bind(step.execution_key, 5, 2)
    rendered = str(ContextItemRenderer().render([ContextItem.from_input(ContextItemInput(
        id="action", type="current_action", content={"execution_fields": record.fields},
    ))]))
    recalled = agent._execution_history.read("owner", record.reference)
    published = str(agent.observer.add_message.call_args_list)
    visible = str(agent.logger.log.call_args_list)
    assert "safe head" in step.observations and "safe tail" in step.observations
    assert "failure:" in str(step.error)
    for value in (step.observations, str(step.error), record.text, json.dumps(record.payload(), ensure_ascii=False),
                  rendered, recalled, published):
        assert (KEYWORD in value) == (severity in {"pass", "disabled"})
    if severity in {"mask", "block"}:
        assert KEYWORD not in visible
    # The summary input uses exactly the same screened record as recall/persistence.
    record.fields["OUTPUT"] += "\nsafe " * 500
    model = Mock(return_value=SimpleNamespace(content="safe failure summary"))
    model.last_finish_reason = "stop"
    model.observer = None
    model.extra_body = {}
    model.context_budget_snapshot = None
    summarize_record(record, model, 20000)
    assert (KEYWORD in str(model.call_args.args[0])) == (severity in {"pass", "disabled"})


@pytest.mark.parametrize("history_mode", ["none", "missing_key", "missing_record"])
@pytest.mark.parametrize("long_output", [False, True])
def test_no_record_action_compacts_only_above_threshold_without_fake_reference(history_mode, long_output):
    original = "head\n" + ("middle sentinel\n" * 5000 if long_output else "short\n") + "tail"
    step = ActionStep(step_number=1, timing=Timing(start_time=0),
                      tool_calls=[ToolCall(name="python_interpreter", arguments="print(data)", id="call")],
                      observations=original, model_output="<code>print(data)</code>")
    step.error = AgentExecutionError("known failure", Mock())
    if history_mode == "missing_record":
        step.execution_key = "unknown"
    history = None if history_mode == "none" else ExecutionHistory()
    manager = ContextManager(ContextManagerConfig(
        execution_history=history, effective_input_limit_tokens=10000,
        policy_layers={"request": {"processing_mode": "adaptive_compact"}},
    ))
    memory = SimpleNamespace(system_prompt=None, steps=[TaskStep(task="task"), step])
    model = Mock(side_effect=AssertionError("Unrecoverable results must not request an LLM summary"))
    result = manager.assemble_final_context(
        model=model, memory=memory, current_run_start_idx=0,
        run_context=manager.prepare_run_context(memory, "", []),
    )
    rendered = str(result.messages)
    assert "head" in rendered and "tail" in rendered
    assert "<ERROR>known failure</ERROR>" in rendered
    assert "OUTPUT_REF" not in rendered and "SUMMARIED_RESULT" not in rendered
    assert rendered.count("print(data)") == 1
    assert step.observations == original
    assert result.evidence.current_action_compact_count == int(long_output)
    assert result.evidence.final_token_estimate < 10000
    if long_output:
        assert "truncated" in rendered.lower()
        assert "middle sentinel\\nmiddle sentinel\\nmiddle sentinel" not in rendered[2500:-2500]
    model.assert_not_called()


def test_external_legacy_action_without_history_keeps_deterministic_compaction():
    action = ContextItem.from_input(ContextItemInput(
        id="external", type="current_action", content={"observations": "x" * 20000, "error": "known failure"},
    ))
    compact = ContextManager()._compact_execution(action, None)
    assert len(compact.content["observations"]) < 2100
    assert compact.content["error"] == "known failure"
    assert len(action.content["observations"]) == 20000
    assert "output_ref" not in compact.content
