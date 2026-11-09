# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Acceptance-derived native protocol unit tests; live proof is separate."""

import json
from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import pytest
from nexent.core.agents.native_runtime import (
    CodeExecutionTool,
    NativeToolCallingAgent,
    collect_native_stream,
)
from nexent.core.concurrency.cancellation import RunTerminated
from smolagents.models import ChatMessage, Model
from smolagents.tools import Tool


class EchoTool(Tool):
    name = "echo"
    description = "Return text."
    inputs = {"text": {"type": "string", "description": "Text to return."}}
    output_type = "string"

    def forward(self, text: str) -> str:
        return text


class ScriptedModel(Model):
    def __init__(self, responses):
        super().__init__()
        self.responses = iter(responses)
        self.requests = []

    def generate(self, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        wire = next(self.responses)
        message = ChatMessage.from_dict(deepcopy(wire))
        message.raw = wire
        return message


def call(identifier, name="echo", arguments='{"text":"hello"}'):
    return {
        "id": identifier,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def agent_for(responses):
    model = ScriptedModel(responses)
    return NativeToolCallingAgent(
        tools=[EchoTool()], model=model, verbosity_level=0
    ), model


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

    wire, usage = collect_native_stream(
        [
            chunk(content="Visible", reasoning="reasoning metadata"),
            chunk(calls=[fragment(1, "b", "echo", '{"text":')]),
            chunk(calls=[fragment(0, "a", "echo", '{"text":"first"}')]),
            chunk(calls=[fragment(1, arguments='"second"}')]),
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


def test_ac007_selected_context_preserves_native_exchange_groups():
    from nexent.core.agents.context import (
        ContextItemInput,
        ContextManager,
        ContextManagerConfig,
        ManagedContextRuntime,
    )

    agent, model = agent_for(
        [
            {"role": "assistant", "tool_calls": [call("a")]},
            {"role": "assistant", "content": "Done"},
        ]
    )
    agent.context_runtime = ManagedContextRuntime(
        ContextManager(ContextManagerConfig()),
        items=[
            ContextItemInput(
                id="system:custom",
                type="system",
                content={"text": "Retain this instruction."},
            )
        ],
    )
    assert str(agent.run("Proceed")) == "Done"
    second = model.requests[1]
    assert "Retain this instruction." in str(second)
    assert second[-2]["tool_calls"][0]["id"] == second[-1]["tool_call_id"] == "a"


def guarded_agent(responses, tool=None, executor=None):
    from nexent.core.agents.agent_model import (
        AgentVerificationConfig,
        GuardrailConfig,
        GuardrailRule,
    )

    model = ScriptedModel(responses)
    agent = NativeToolCallingAgent(
        tools=[tool or EchoTool()],
        model=model,
        executor=executor,
        verbosity_level=0,
        verification_config=AgentVerificationConfig(
            guardrail_config=GuardrailConfig(
                enabled=True,
                rules=[
                    GuardrailRule(name="blocked", pattern="forbidden", severity="block")
                ],
            )
        ),
    )
    return agent, model


def test_ac007_guardrail_input_terminates_before_model():
    agent, model = guarded_agent([])
    answer = str(agent.run("forbidden"))
    assert answer
    assert model.requests == []


@pytest.mark.parametrize("include_following_call", [False, True])
def test_ac007_guardrail_blocks_tool_without_side_effect(include_following_call):
    tool = EchoTool()
    effects = []
    tool.forward = lambda text: effects.append(text) or text
    agent, model = guarded_agent(
        [
            {
                "role": "assistant",
                "tool_calls": [call("blocked", arguments='{"text":"forbidden"}')]
                + (
                    [call("unexecuted", arguments='{"text":"safe"}')]
                    if include_following_call
                    else []
                ),
            },
        ],
        tool=tool,
    )
    assert str(agent.run("Use tool"))
    assert effects == []
    assert len(model.requests) == 1
    results = [
        message for message in agent.native_messages if message["role"] == "tool"
    ]
    assert [message["tool_call_id"] for message in results] == (
        ["blocked", "unexecuted"] if include_following_call else ["blocked"]
    )


def test_ac007_guardrail_checks_resolved_programmatic_arguments():
    from smolagents.local_python_executor import LocalPythonExecutor

    tool = EchoTool()
    effects = []
    tool.forward = lambda text: effects.append(text) or text
    code = 'value = "for" + "bidden"; print(echo(text=value))'
    agent, model = guarded_agent(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    call("programmatic", "code_execution", json.dumps({"code": code}))
                ],
            },
        ],
        tool=tool,
        executor=LocalPythonExecutor(additional_authorized_imports=[]),
    )
    assert str(agent.run("Use code"))
    assert effects == []
    assert len(model.requests) == 1


def test_ac007_final_verification_rejects_and_repairs_candidate():
    from nexent.core.agents.agent_model import AgentVerificationConfig

    model = ScriptedModel(
        [
            {"role": "assistant", "content": "{{TODO}}"},
            {"role": "assistant", "content": "Hello."},
        ]
    )
    agent = NativeToolCallingAgent(
        tools=[],
        model=model,
        verbosity_level=0,
        verification_config=AgentVerificationConfig(
            enabled=True, llm_verification_enabled=False
        ),
    )
    assert str(agent.run("Hi")) == "Hello."
    assert len(model.requests) == 2
    assert "Verification feedback" in model.requests[1][-1]["content"]


@pytest.mark.parametrize("terminal", ["content", "tool"])
def test_ac007_plan_tools_use_existing_callbacks_and_persistence(terminal):
    from nexent.core.tools.plan_tools import CreatePlanTool

    tool = CreatePlanTool(
        observer=None,
        plan_repo=None,
        on_plan_created=None,
        get_conversation_id=None,
        get_user_id=None,
    )
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    call(
                        "plan",
                        "create_plan",
                        json.dumps(
                            {
                                "title": "Task",
                                "steps": [
                                    {"id": str(index), "title": "Step"}
                                    for index in range(3)
                                ],
                            }
                        ),
                    )
                ],
            },
            (
                {"role": "assistant", "content": "Plan created."}
                if terminal == "content"
                else {
                    "role": "assistant",
                    "tool_calls": [
                        call("final-plan", "final_answer", '{"answer":"Plan created."}')
                    ],
                }
            ),
        ]
    )
    agent = NativeToolCallingAgent(
        tools=[tool], model=model, enable_planning=True, verbosity_level=0
    )
    tool.plan_repo = agent.plan_repo
    tool._on_plan_created = agent._on_plan_created
    tool._get_conversation_id = agent._get_conversation_id
    tool._get_user_id = agent._get_user_id
    assert str(agent.run("Create plan")) == "Plan created."
    assert agent.current_plan.title == "Task"
    assert (
        agent.plan_repo.load(conversation_id=0, user_id="anonymous")["title"] == "Task"
    )


def test_ac007_clarification_uses_validated_terminal_form():
    from nexent.core.utils.observer import ProcessType

    events = []
    observer = SimpleNamespace(add_message=lambda *args, **kwargs: events.append(args))
    question = {
        "id": "topic",
        "type": "text",
        "title": "Which topic?",
        "required": True,
    }
    model = ScriptedModel(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    call("clarify", "ask_user", json.dumps({"questions": [question]}))
                ],
            },
        ]
    )
    agent = NativeToolCallingAgent(
        tools=[],
        model=model,
        observer=observer,
        enable_clarification=True,
        verbosity_level=0,
    )
    assert "Which topic?" in str(agent.run("Clarify"))
    assert len(model.requests) == 1
    forms = [event[2] for event in events if event[1] == ProcessType.HUMAN_INTERACTION]
    assert forms[0]["schema_version"] == 1
    assert forms[0]["questions"][0]["id"] == "topic"
    assert "<code>" not in agent.system_prompt


def test_ac007_prompt_adapter_changes_only_catalog_runtime_conventions():
    from nexent.core.agents.context import ContextItemInput
    from nexent.core.agents.native_runtime import adapt_native_context_items

    flow = ContextItemInput(
        id="system:execution_flow",
        type="system",
        content={"text": "Think: <code>action</code>"},
        source=("agent_prompt:execution_flow",),
        metadata={"authority": "platform"},
    )
    authored = ContextItemInput(
        id="system:duty",
        type="system",
        content={"text": "Explain <code> examples to users."},
        source=("agent_prompt:duty",),
        metadata={"authority": "agent"},
    )
    answer = ContextItemInput(
        id="system:final_answer_guidance",
        type="system",
        content={"text": "Use <final_answer>.\n\nKeep citations and file security."},
        source=("agent_prompt:final_answer_guidance",),
        metadata={"authority": "platform"},
    )
    result = adapt_native_context_items([flow, authored, answer], enable_planning=True)
    assert "<code>" not in result[0].content["text"]
    assert "create_plan" in result[0].content["text"]
    assert result[1] is authored
    assert "Keep citations and file security." in result[2].content["text"]
    assert flow.content["text"] == "Think: <code>action</code>"


def test_ac001_existing_definition_constructs_native_runtime_without_mutation(mocker):
    from nexent.core.agents.agent_model import AgentConfig
    from nexent.core.agents.nexent_agent import NexentAgent
    from nexent.core.utils.observer import MessageObserver

    observer = MessageObserver(lang="en")
    factory = NexentAgent(observer, [], Event(), agent_runtime="toolcalling")
    model = ScriptedModel([{"role": "assistant", "content": "Definition retained."}])
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


def test_ac007_guardrail_termination_emits_existing_verification_event():
    from nexent.core.agents.agent_model import (
        AgentVerificationConfig,
        GuardrailConfig,
        GuardrailRule,
    )
    from nexent.core.utils.observer import MessageObserver

    observer = MessageObserver(lang="en")
    model = ScriptedModel([])
    agent = NativeToolCallingAgent(
        tools=[],
        model=model,
        observer=observer,
        verbosity_level=0,
        verification_config=AgentVerificationConfig(
            enabled=True,
            guardrail_config=GuardrailConfig(
                enabled=True,
                rules=[
                    GuardrailRule(name="blocked", pattern="forbidden", severity="block")
                ],
            ),
        ),
    )
    agent.run("forbidden")
    events = [json.loads(value) for value in observer.get_cached_message()]
    assert any(event["type"] == "verification" for event in events)
    assert not model.requests


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
    wire, _ = collect_native_stream([packet(header), packet(body)], Event())
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


def test_ac007_context_overflow_fails_before_provider_and_keeps_native_history():
    from nexent.core.agents.context import (
        ContextManager,
        ContextManagerConfig,
        ManagedContextRuntime,
    )

    agent, model = agent_for([])
    agent.context_runtime = ManagedContextRuntime(
        ContextManager(
            ContextManagerConfig(
                context_window_tokens=10,
                effective_input_limit_tokens=1,
                token_threshold=1,
            )
        )
    )
    with pytest.raises(ValueError, match="Native context exceeds"):
        agent.run("A task which cannot fit the authorized one-token input limit")
    assert model.requests == []
    assert agent.native_messages[-1]["role"] == "user"


def test_ac007_prompt_adapter_rejects_unknown_owned_final_layout_and_adapts_code_norms():
    from nexent.core.agents.context import ContextItemInput
    from nexent.core.agents.native_runtime import adapt_native_context_items

    def owned(section, text):
        return ContextItemInput(
            id="system:" + section,
            type="system",
            content={"text": text},
            source=("agent_prompt:" + section,),
            metadata={"authority": "platform"},
        )

    items = adapt_native_context_items(
        [owned("execution_flow", "old"), owned("code_norms", "old")]
    )
    assert "native tool calls" in items[0].content["text"]
    assert "prebound" in items[1].content["text"]
    with pytest.raises(ValueError, match="Unknown catalog final-answer guidance"):
        adapt_native_context_items(
            [
                owned(
                    "final_answer_guidance",
                    "Unrecognized policy without a semantic paragraph",
                )
            ]
        )


def test_ac007_final_verification_budget_returns_controlled_failure():
    from nexent.core.agents.agent_model import AgentVerificationConfig

    model = ScriptedModel([{"role": "assistant", "content": "{{TODO}}"}])
    agent = NativeToolCallingAgent(
        tools=[],
        model=model,
        verbosity_level=0,
        verification_config=AgentVerificationConfig(
            enabled=True, llm_verification_enabled=False, max_final_rounds=1
        ),
    )
    output = str(agent.run("Answer"))
    assert "TODO" not in output
    assert "自验证" in output
    assert len(model.requests) == 1


@pytest.mark.parametrize("checkpoint", ["input", "arguments", "output"])
def test_ac007_guardrail_masking_preserves_execution_but_redacts_boundary(checkpoint):
    from nexent.core.agents.agent_model import (
        AgentVerificationConfig,
        GuardrailConfig,
        GuardrailRule,
    )

    seen = []
    tool = EchoTool()

    def forward(text):
        seen.append(text)
        return "sensitive output" if checkpoint == "output" else text

    tool.forward = forward
    responses = (
        [{"role": "assistant", "content": "Done"}]
        if checkpoint == "input"
        else [
            {
                "role": "assistant",
                "tool_calls": [
                    call(
                        "mask",
                        arguments=json.dumps(
                            {
                                "text": "sensitive"
                                if checkpoint == "arguments"
                                else "safe"
                            }
                        ),
                    )
                ],
            },
            {"role": "assistant", "content": "Done"},
        ]
    )
    model = ScriptedModel(responses)
    agent = NativeToolCallingAgent(
        tools=[tool],
        model=model,
        verbosity_level=0,
        verification_config=AgentVerificationConfig(
            guardrail_config=GuardrailConfig(
                enabled=True,
                rules=[
                    GuardrailRule(name="redact", pattern="sensitive", severity="mask")
                ],
            )
        ),
    )
    assert str(agent.run("sensitive" if checkpoint == "input" else "Proceed")) == "Done"
    if checkpoint == "input":
        assert "sensitive" not in model.requests[0][-1]["content"]
    else:
        if checkpoint == "arguments":
            assert seen and "sensitive" not in seen[0]
        assert "sensitive" not in model.requests[1][-1]["content"]


def test_ac007_error_observation_includes_verifier_repair_feedback():
    from nexent.core.agents.agent_model import AgentVerificationConfig

    tool = EchoTool()
    tool.forward = lambda text: "Error: resource unavailable"
    model = ScriptedModel(
        [
            {"role": "assistant", "tool_calls": [call("error")]},
            {"role": "assistant", "content": "Reported failure."},
        ]
    )
    agent = NativeToolCallingAgent(
        tools=[tool],
        model=model,
        verbosity_level=0,
        verification_config=AgentVerificationConfig(
            enabled=True,
            llm_verification_enabled=False,
            final_verification_enabled=False,
            strictness="strict",
        ),
    )
    assert str(agent.run("Use the tool")) == "Reported failure."
    assert "Verification feedback" in model.requests[1][-1]["content"]


def test_ac007_headless_clarification_keeps_terminal_question_text():
    from nexent.core.agents.native_runtime import NativeClarificationTool

    tool = NativeClarificationTool("ask_user", None)
    assert "Which topic?" in tool.forward(
        [{"id": "topic", "type": "text", "title": "Which topic?", "required": True}]
    )
