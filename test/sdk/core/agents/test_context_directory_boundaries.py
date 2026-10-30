# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Context contracts and native bridges keep identities and message semantics."""

import ast
import importlib
import json
import pickle
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from nexent.core.agents.context.config import ContextManagerConfig
from nexent.core.agents.context.llm_summary import LLMSummary
from nexent.core.agents.context.manager import ContextManager
from nexent.core.agents.context.step_renderer import StepRenderer
from nexent.core.agents.contracts.context import (
    ContextInput,
    ContextItemInput,
    ContextMessage,
    ContextToolView,
    FinalContext,
)
from nexent.core.agents.cores.smolagents.context import (
    ManagedContextRuntime,
    adapt_context_model,
)
from nexent.core.agents.cores.smolagents.context_contracts import (
    native_context_messages,
    native_context_rebuild,
)
from nexent.core.utils.observer import MessageObserver
from pydantic import ValidationError
from smolagents.memory import AgentMemory, TaskStep
from smolagents.models import ChatMessage

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("module,names", [
    ("contracts.context", ("ContextInput", "ContextItemInput", "ContextItemType")),
    ("context.summary_cache", ("CompressionCallRecord",)),
    ("contracts.clarification", ("ClarificationOption", "ClarificationQuestion", "ClarificationForm")),
])
def test_context_types_are_owned_and_pickled_by_canonical_modules(module, names):
    owner = importlib.import_module("nexent.core.agents." + module)
    for name in names:
        symbol = getattr(owner, name)
        assert symbol.__module__ == owner.__name__
        assert pickle.loads(pickle.dumps(symbol)) is symbol


def test_evidence_final_context_and_native_protocols_have_separate_owners():
    from nexent.core.agents.contracts import context as data
    from nexent.core.agents.cores.smolagents import context_contracts as native
    assert data.ContextEvidence.__module__ == data.__name__
    assert data.FinalContext.__module__ == data.__name__
    assert native.ContextRuntime.__module__ == native.__name__
    assert native.UnconfiguredContextRuntime.__module__ == native.__name__
    assert ManagedContextRuntime.__module__ == "nexent.core.agents.cores.smolagents.context"


def test_authorized_input_detaches_and_rejects_invalid_payloads():
    item = ContextItemInput(id="source", type="system", content={"text": "policy"})
    snapshot = ContextInput(items=(item,))
    assert pickle.loads(pickle.dumps(snapshot)) == snapshot
    item.content["text"] = "modified"
    assert snapshot.items[0].content == {"text": "policy"}
    with pytest.raises(TypeError, match="immutable tuples"):
        ContextInput(items=[])
    with pytest.raises(ValidationError, match="JSON serializable"):
        ContextItemInput(id="invalid", type="system", content={"text": object()})


def test_common_context_source_imports_no_native_memory_types_or_core_implementations():
    context = ROOT / "sdk/nexent/core/agents/context"
    files = [
        file
        for file in context.rglob("*.py")
        if file.name not in {"compatibility.py", "runtime.py"}
    ]
    files += [
        ROOT / "sdk/nexent/core/agents/contracts/context.py",
        ROOT / "sdk/nexent/core/agents/contracts/clarification.py",
    ]
    for file in files:
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert "smolagents" not in (node.module or ""), file
                assert "cores." not in (node.module or ""), file
    schema = (ROOT / "sdk/nexent/core/agents/contracts/clarification.py").read_text(
        encoding="utf-8"
    )
    assert "load_prompt" not in schema


def test_neutral_cm_runs_with_native_context_bridge_imports_rejected():
    code = f"""
import sys, importlib.abc
sys.path.insert(0, {str(ROOT / "sdk")!r})
import nexent
class NoNativeMemory(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {{'nexent.core.agents.cores.smolagents.context',
                        'nexent.core.agents.context.compatibility'}}:
            raise AssertionError('neutral path imported native memory: ' + fullname)
sys.meta_path.insert(0, NoNativeMemory())
from nexent.core.agents.context.manager import ContextManager
from nexent.core.agents.contracts.context import ContextItemInput
from nexent.core.agents.context.models import ContextItem
manager = ContextManager()
run = manager.prepare_items_context('SYSTEM', [ContextItemInput(id='history', type='system', content={{'text':'FACT'}})])
current = ContextItem.from_input(ContextItemInput(id='task', type='current_task', content={{'text':'CURRENT'}}))
result = manager.assemble_context_items(model=None, run_context=run, current_items=[current])
assert str(result.messages).count('CURRENT') == 1
assert 'FACT' in str(result.messages)
print('NEUTRAL_CM_PASS')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=90
    )
    assert result.returncode == 0, result.stderr
    assert "NEUTRAL_CM_PASS" in result.stdout


@pytest.mark.parametrize("supports_max_tokens", [True, False])
@pytest.mark.parametrize("raises", [True, False])
def test_native_summary_port_preserves_parameters_message_payload_and_restores_model_state(
    supports_max_tokens, raises
):
    observer = MessageObserver()
    budget = object()
    original_body = {"custom": 1, "chat_template_kwargs": {"keep": "value"}}
    calls = []

    class NativeModel:
        def __init__(self):
            self.observer, self.context_budget_snapshot, self.extra_body = (
                observer,
                budget,
                original_body,
            )

        def invoke(self, messages, parameters):
            assert all(isinstance(message, ChatMessage) for message in messages)
            assert [message.role.value for message in messages] == ["system", "user"]
            assert messages[0].content[0]["text"] == "SUMMARY_SYSTEM"
            assert "SOURCE_FACT" in messages[1].content[0]["text"]
            assert self.observer is not observer
            assert self.extra_body["chat_template_kwargs"] == {
                "keep": "value",
                "enable_thinking": False,
            }
            assert (self.context_budget_snapshot is None) is supports_max_tokens
            calls.append(parameters)
            if raises:
                raise RuntimeError("controlled failure")
            return SimpleNamespace(
                content="SUMMARY",
                token_usage=SimpleNamespace(input_tokens=9, output_tokens=2),
            )

    if supports_max_tokens:

        def invoke(self, messages, *, stop_sequences, max_tokens=None):
            return self.invoke(
                messages, {"stop_sequences": stop_sequences, "max_tokens": max_tokens}
            )
    else:

        def invoke(self, messages, *, stop_sequences):
            return self.invoke(messages, {"stop_sequences": stop_sequences})

    NativeModel.__call__ = invoke
    model = NativeModel()
    config = ContextManagerConfig(summary_system_prompt="SUMMARY_SYSTEM")
    summary = LLMSummary(config, StepRenderer(config)).generate_summary(
        "SOURCE_FACT",
        adapt_context_model(model),
        max_output_tokens=19,
    )
    assert len(calls) == 1
    assert calls[0] == (
        {"stop_sequences": [], "max_tokens": 19}
        if supports_max_tokens
        else {"stop_sequences": []}
    )
    assert summary.summary_text == (None if raises else "SUMMARY")
    assert model.observer is observer and model.context_budget_snapshot is budget
    assert model.extra_body is original_body


def test_common_summary_supplies_neutral_messages_without_native_conversion():
    calls = []

    def neutral_model(messages, **parameters):
        assert all(isinstance(message, ContextMessage) for message in messages)
        calls.append((messages, parameters))
        return SimpleNamespace(content="RESULT")

    config = ContextManagerConfig()
    result = LLMSummary(config, StepRenderer(config)).generate_summary(
        "FACT", neutral_model
    )
    assert result.summary_text == "RESULT"
    assert len(calls) == 1


def test_native_lifecycle_uses_neutral_assembly_without_legacy_manager_memory_facades(
    monkeypatch,
):
    manager = ContextManager()

    def forbidden(*args, **kwargs):
        raise AssertionError("production used a legacy memory facade")

    for name in (
        "prepare_run_context",
        "assemble_final_context",
        "_project_current_run",
        "render_memory_messages",
    ):
        monkeypatch.setattr(manager, name, forbidden)
    memory = AgentMemory("SYSTEM")
    memory.steps.append(TaskStep(task="CURRENT"))
    runtime = ManagedContextRuntime(manager)
    runtime.prepare_run(memory=memory, fallback_system_prompt="SYSTEM")
    context = runtime.prepare_step(model=None, memory=memory, current_run_start_idx=0)
    assert str(context.messages).count("CURRENT") == 1
    assert "SYSTEM" in str(context.messages)


def test_native_tool_audit_and_request_messages_preserve_budget_and_fingerprints_without_executable_objects():
    class NativeTool:
        name = "read"

        def __str__(self):
            return "NativeTool(read)"

        def __call__(self):
            raise AssertionError("CM must never execute a tool")

    tools = [NativeTool()]
    overlay = [
        ChatMessage(role="system", content=[{"type": "text", "text": "REQUEST_ONLY"}])
    ]
    memory = AgentMemory("SYSTEM")
    memory.steps.append(TaskStep(task="CURRENT"))
    manager = ContextManager()
    runtime = ManagedContextRuntime(manager)
    runtime.prepare_run(memory=memory, fallback_system_prompt="SYSTEM")
    final = runtime.prepare_step(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=tools,
        request_system_messages=overlay,
    )
    assert all(
        isinstance(tool, ContextToolView) and not callable(tool) for tool in final.tools
    )
    assert json.dumps(final.tools, default=str) == json.dumps(tools, default=str)
    assert any(isinstance(message, ContextMessage) for message in final.messages)
    legacy_manager = ContextManager()
    legacy_run = legacy_manager.prepare_run_context(
        memory=memory, fallback_system_prompt="SYSTEM"
    )
    legacy = legacy_manager.assemble_final_context(
        model=None,
        memory=memory,
        current_run_start_idx=0,
        tools=tools,
        request_system_messages=overlay,
        run_context=legacy_run,
    )
    assert legacy.tools == tools
    assert asdict(final.evidence) == asdict(legacy.evidence)
    assert [
        getattr(message, "content", message)
        for message in native_context_messages(final.messages)
    ] == [getattr(message, "content", message) for message in legacy.messages]


def test_neutral_rebuild_converts_at_native_boundary_without_mutating_common_context():
    common = FinalContext(messages=[ContextMessage(role="user", content="FACT")])
    native = native_context_rebuild(common)
    assert native is not common and native.evidence is common.evidence
    assert isinstance(native.messages[0], ChatMessage)
    assert isinstance(common.messages[0], ContextMessage)
    assert native.messages[0].content == "FACT"
    assert native_context_rebuild(native) is native


@pytest.mark.parametrize(
    "model_id,model_name", [("saved", "alias"), ("", "alias"), (None, None)]
)
def test_native_context_model_keeps_the_original_cache_identity_fallback(
    model_id, model_name
):
    class PlainModel:
        def __call__(self, messages, **kwargs):
            return SimpleNamespace(content="")

    model = PlainModel()
    model.model_id, model.model_name = model_id, model_name
    assert adapt_context_model(model).model_id == (
        model_id or model_name or "PlainModel"
    )


def test_native_memory_selection_uses_the_configured_model_and_only_selects_source_blocks():
    from nexent.core.agents.context.long_term_memory_selector import (
        select_long_term_memory,
    )

    calls = []

    class NativeSelector:
        def __call__(self, messages, *, stop_sequences):
            assert all(isinstance(message, ChatMessage) for message in messages)
            assert stop_sequences == []
            catalog = json.loads(messages[0].content[0]["text"])
            calls.append(catalog)
            selections = {
                scope: [blocks[0]["id"]] for scope, blocks in catalog["blocks"].items()
            }
            return SimpleNamespace(content=json.dumps({"selections": selections}))

    selected, audit = select_long_term_memory(
        {"saved": "Source fact"},
        task="CURRENT",
        target_tokens=100,
        model=adapt_context_model(NativeSelector()),
        chars_per_token=1.5,
    )
    assert selected == {"saved": "Source fact"}
    assert audit["outcome"] == "selected" and len(calls) == 1
