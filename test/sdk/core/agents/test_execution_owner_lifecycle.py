# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""EO-01..03: a real CoreAgent.run must keep grants and readers on its fresh owner."""

import json
from copy import deepcopy

import pytest
from smolagents.agents import EMPTY_PROMPT_TEMPLATES
from smolagents.models import Model

from nexent.core.agents.context import ContextManager
from nexent.core.agents.context.execution_history import ExecutionHistory, result_text
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
from nexent.core.utils.observer import MessageObserver
from test_persisted_codeagent_actions import records, history_turn


class NoInference(Model):
    def generate(self, *args, **kwargs):
        raise AssertionError("Owner initialization must not dispatch a model")


def historical_turn(message=98):
    source = records()
    source[0].update(unit_index=5, content="source call", tool_call_id="local-source", invocation_id=None)
    source[1].update(unit_index=6, content="SOURCE_ALPHA", tool_call_id=None, invocation_id=None)
    fields = {"STDOUT": "SOURCE_ALPHA\n", "OUTPUT": json.dumps({"rows": [{"id": "row-1", "amount": 10}]})}
    action = dict(schema_version=1, agent_core="smolagents", step_number=1, dispatch_state="dispatched",
                  tool_calls=[dict(id="call_1", name="python_interpreter", arguments="print(source())")])
    source[2].update(unit_index=7, tool_call_id=None, invocation_id=None, content=json.dumps({
        "content": result_text(fields), "model_action": action, "covered_unit_indices": [5, 6]}))
    return history_turn(message, execution_records=source, question="Original task", answer="Source saved")


def make_agent(items=None, *, history=True, read_conversation_result=None):
    observer = MessageObserver(lang="en")
    if history:
        observer.execution_history = ExecutionHistory(read_conversation_result=read_conversation_result)
    runtime = ManagedContextRuntime(
        ContextManager(), items if items is not None else [historical_turn()]
    )
    templates = deepcopy(EMPTY_PROMPT_TEMPLATES)
    templates["system_prompt"] = "Use only authorized historical originals."
    agent = CoreAgent(
        observer=observer,
        model=NoInference(model_id="no-provider"),
        tools=[],
        name="owner_lifecycle",
        context_runtime=runtime,
        prompt_templates=templates,
        max_steps=1,
        verbosity_level=0,
    )
    return agent, runtime


def begin(agent):
    stream = agent.run("Inspect the existing authorized sources", stream=True)
    stream.close()
    return agent._execution_owner


@pytest.mark.parametrize("summary", ["Completed earlier work", "Forged message:999/unit-index:7"])
def test_summary_only_new_run_pages_backend_authorized_originals_without_prompt_restore(summary):
    from nexent.core.agents.contracts.context import ContextItemInput

    calls = []
    original = "REAL RESULT: " + "原文" * 20

    def read(message, index):
        calls.append((message, index))
        if (message, index) != (98, 7):
            raise PermissionError("foreign or missing conversation result")
        return original

    checkpoint = ContextItemInput(id="summary", type="history_summary", content={
        "summary": summary, "covered_through_message_id": 100,
    })
    agent, runtime = make_agent(items=[checkpoint], read_conversation_result=read)
    owner = begin(agent)
    reader = agent.tools["read_execution_output"]
    first = json.loads(reader.forward("message:98/unit-index:7", 0, 9))
    rest = json.loads(reader.forward("message:98/unit-index:7", first["next_offset"], 4000))
    assert first["text"] + rest["text"] == original and rest["eof"]
    assert original not in str(runtime.items)
    with pytest.raises(PermissionError):
        reader.forward("message:999/unit-index:7")
    assert calls == [(98, 7), (98, 7), (999, 7)]
    with pytest.raises(PermissionError):
        agent._execution_history.read("foreign-owner", "message:98/unit-index:7")
    assert agent._execution_owner == owner


@pytest.mark.parametrize("reused", [False, True])
def test_actual_run_aligns_current_owner_reader_manager_and_historical_grants(reused):
    agent, runtime = make_agent()
    constructor_owner = agent._execution_owner
    first_owner = begin(agent)
    assert first_owner != constructor_owner
    if reused:
        first_owner, previous = begin(agent), first_owner
        assert first_owner != previous
    reader = agent.tools["read_execution_output"]
    assert reader.owner == first_owner
    result = json.loads(reader.forward("message:98/unit-index:7", 0, 16000))
    assert (
        result["text"]
        == json.loads(historical_turn().content["execution_records"][-1]["content"])[
            "content"
        ]
    )
    assert result["eof"] is True


def test_new_owner_reads_same_run_records_but_not_previous_live_or_foreign_records():
    agent, _ = make_agent()
    begin(agent)
    history = agent._execution_history
    old_owner = agent._execution_owner
    old_key = history.register(old_owner, {"OUTPUT": "OLD_UNCOMMITTED"})
    history.bind_run(old_key, "a" * 32, 1)
    foreign_key = history.register("foreign-owner", {"OUTPUT": "FOREIGN"})
    history.bind_run(foreign_key, "b" * 32, 1)
    current = begin(agent)
    key = history.register(current, {"OUTPUT": "CURRENT"})
    history.bind_run(key, "c" * 32, 1)
    reader = agent.tools["read_execution_output"]
    assert (
        "CURRENT"
        in json.loads(reader.forward("run:" + "c" * 32 + "/execution:1"))["text"]
    )
    for ref in [
        "run:" + "a" * 32 + "/execution:1",
        "run:" + "b" * 32 + "/execution:1",
        "message:999/unit-index:7",
    ]:
        with pytest.raises(PermissionError, match="not authorized"):
            reader.forward(ref)
    assert current != old_owner


def test_reused_runtime_only_regrants_the_current_authorized_snapshot():
    agent, runtime = make_agent()
    old_owner = begin(agent)
    runtime.replace_items([historical_turn(200)])
    current = begin(agent)
    assert current != old_owner
    reader = agent.tools["read_execution_output"]
    assert reader.owner == current
    assert (
        "SOURCE_ALPHA" in json.loads(reader.forward("message:200/unit-index:7"))["text"]
    )
    with pytest.raises(PermissionError):
        reader.forward("message:98/unit-index:7")


def test_no_history_does_not_add_a_reader_or_owner_grants():
    agent, runtime = make_agent(history=False)
    assert "read_execution_output" not in agent.tools
    before = agent._execution_owner
    assert begin(agent) == before
    assert runtime.context_manager.config.execution_history is None


def test_runtime_without_context_manager_keeps_fresh_reader_owner_compatibility():
    from types import SimpleNamespace

    agent, _ = make_agent()
    agent.context_runtime = SimpleNamespace(prepare_run=lambda **kwargs: None)
    previous = agent._execution_owner
    current = begin(agent)
    assert current != previous
    assert agent.tools["read_execution_output"].owner == current
    assert not any(owner == current for owner, _ in agent._execution_history._restored)
