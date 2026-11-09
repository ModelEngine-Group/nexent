# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Acceptance-derived native protocol unit tests; live proof is separate."""

import json
from types import SimpleNamespace

import pytest
from native_runtime_fixtures import EchoTool, ScriptedModel, agent_for, call, guarded_agent
from nexent.core.agents.native_runtime import (
    NativeToolCallingAgent,
)


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
                + ([call("unexecuted", arguments='{"text":"safe"}')] if include_following_call else []),
            },
        ],
        tool=tool,
    )
    assert str(agent.run("Use tool"))
    assert effects == []
    assert len(model.requests) == 1
    results = [message for message in agent.native_messages if message["role"] == "tool"]
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
                "tool_calls": [call("programmatic", "code_execution", json.dumps({"code": code}))],
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
        verification_config=AgentVerificationConfig(enabled=True, llm_verification_enabled=False),
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
                                "steps": [{"id": str(index), "title": "Step"} for index in range(3)],
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
                    "tool_calls": [call("final-plan", "final_answer", '{"answer":"Plan created."}')],
                }
            ),
        ]
    )
    agent = NativeToolCallingAgent(tools=[tool], model=model, enable_planning=True, verbosity_level=0)
    tool.plan_repo = agent.plan_repo
    tool._on_plan_created = agent._on_plan_created
    tool._get_conversation_id = agent._get_conversation_id
    tool._get_user_id = agent._get_user_id
    assert str(agent.run("Create plan")) == "Plan created."
    assert agent.current_plan.title == "Task"
    assert agent.plan_repo.load(conversation_id=0, user_id="anonymous")["title"] == "Task"


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
                "tool_calls": [call("clarify", "ask_user", json.dumps({"questions": [question]}))],
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
                rules=[GuardrailRule(name="blocked", pattern="forbidden", severity="block")],
            ),
        ),
    )
    agent.run("forbidden")
    events = [json.loads(value) for value in observer.get_cached_message()]
    assert any(event["type"] == "verification" for event in events)
    assert not model.requests


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

    items = adapt_native_context_items([owned("execution_flow", "old"), owned("code_norms", "old")])
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
        verification_config=AgentVerificationConfig(enabled=True, llm_verification_enabled=False, max_final_rounds=1),
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
                        arguments=json.dumps({"text": "sensitive" if checkpoint == "arguments" else "safe"}),
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
                rules=[GuardrailRule(name="redact", pattern="sensitive", severity="mask")],
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
    assert "Which topic?" in tool.forward([{"id": "topic", "type": "text", "title": "Which topic?", "required": True}])
