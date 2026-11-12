# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit delegation preserves common instructions and precedes side effects."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_jiuwen_model_service import completion, message, stream_service
from test_jiuwen_model_service import saved_profile as _saved_profile

from nexent.core.agents.context.models import ContextItemType
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.cores.jiuwen.delegation import DelegationPolicy
from nexent.core.agents.cores.jiuwen.messages import resource_view
from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, JiuwenProtocolError
from nexent.core.concurrency import RunCancellationScope
from nexent.core.model_service.contracts import AssistantMessage, ToolCall
from nexent.core.model_service.service import ModelServiceError
from nexent.core.utils.observer import MessageObserver


saved_profile = _saved_profile


def policy(query="调用子智能体，帮我生成一个docx文件"):
    return DelegationPolicy(
        query, [SimpleNamespace(name="writer", invocation_name="write_file", display_name="文件生成助手")]
    )


@pytest.mark.parametrize(
    "query",
    [
        "调用子智能体，生成docx",
        "请调用文件生成助手生成文件",
        "Call the subagent to make a file",
        "能否帮我调用子智能体生成文件",
        "Can you please call the subagent to create a file",
        "Delegate this task to the worker",
        "Please invoke write_file",
        "不要自己生成，请调用子智能体",
        "调用子智能体完成‘生成文件’",
    ],
)
def test_affirmative_current_delegation_is_required(query):
    assert policy(query).pending


@pytest.mark.parametrize(
    "query",
    [
        "生成一个docx文件",
        "不要调用子智能体，自己生成",
        "我不想调用子智能体",
        "你支持调用子智能体吗？",
        "能否调用子智能体？",
        "Can you call a subagent?",
        "Don't call the subagent",
        "解释如何调用子智能体",
        "为什么没有调用子智能体？",
        "解释“调用子智能体”是什么意思",
        "Explain how to use the worker",
        'Here is an example: "call the subagent"',
        "总结刚才的文件",
    ],
)
def test_negative_quoted_explanatory_and_ordinary_requests_do_not_force_delegation(query):
    assert not policy(query).required


def test_only_authorized_named_collaborator_can_satisfy_the_directive():
    other = SimpleNamespace(name="search", invocation_name=None, display_name="搜索助手")
    selected = DelegationPolicy(
        "请调用文件生成助手生成文件",
        [SimpleNamespace(name="writer", invocation_name="write_file", display_name="文件生成助手"), other],
    )
    assert selected.names == {"write_file"}
    view = resource_view(
        "Current",
        [{"name": name, "parameters": {"type": "object"}} for name in ["write_file", "search", "upload_to_s3"]],
    )
    constrained = selected.constrain(view)
    assert [tool.name for tool in constrained.tool_definitions] == ["write_file"]
    assert len(view.tool_definitions) == 3
    selected.record_dispatch("search")
    assert selected.pending
    with pytest.raises(JiuwenProtocolError, match="DELEGATION_REQUIRED"):
        selected.validate_calls([])
    selected.validate_calls([SimpleNamespace(name="write_file")])
    assert selected.pending
    selected.record_dispatch("write_file")
    assert not selected.pending and selected.constrain(view) is view


@pytest.mark.parametrize(
    "code", ["print(write_file(task='Make a docx'))", "result = write_file(task='Make a docx')\nprint(result)"]
)
def test_text_delegation_permits_direct_child_call_without_releasing_pending_state(code):
    selected = policy()
    selected.validate_calls([SimpleNamespace(name=EXECUTION_TOOL, arguments=json.dumps({"code": code}))])
    assert selected.pending


@pytest.mark.parametrize(
    "code",
    [
        "print('Created a file')",
        "open('x.docx', 'w').write('x')",
        "import os\nwrite_file(task='Create')",
        "upload_to_s3(file_path='x')\nwrite_file(task='Create')",
        "print = eval\nprint('dangerous')\nwrite_file(task='Create')",
        "write_file = print\nwrite_file('fake')",
        "getattr(write_file, 'forward')('task')",
        "for x in range(2):\n write_file(task='Create')",
        "write_file(**{'task':'Create'})",
    ],
)
def test_text_bypass_cannot_dispatch_python_or_root_side_effects(code):
    with pytest.raises(JiuwenProtocolError, match="DELEGATION_REQUIRED"):
        policy().validate_calls([SimpleNamespace(name=EXECUTION_TOOL, arguments=json.dumps({"code": code}))])


def test_missing_collaborator_is_explicit_and_new_run_does_not_inherit_dispatch():
    selected = DelegationPolicy("调用子智能体", [])
    with pytest.raises(JiuwenProtocolError, match="DELEGATION_UNAVAILABLE"):
        selected.constrain(resource_view("Current", []))
    previous = policy()
    previous.record_dispatch("write_file")
    assert policy().pending and not policy("只总结上轮结果").pending


@pytest.mark.parametrize("fails", [False, True])
async def test_only_completed_actual_child_entry_releases_delegation(fails):
    child = SimpleNamespace(name="write_file", invocation_name=None, display_name=None)
    adapter = JiuwenAdapter(
        SimpleNamespace(
            query="调用子智能体",
            observer=MessageObserver(lang="en"),
            agent_config=SimpleNamespace(name="parent", worker_agents=[child]),
        )
    )
    adapter.scope = RunCancellationScope()
    forward = (
        AsyncMock(side_effect=RuntimeError("Worker failed")) if fails else AsyncMock(return_value="Worker result")
    )
    call = adapter._business_handler("write_file", forward)
    if fails:
        with pytest.raises(RuntimeError, match="Worker failed"):
            await call(task="Make a document")
    else:
        assert await call(task="Make a document") == "Worker result"
    forward.assert_awaited_once_with(task="Make a document")
    assert adapter.delegation.pending is fails


TOOLS = [
    {"name": name, "parameters": {"type": "object", "properties": properties}}
    for name, properties in [
        ("write_file", {"task": {"type": "string"}}),
        ("nexent_execute_python", {"code": {"type": "string"}}),
    ]
]


def child_message():
    arguments = json.dumps({"task": "Create a document"})
    return AssistantMessage(
        content_parts=[],
        finish_reason="tool_calls",
        tool_calls=[
            ToolCall(
                provider_call_id="child-call",
                index=0,
                name="write_file",
                raw_arguments=arguments,
                parsed_arguments=json.loads(arguments),
            )
        ],
    )


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("bypass", ["final", "python"])
async def test_bridge_corrects_bypass_before_exposing_an_executable_call(saved_profile, streaming, bypass):
    rejected = (
        message("File created")
        if bypass == "final"
        else AssistantMessage(
            content_parts=[],
            finish_reason="tool_calls",
            tool_calls=[
                ToolCall(
                    provider_call_id="root-call",
                    index=0,
                    name="nexent_execute_python",
                    raw_arguments='{"code":"print(1)"}',
                    parsed_arguments={"code": "print(1)"},
                )
            ],
        )
    )
    responses = [rejected, child_message()]
    if streaming:
        service, closed = stream_service(lambda request: [completion(request, responses.pop(0))])
    else:
        service = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
    recovered = Mock()
    selected = policy()
    model = JiuwenServiceModel(
        service, saved_profile, RunCancellationScope(), delegation=selected, on_recovery=recovered
    )
    if streaming:
        chunks = [chunk async for chunk in model.stream("Create the document", tools=TOOLS)]
        assert [call.name for chunk in chunks for call in chunk.tool_calls or []] == ["write_file"]
        assert closed.call_count == 2
    else:
        result = await model.invoke("Create the document", tools=TOOLS)
        assert [call.name for call in result.tool_calls] == ["write_file"]
        assert [tool.name for tool in service.ainvoke.await_args_list[0].args[0].tools] == ["write_file"]
    assert model.delegation_corrections == 1 and recovered.call_count == 1 and selected.pending


async def test_repeated_refusal_to_delegate_fails_instead_of_returning_success(saved_profile):
    service = SimpleNamespace(ainvoke=AsyncMock(return_value=message("I already made the file")))
    model = JiuwenServiceModel(service, saved_profile, RunCancellationScope(), delegation=policy())
    with pytest.raises(ModelServiceError) as failure:
        await model.invoke("Create the document", tools=TOOLS)
    assert failure.value.error.category == "JIUWEN_DELEGATION_REQUIRED"
    assert service.ainvoke.await_count == 2
    with pytest.raises(ModelServiceError):
        await model.invoke("Native harness retries the same failed step", tools=TOOLS)
    assert service.ainvoke.await_count == 2


def test_common_manager_instruction_survives_native_prompt_compilation(mocker):
    items = [
        SimpleNamespace(
            type=ContextItemType.SYSTEM,
            id="system:" + name,
            metadata={"authority": "platform"},
            content={"text": text},
        )
        for name, text in [
            ("manager_orchestration", "COMMON_COLLABORATION_INSTRUCTION"),
            ("execution_flow", "CODE_ACTION_ONLY_INSTRUCTION"),
        ]
    ]
    mocker.patch("nexent.core.agents.orchestration.execution._get_authorized_context_items", return_value=items)
    mocker.patch("nexent.core.agents.orchestration.execution._get_authorized_history", return_value=[])
    adapter = JiuwenAdapter(
        SimpleNamespace(
            query="Create a file",
            agent_config=SimpleNamespace(name="files", instructions="User duties", description=""),
        )
    )
    prompt = adapter._compile_context()
    assert "COMMON_COLLABORATION_INSTRUCTION" in prompt
    assert "CODE_ACTION_ONLY_INSTRUCTION" not in prompt


def test_explicit_delegation_takes_precedence_over_direct_file_guidance(mocker):
    mocker.patch("nexent.core.agents.orchestration.execution._get_authorized_context_items", return_value=[])
    mocker.patch("nexent.core.agents.orchestration.execution._get_authorized_history", return_value=[])
    child = SimpleNamespace(name="file_generation_assistant", invocation_name=None, display_name="文件生成助手")
    adapter = JiuwenAdapter(
        SimpleNamespace(
            query="调用子智能体，帮我生成一个docx文件",
            agent_config=SimpleNamespace(
                name="files", instructions="User duties", description="", worker_agents=[child]
            ),
        )
    )
    prompt = adapter._compile_context()
    assert "file_generation_assistant" in prompt
    assert "before direct execution" in prompt
