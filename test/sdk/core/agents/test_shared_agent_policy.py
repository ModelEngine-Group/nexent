# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared behavior ownership and Core-specific delegation protocol regressions."""

import ast
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.context.models import ContextItemInput, ContextItemType
from nexent.core.agents.cores.jiuwen.delegation import (
    DelegationPolicy as JiuwenDelegation,
)
from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
from nexent.core.agents.cores.smolagents.delegation import (
    DelegationPolicy as SmolagentsDelegation,
)
from nexent.core.agents.cores.smolagents.output_protocol import (
    ModelOutputProtocolExhaustedError,
)
from nexent.core.agents.orchestration.delegation import (
    DelegationError,
    DelegationPolicy,
)
from nexent.core.agents.prompt.policies import (
    COMMON_BEHAVIOR_GUIDANCE,
    business_system_instructions,
    with_common_behavior,
)
from nexent.core.agents.resources.subagents import SubAgentToolWrapper
from nexent.core.prompts import load_prompt


def worker(name="writer"):
    return SimpleNamespace(name=name, invocation_name=None, display_name="文件生成助手")


@pytest.mark.parametrize("factory", [DelegationPolicy, JiuwenDelegation, SmolagentsDelegation])
@pytest.mark.parametrize(
    "query,required",
    [
        ("调用子智能体，生成docx", True),
        ("请调用文件生成助手生成文档", True),
        ("Can you please call the subagent to create a docx", True),
        ("Don't call the subagent", False),
        ("你支持调用子智能体吗？", False),
        ('Explain "call the subagent"', False),
        ("只总结上轮的文件名", False),
        ("生成一个文档", False),
    ],
)
def test_shared_intent_state_and_single_correction(factory, query, required):
    policy = factory(query, [worker()])
    assert isinstance(policy, DelegationPolicy)
    assert policy.required is required
    assert policy.pending is required
    assert policy.allow_correction()
    assert not policy.allow_correction()
    policy.record_dispatch("unbound")
    assert policy.pending is required
    policy.record_dispatch("writer")
    assert not policy.pending
    assert factory(query, [worker()]).pending is required


@pytest.mark.parametrize("names", [[], ["upload_to_s3"], ["writer", "upload_to_s3"]])
def test_common_target_contract_rejects_bypass_without_mutating_state(names):
    policy = DelegationPolicy("调用子智能体", [worker()])
    with pytest.raises(DelegationError, match="DELEGATION_REQUIRED"):
        policy.validate_targets(names)
    assert policy.pending
    policy.validate_targets(["writer"])
    assert policy.pending


def smolagent():
    agent = object.__new__(CoreAgent)
    agent._delegation = SmolagentsDelegation("调用子智能体", [worker()])
    agent._use_structured_outputs_internally = False
    return agent


@pytest.mark.parametrize(
    "response",
    [
        "<final_answer>File generated</final_answer>",
        "File generated",
        "<code>open('file.docx', 'w').write('bypass')</code>",
        "<code>upload_to_s3(file_path='file.docx')</code>",
        "<code>print = eval\nprint('bypass')\nwriter(task='Create')</code>",
        "<code>writer(task='Create')</code><final_answer>Done</final_answer>",
        "<code>writer = print\nwriter('fake')</code>",
        "<code>import os\nwriter(task='Create')</code>",
    ],
)
def test_smolagents_complete_response_gate_precedes_final_and_side_effect_branches(response):
    agent = smolagent()
    with pytest.raises(DelegationError, match="DELEGATION_REQUIRED"):
        agent._validate_delegation_output(response)
    assert agent._delegation.pending


@pytest.mark.parametrize("structured", [False, True])
def test_smolagents_proposal_is_not_dispatch_and_success_unlocks_followup(structured):
    agent = smolagent()
    agent._use_structured_outputs_internally = structured
    agent.code_block_tags = ("<code>", "</code>")
    code = "result = writer(task='Create a document')\nprint(result)"
    response = json.dumps({"code": code}) if structured else f"<code>{code}</code>"
    agent._validate_delegation_output(response)
    assert agent._delegation.pending
    agent._delegation.record_dispatch("writer")
    agent._validate_delegation_output("<final_answer>Actual worker result</final_answer>")


@pytest.mark.parametrize("repeat_bypass", [False, True])
def test_smolagents_run_loop_corrects_once_and_stops_repeated_bypass(repeat_bypass):
    from smolagents.agents import ActionOutput
    from smolagents.memory import FinalAnswerStep

    agent = smolagent()
    agent.enable_planning = False
    agent.stop_event = threading.Event()
    agent.logger = Mock()
    agent.final_answer_checks = []
    agent.memory = SimpleNamespace(steps=[])
    agent._resolve_deferred_model_attempt = Mock()
    agent._finalize_step = Mock()
    agent._collect_step_metrics = Mock()
    agent._record_output_protocol = Mock()
    agent._cleanup_plan = Mock()
    calls = []

    def step(memory_step):
        calls.append(memory_step.step_number)
        if len(calls) == 1 or repeat_bypass:
            raise DelegationError("DELEGATION_REQUIRED")
        assert agent._protocol_repair_messages
        agent._delegation.record_dispatch("writer")
        yield ActionOutput(output="Verified worker result", is_final_answer=True)

    agent._step_stream = step
    if repeat_bypass:
        with pytest.raises(ModelOutputProtocolExhaustedError, match="DELEGATION_REQUIRED"):
            list(agent._run_stream("Call the subagent", 5))
        assert agent.memory.steps == []
    else:
        output = list(agent._run_stream("Call the subagent", 5))
        assert isinstance(output[-1], FinalAnswerStep)
        assert len(agent.memory.steps) == 1
    assert calls == [1, 1]
    assert agent._delegation.corrections == 1


@pytest.mark.parametrize("forward", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_actual_shared_resource_wrapper_records_success_only(forward, fails):
    policy = DelegationPolicy("调用子智能体", [worker()])
    target = Mock(side_effect=RuntimeError("Worker failed")) if fails else Mock(return_value="Saved file")
    inner = SimpleNamespace(name="writer", forward=target)
    wrapper = SubAgentToolWrapper(inner, Mock())
    wrapper._on_success = policy.record_dispatch
    assert not hasattr(inner, "_on_success")
    invoke = wrapper.forward if forward else lambda **kwargs: wrapper._invoke(target, (), kwargs)
    if fails:
        with pytest.raises(RuntimeError, match="Worker failed"):
            invoke(task="Generate")
    else:
        assert invoke(task="Generate") == "Saved file"
    target.assert_called_once_with(task="Generate")
    assert policy.pending is fails


def item(item_id, text):
    return ContextItemInput(id=item_id, type=ContextItemType.SYSTEM, content={"text": text})


def test_shared_business_projection_preserves_custom_policy_and_excludes_execution_protocol():
    inputs = [
        item("system:duty", "Saved business duty"),
        item("system:manager_orchestration", "Common collaboration"),
        item("system:custom_policy", "Authorized custom policy"),
        item("system:execution_flow", "CodeAgent execution syntax"),
        item("system:code_norms", "CodeAgent code norms"),
        item("system:final_answer_guidance", "CodeAgent final syntax"),
    ]
    projected = business_system_instructions("Saved instructions", inputs)
    assert projected[:4] == [
        "Saved instructions", "Saved business duty", "Common collaboration", "Authorized custom policy",
    ]
    assert projected[-1].startswith(COMMON_BEHAVIOR_GUIDANCE)
    assert "reference_mark" in projected[-1]
    assert "CodeAgent" not in "\n".join(projected)
    assert len(inputs) == 6
    twice = with_common_behavior(with_common_behavior(inputs))
    assert sum(i.id == "system:common_behavior" for i in twice) == 1


def test_shared_policy_has_no_core_imports_or_execution_tags():
    root = Path(__file__).resolve().parents[4] / "sdk/nexent/core/agents"
    for relative in ["prompt/policies.py", "orchestration/delegation.py"]:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert ".cores." not in (node.module or "")
                assert not (node.module or "").startswith(("smolagents", "openjiuwen"))
    for forbidden in ["<code>", "<final_answer>", "nexent_execute_python", "nexent_execute_block"]:
        assert forbidden not in COMMON_BEHAVIOR_GUIDANCE
    for core in ["jiuwen", "smolagents"]:
        source = (root / f"cores/{core}/delegation.py").read_text(encoding="utf-8")
        assert "_ACTION" not in source and "_NEGATIVE" not in source


@pytest.mark.parametrize("language", ["zh", "en"])
def test_both_roles_share_response_style_without_copying_execution_protocol(language):
    from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer

    style = load_prompt(language, "agent/response_style")["policy"]
    assert "reference_mark" in style and "s3://" in style
    assert "<final_answer>" not in style and "<code>" not in style
    for role in ["manager", "managed"]:
        composer = AgentPromptComposer(AgentPromptBundle.from_resource(role=role, language=language))
        inputs = composer.compose_context_inputs(
            prompt="Saved duty", language=language, is_manager=role == "manager",
        )
        common = next(i for i in inputs if i.id == "system:common_behavior")
        assert common.content["text"].count(style) == 1
        protocol = composer.render_system_section("final_answer_guidance")
        assert "<final_answer>" in protocol and "reference_mark" not in protocol
        projected = "\n".join(business_system_instructions("User prompt", inputs, language))
        assert "Nexent" in projected and "Saved duty" in projected
        assert style in projected
        assert "<final_answer>" not in projected


@pytest.mark.parametrize("factory", [DelegationPolicy, JiuwenDelegation, SmolagentsDelegation])
def test_non_executing_prompt_consumers_do_not_treat_configuration_text_as_dispatch(factory):
    policy = factory("创建一个调用子智能体的智能体", [], enabled=False)
    assert not policy.pending and not policy.required and policy.instruction == ""
