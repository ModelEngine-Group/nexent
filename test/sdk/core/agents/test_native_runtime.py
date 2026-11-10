# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Acceptance-derived native protocol unit tests; live proof is separate."""

from threading import Event
from types import SimpleNamespace

import pytest
from native_runtime_fixtures import EchoTool, ScriptedModel, agent_for, call
from nexent.core.agents.native_runtime import (
    CodeExecutionTool,
    NativeToolCallingAgent,
    collect_native_stream,
)
from nexent.core.concurrency.cancellation import RunTerminated


def test_ac002_native_direct_call_and_content_final():
    agent, model = agent_for(
        [
            {"role": "assistant", "content": "Checking", "tool_calls": [call("a")]},
            {"role": "assistant", "content": "hello"},
        ]
    )
    assert str(agent.run("Echo hello")) == "hello"
    history = model.requests[1]
    assert all(
        message["role"] in {"system", "user", "assistant", "tool"}
        for message in history
    )
    assert history[-2]["tool_calls"][0]["id"] == "a"
    assert history[-2]["content"] == "Checking"
    assert history[-1] == {"role": "tool", "tool_call_id": "a", "content": "hello"}
    assert not any("Calling tools:" in str(message) for message in history)



def test_ac005_native_arguments_cannot_resolve_private_state_by_name():
    agent, model = agent_for(
        [
            {"role": "assistant", "tool_calls": [call("literal")]},
            {"role": "assistant", "content": "Done"},
        ]
    )
    agent.state["hello"] = "private runtime value"
    assert str(agent.run("Echo", reset=False)) == "Done"
    assert model.requests[1][-1]["content"] == "hello"



def test_ac003_multiple_calls_and_correlated_error_recovery():
    agent, model = agent_for(
        [
            {
                "role": "assistant",
                "tool_calls": [call("a"), call("b", name="unauthorized")],
            },
            {"role": "assistant", "content": "Recovered"},
        ]
    )
    assert str(agent.run("Try tools")) == "Recovered"
    results = model.requests[1][-2:]
    assert [result["tool_call_id"] for result in results] == ["a", "b"]
    assert results[0]["content"] == "hello"
    assert "Unknown tool" in results[1]["content"]



@pytest.mark.parametrize("arguments", ["{bad", "[]", '{"text":123}'])
def test_ac008_invalid_arguments_are_correlated_observations(arguments):
    agent, model = agent_for(
        [
            {"role": "assistant", "tool_calls": [call("invalid", arguments=arguments)]},
            {"role": "assistant", "content": "Handled"},
        ]
    )
    assert str(agent.run("Validate")) == "Handled"
    assert model.requests[1][-1]["tool_call_id"] == "invalid"
    assert "Tool execution failed" in model.requests[1][-1]["content"]



def test_ac004_code_execution_delegates_and_cancellation():
    calls = []

    def executor(code):
        calls.append(code)
        return "result"

    stop = Event()
    tool = CodeExecutionTool(executor, stop)
    assert tool.forward("print(1)") == "result"
    assert calls == ["print(1)"]
    stop.set()
    with pytest.raises(RunTerminated):
        tool.forward("print(2)")
    assert calls == ["print(1)"]



def test_ac001_factory_defaults_preserve_legacy_constructor(mocker):
    from nexent.core.agents.runtime_factory import create_agent_runtime

    legacy = mocker.patch("nexent.core.agents.runtime_factory.CoreAgent")
    assert create_agent_runtime(tools=[], model="configured") is legacy.return_value
    legacy.assert_called_once_with(tools=[], model="configured")
    with pytest.raises(ValueError, match="NEXENT_AGENT_RUNTIME"):
        create_agent_runtime("invalid", tools=[], model="configured")
    assert legacy.call_count == 1



def test_ac004_stateful_restricted_executor_and_tool_orchestration():
    from smolagents.local_python_executor import LocalPythonExecutor

    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    call(
                        "a",
                        "code_execution",
                        '{"code":"counter = 40; print(echo(text=str(counter)))"}',
                    )
                ],
            },
            {
                "role": "assistant",
                "tool_calls": [
                    call(
                        "b", "code_execution", '{"code":"counter += 2; print(counter)"}'
                    )
                ],
            },
            {"role": "assistant", "content": "42"},
        ]
    )
    agent = NativeToolCallingAgent(
        tools=[EchoTool()],
        model=model,
        executor=LocalPythonExecutor(additional_authorized_imports=[]),
        verbosity_level=0,
    )
    assert str(agent.run("Compute")) == "42"
    assert "40" in model.requests[1][-1]["content"]
    assert "42" in model.requests[2][-1]["content"]



@pytest.mark.parametrize("reserved", ["code_execution", "final_answer"])
def test_ac005_reserved_name_cannot_shadow_runtime_tool(reserved):
    tool = EchoTool()
    tool.name = reserved
    with pytest.raises(ValueError, match="reserved"):
        NativeToolCallingAgent(tools=[tool], model=ScriptedModel([]))



def test_ac008_max_steps_does_not_make_unbudgeted_final_request():
    from smolagents.utils import AgentMaxStepsError

    agent, model = agent_for(
        [
            {"role": "assistant", "tool_calls": [call("a")]},
        ]
    )
    with pytest.raises(AgentMaxStepsError):
        agent.run("Repeat", max_steps=1)
    assert len(model.requests) == 1



def test_ac008_cancellation_bypasses_tool_error_repair():
    agent, model = agent_for([])
    agent.stop_event.set()
    with pytest.raises(RunTerminated):
        agent.run("Cancelled")
    assert model.requests == []



def test_ac003_stream_fragments_preserve_reasoning_and_call_identity():
    def chunk(content=None, calls=None, reasoning=None):
        delta = SimpleNamespace(
            content=content, tool_calls=calls, reasoning_content=reasoning
        )
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    def fragment(index, identifier=None, name=None, arguments=None):
        return SimpleNamespace(
            index=index,
            id=identifier,
            function=SimpleNamespace(name=name, arguments=arguments),
        )

    wire, usage, finish_reason = collect_native_stream(
        [
            chunk(content="Visible", reasoning="reasoning metadata"),
            chunk(calls=[fragment(1, "b", "echo", '{"text":')]),
            chunk(calls=[fragment(0, "a", "echo", '{"text":"first"}')]),
            chunk(calls=[fragment(1, arguments='"second"}')]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None), finish_reason="tool_calls")], usage=None),
            SimpleNamespace(
                choices=[], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4)
            ),
        ],
        Event(),
    )
    assert wire["content"] == "Visible"
    assert wire["reasoning_content"] == "reasoning metadata"
    assert [call["id"] for call in wire["tool_calls"]] == ["a", "b"]
    assert wire["tool_calls"][1]["function"]["arguments"] == '{"text":"second"}'
    assert usage.completion_tokens == 4
    assert finish_reason == "tool_calls"



def test_ac001_existing_definition_constructs_native_runtime_without_mutation(mocker):
    from nexent.core.agents.agent_model import AgentConfig
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.utils.observer import MessageObserver

    observer = MessageObserver(lang="en")
    factory = NexentAgent(observer, [], Event(), agent_runtime="toolcalling")
    model = ScriptedModel([{"role": "assistant", "content": "Definition retained."}])
    model.profile = SimpleNamespace(
        capabilities=SimpleNamespace(tools=SimpleNamespace(status="supported")),
        model_dump=lambda **_: {"capabilities": {"tools": {"status": "supported"}}},
    )
    mocker.patch.object(factory, "create_model", return_value=model)
    definition = AgentConfig(
        name="existing",
        description="Existing definition",
        tools=[],
        model_name="test",
        instructions="Keep this instruction.",
    )
    before = definition.model_dump()
    agent = factory.create_single_agent(definition)
    assert isinstance(agent, NativeToolCallingAgent)
    assert "code_execution" in agent.tools
    assert "Keep this instruction." in agent.system_prompt
    assert definition.model_dump() == before
    factory.set_agent(agent)
    factory.add_history_to_agent([])
    factory.agent_run_with_observer("Hello", reset=False)
    assert len(model.requests) == 1



def test_ac004_native_run_registers_only_programmatic_tools_once(mocker):
    """MultiStepAgent must not send terminal/recursive tools to the sandbox."""
    from unittest.mock import Mock

    executor = Mock()
    model = ScriptedModel([{"role": "assistant", "content": "Done."}])
    agent = NativeToolCallingAgent(
        tools=[EchoTool()], model=model, executor=executor, verbosity_level=0
    )
    agent.run("Finish")
    assert executor.send_tools.call_count == 1
    assert set(executor.send_tools.call_args.args[0]) == {"echo"}



def test_ac001_runtime_identity_rejects_marker_impostors_and_accepts_legacy():
    from nexent.core.agents.core_agent import CoreAgent
    from nexent.core.agents.runtime_factory import is_runtime_agent

    legacy = CoreAgent(
        observer=None, tools=[], model=ScriptedModel([]), verbosity_level=0
    )
    assert is_runtime_agent(legacy)
    assert not is_runtime_agent(object())

    class Impostor:
        nexent_runtime_name = "toolcalling"

    assert not is_runtime_agent(Impostor())



@pytest.mark.parametrize("runtime", ["unknown", ""])
def test_ac001_sdk_factory_rejects_invalid_runtime_before_allocating(runtime):
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.utils.observer import MessageObserver

    with pytest.raises(ValueError, match="NEXENT_AGENT_RUNTIME"):
        NexentAgent(MessageObserver(lang="en"), [], Event(), agent_runtime=runtime)



@pytest.mark.parametrize("identifier", ["", "duplicate"])
def test_ac002_invalid_batch_ids_fail_before_any_tool_side_effect(identifier):
    effects = []
    tool = EchoTool()
    tool.forward = lambda text: effects.append(text) or text
    calls = (
        [call(identifier)] if not identifier else [call(identifier), call(identifier)]
    )
    model = ScriptedModel([{"role": "assistant", "tool_calls": calls}])
    agent = NativeToolCallingAgent(tools=[tool], model=model, verbosity_level=0)
    with pytest.raises(ValueError, match="unique nonempty identifiers"):
        agent.run("Execute")
    assert effects == []



def test_ac002_terminal_tool_in_batch_is_rejected_without_early_termination():
    agent, model = agent_for(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    call("terminal", "final_answer", '{"answer":"Premature"}'),
                    call("work"),
                ],
            },
            {"role": "assistant", "content": "Recovered"},
        ]
    )
    assert str(agent.run("Continue")) == "Recovered"
    results = [message for message in model.requests[1] if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in results] == ["terminal", "work"]
    assert "terminal tool must be the only call" in results[0]["content"]
    assert results[1]["content"] == "hello"



def test_ac002_empty_native_response_cannot_be_reported_as_success():
    agent, model = agent_for([{"role": "assistant", "content": ""}])
    with pytest.raises(ValueError, match="neither content nor tool calls"):
        agent.run("Answer")
    assert len(model.requests) == 1



def test_ac003_stream_requires_index_but_accepts_id_only_header_fragment():
    def packet(fragment):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=[fragment])
                )
            ],
            usage=None,
        )

    with pytest.raises(ValueError, match="requires an index"):
        collect_native_stream([packet(SimpleNamespace(index=None))], Event())
    header = SimpleNamespace(index=0, id="correlation", function=None)
    body = SimpleNamespace(
        index=0,
        id=None,
        function=SimpleNamespace(name="echo", arguments='{"text":"ok"}'),
    )
    wire, _, _ = collect_native_stream([packet(header), packet(body),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None),
                                                finish_reason="tool_calls")], usage=None)], Event())
    assert wire["tool_calls"] == [call("correlation", arguments='{"text":"ok"}')]



def test_ac008_cancelled_stream_collection_never_consumes_a_chunk():
    stop = Event()
    stop.set()
    with pytest.raises(RunTerminated):
        collect_native_stream([SimpleNamespace()], stop)



def test_ac005_duplicate_authorized_tool_names_fail_before_registration():
    with pytest.raises(ValueError, match="must be unique"):
        NativeToolCallingAgent(tools=[EchoTool(), EchoTool()], model=ScriptedModel([]))



def test_ac004_python_precheck_blocks_invalid_code_before_executor_side_effect():
    from nexent.core.agents.agent_model import AgentVerificationConfig
    from nexent.core.agents.verification import VerificationController

    effects = []
    tool = CodeExecutionTool(lambda code: effects.append(code), Event())
    tool.verification_controller = VerificationController(
        AgentVerificationConfig(enabled=True, llm_verification_enabled=False),
        None,
        "agent",
        ScriptedModel([]),
    )
    with pytest.raises(ValueError, match="Verification feedback"):
        tool.forward("def invalid(:")
    assert effects == []



def test_ac008_python_cancellation_after_execution_cannot_return_partial_output():
    stop = Event()

    def executor(code):
        stop.set()
        return "partial"

    with pytest.raises(RunTerminated):
        CodeExecutionTool(executor, stop).forward("print('partial')")
