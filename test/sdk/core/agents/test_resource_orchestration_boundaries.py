# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared resources have no engine loop and retain scoped cleanup ownership."""

import ast
import importlib
import pickle
import subprocess
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentHistory, AgentRunInfo
from nexent.core.agents.orchestration import execution
from nexent.core.agents.resources.provider import AgentResources
from nexent.core.utils.observer import MessageObserver


def resource_owner(**kwargs):
    return AgentResources(observer=MessageObserver(), model_config_list=[], stop_event=Event(), **kwargs)


@pytest.mark.parametrize("failure", [None, "validate", "prepare", "run"])
def test_common_adapter_lifetime_closes_partial_preparation_without_core_callback(monkeypatch, failure):
    from nexent.core.agents.factory import AgentCoreFactory

    adapter = Mock()
    if failure:
        getattr(adapter, failure).side_effect = RuntimeError(failure)
    create = Mock(return_value=adapter)
    monkeypatch.setattr(AgentCoreFactory, "create", create)
    info = object()
    if failure:
        with pytest.raises(RuntimeError, match=failure):
            execution.execute_adapter(info)
    else:
        assert execution.execute_adapter(info) is adapter.run.return_value
    create.assert_called_once_with(info)
    adapter.close.assert_called_once_with()
    if failure == "validate":
        adapter.prepare.assert_not_called()
    if failure in {"validate", "prepare"}:
        adapter.run.assert_not_called()


@pytest.mark.parametrize("failure", [None, "finalize", "drain", "sandbox"])
def test_shared_close_order_idempotence_and_failed_drain_retains_owner(monkeypatch, failure):
    owner = resource_owner()
    calls = []
    methods = {"drain": "_close_subagent_invocations", "finalize": "_finalize_file_workspace",
               "workspace": "_cleanup_file_workspace", "sandbox": "_cleanup_sandbox"}
    for phase, name in methods.items():
        def run_phase(phase=phase):
            calls.append(phase)
            if phase == failure:
                raise RuntimeError(phase)
        monkeypatch.setattr(owner, name, run_phase)
    if failure:
        with pytest.raises(RuntimeError, match=failure):
            owner.close()
    else:
        owner.close()
    assert calls == (["drain"] if failure == "drain" else ["drain", "finalize", "workspace", "sandbox"])
    assert owner._resources_closed is (failure not in {"drain", "sandbox"})
    if owner._resources_closed:
        owner.close()
        assert calls == ["drain", "finalize", "workspace", "sandbox"]


def test_native_resources_never_construct_default_core(monkeypatch):
    from nexent.core.agents.cores.smolagents.agent import NexentAgent

    monkeypatch.setattr(NexentAgent, "__init__", Mock(side_effect=AssertionError("default core created")))
    owner = resource_owner()
    assert not isinstance(owner, NexentAgent)
    assert not hasattr(owner, "create_single_agent")
    assert not hasattr(owner, "agent_run_with_observer")
    owner.close()
    NexentAgent.__init__.assert_not_called()


def test_resource_child_dispatch_is_injected_and_scope_is_reclaimed():
    selected = []
    def create(config, scope):
        selected.append((config, scope))
        return lambda task: (config.agent_core, task)
    owner = resource_owner(child_invocation_factory=create)
    config = SimpleNamespace(agent_core="jiuwen")
    with owner._subagent_invocation(config, None, {}) as invoke:
        assert invoke("current task") == ("jiuwen", "current task")
        assert len(owner._subagent_invocations) == 1
    assert selected[0][0] is config
    assert not owner._subagent_invocations
    owner.close()


def test_default_core_resource_owner_closes_after_construction_failure(monkeypatch):
    from nexent.core.agents.cores.smolagents import runner

    owner = Mock()
    owner.create_single_agent.side_effect = RuntimeError("partial setup")
    monkeypatch.setattr(runner, "NexentAgent", Mock(return_value=owner))
    info = SimpleNamespace(observer=MessageObserver(), model_config_list=[], stop_event=Event(),
                           redis_client=None, conversation_id=None, user_id=None, cancellation_scope=None,
                           agent_config=object(), context_input=None)
    with pytest.raises(RuntimeError, match="partial setup"):
        runner._run_with_resources(info)
    owner.close.assert_called_once_with()
    owner.agent_run_with_observer.assert_not_called()


@pytest.mark.parametrize("name,canonical", [
    ("AgentConfig", AgentConfig), ("ModelConfig", ModelConfig), ("ToolConfig", ToolConfig),
    ("AgentRunInfo", AgentRunInfo), ("AgentHistory", AgentHistory),
])
def test_configuration_types_use_their_canonical_owner(name, canonical):
    owner = importlib.import_module(canonical.__module__)
    assert getattr(owner, name) is canonical
    assert pickle.loads(pickle.dumps(canonical)) is canonical


def test_output_protocol_error_is_a_single_neutral_contract():
    from nexent.core.agents.contracts.adapter import ModelOutputProtocolExhaustedError
    from nexent.core.agents.cores.smolagents.output_protocol import (
        ModelOutputProtocolExhaustedError as CoreError,
    )

    assert CoreError is ModelOutputProtocolExhaustedError
    assert pickle.loads(pickle.dumps(CoreError)) is ModelOutputProtocolExhaustedError


def test_common_layers_and_native_adapter_do_not_import_default_agent_implementation():
    root = Path(__file__).resolve().parents[4] / "sdk/nexent/core/agents"
    files = list((root / "resources").glob("*.py")) + list((root / "orchestration").glob("*.py"))
    files.append(root / "cores/jiuwen/adapter.py")
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "cores.smolagents" not in (node.module or ""), file
                assert "nexent_agent" not in (node.module or ""), file
                assert "core_agent" not in (node.module or ""), file
                if file.parent.name == "resources":
                    assert "agents.orchestration" not in (node.module or ""), file
                    assert "agents.factory" not in (node.module or ""), file
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                assert not any(keyword.arg == "smolagents_executor" for keyword in node.keywords), file


def test_clean_native_import_and_resources_with_default_agent_modules_blocked():
    sdk = Path(__file__).resolve().parents[4] / "sdk"
    script = f"""
import importlib.abc, sys
sys.path.insert(0, {str(sdk)!r})
class RejectDefaultAgent(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {{'nexent.core.agents.cores.smolagents.agent',
                        'nexent.core.agents.cores.smolagents.core_agent'}}:
            raise AssertionError('default Agent implementation imported: ' + fullname)
sys.meta_path.insert(0, RejectDefaultAgent())
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.resources.provider import AgentResources
from nexent.core.utils.observer import MessageObserver
from threading import Event
owner = AgentResources(observer=MessageObserver(), model_config_list=[], stop_event=Event())
owner.close()
print('NATIVE_IMPORT_PASS')
"""
    result = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert "NATIVE_IMPORT_PASS" in result.stdout
