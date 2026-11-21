# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""EO-01..03: a real CoreAgent.run must keep grants and readers on its fresh owner."""

import json
from copy import deepcopy

import pytest
from smolagents.agents import EMPTY_PROMPT_TEMPLATES
from smolagents.models import Model

from nexent.core.agents.context import ContextItemInput, ContextManager
from nexent.core.agents.context.execution_history import ExecutionHistory, result_text
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
from nexent.core.utils.observer import MessageObserver


class NoInference(Model):
    def generate(self, *args, **kwargs):
        raise AssertionError("Owner initialization must not dispatch a model")


def historical_turn(message=98):
    fields = {
        "STDOUT": "SOURCE_ALPHA\n",
        "OUTPUT": json.dumps({"rows": [{"id": "row-1", "amount": 10}]}),
    }
    action = {
        "schema_version": 1,
        "agent_core": "smolagents",
        "step_number": 1,
        "dispatch_state": "dispatched",
        "tool_calls": [
            {
                "id": "call_1",
                "name": "python_interpreter",
                "arguments": "print(source())",
            }
        ],
    }
    return ContextItemInput(
        id=f"turn:{message}",
        type="conversation_turn",
        content={
            "user_message_id": message - 1,
            "assistant_message_id": message,
            "user_message": "Original task",
            "assistant_final_answer": "Source saved",
            "execution_records": [
                {
                    "record_type": "tool",
                    "unit_index": 5,
                    "content": "source call",
                    "tool_call_id": "local-source",
                    "invocation_id": None,
                },
                {
                    "record_type": "execution_logs",
                    "unit_index": 6,
                    "content": "SOURCE_ALPHA",
                    "tool_call_id": None,
                    "invocation_id": None,
                },
                {
                    "record_type": "execution_result",
                    "unit_index": 7,
                    "content": json.dumps(
                        {
                            "content": result_text(fields),
                            "model_action": action,
                            "covered_unit_indices": [5, 6],
                        }
                    ),
                    "tool_call_id": None,
                    "invocation_id": None,
                },
            ],
        },
    )


def make_agent(items=None, *, history=True):
    observer = MessageObserver(lang="en")
    if history:
        observer.execution_history = ExecutionHistory()
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
    assert reader.owner == runtime.context_manager.config.execution_owner == first_owner
    sources = agent._execution_history.authorized_sources(first_owner)
    assert {source.source_kind for source in sources} == {
        "user_message",
        "execution_result",
    }
    result = json.loads(reader.forward("message:98/unit-index:7", 0, 16000))
    assert result["text"] == next(
        source.text for source in sources if source.source_kind == "execution_result"
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
    assert reader.owner == runtime.context_manager.config.execution_owner == current
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


def checkpoint_with_proof():
    from nexent.core.agents.context.action_history import register_authorized_sources

    turn = historical_turn()
    record = deepcopy(turn.content["execution_records"][-1])
    raw = json.dumps(
        [{"id": f"row-{i}", "detail": "original row data " * 20} for i in range(20)]
    )
    record["content"] = json.dumps({"content": result_text({"OUTPUT": raw})})
    checkpoint = ContextItemInput(
        id="checkpoint",
        type="history_summary",
        content={
            "summary": "Source saved",
            "covered_through_message_id": 98,
            "execution_sources": [
                {"message_id": 98, "unit_index": 7, "content": record["content"]}
            ],
        },
    )
    store = ExecutionHistory()
    register_authorized_sources([checkpoint], store, "checkpoint-writer")
    checkpoint.content["structured_source_proofs"] = list(
        store.structured_source_index("checkpoint-writer").collections.values()
    )
    assert checkpoint.content["structured_source_proofs"]
    return checkpoint


def test_cold_checkpoint_proof_survives_first_and_reused_actual_run():
    checkpoint = checkpoint_with_proof()
    agent, runtime = make_agent([checkpoint])
    for _ in range(2):
        owner = begin(agent)
        assert runtime.context_manager.config.execution_owner == owner
        index = agent._execution_history.structured_source_index(owner)
        assert (
            list(index.collections.values())
            == checkpoint.content["structured_source_proofs"]
        )
        assert (
            "row-1"
            in json.loads(
                agent.tools["read_execution_output"].forward("message:98/unit-index:7")
            )["text"]
        )


@pytest.mark.parametrize("failure", ["proof", "conflict", "invalid_provenance"])
def test_invalid_current_snapshot_does_not_publish_a_half_rotated_owner(failure):
    agent, runtime = make_agent()
    previous = begin(agent)
    checkpoint = checkpoint_with_proof()
    if failure == "proof":
        checkpoint.content["structured_source_proofs"][0]["source_ref"] = (
            "message:999/unit-index:7"
        )
        items = [checkpoint]
    elif failure == "conflict":
        duplicate = deepcopy(checkpoint.content["execution_sources"][0])
        duplicate["content"] = json.dumps(
            {"content": result_text({"STDOUT": "conflicting"})}
        )
        checkpoint.content["execution_sources"].append(duplicate)
        items = [checkpoint]
    else:
        checkpoint.content["execution_sources"][0]["content"] = "{}"
        items = [checkpoint]
    runtime.replace_items(items)
    original_items = runtime.items
    with pytest.raises((ValueError, PermissionError)):
        begin(agent)
    assert agent._execution_owner == previous
    assert agent.tools["read_execution_output"].owner == previous
    assert runtime.context_manager.config.execution_owner == previous
    assert runtime.items is original_items
    assert (
        "SOURCE_ALPHA"
        in json.loads(
            agent.tools["read_execution_output"].forward("message:98/unit-index:7")
        )["text"]
    )


def test_runtime_without_context_manager_keeps_fresh_reader_owner_compatibility():
    from types import SimpleNamespace

    agent, _ = make_agent()
    agent.context_runtime = SimpleNamespace(prepare_run=lambda **kwargs: None)
    previous = agent._execution_owner
    current = begin(agent)
    assert current != previous
    assert agent.tools["read_execution_output"].owner == current
    assert agent._execution_history.authorized_sources(current) == ()
