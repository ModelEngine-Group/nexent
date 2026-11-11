# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolved Agent versions belong to the executing Agent, never its parent."""

import sys
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from nexent.monitor.monitoring import AgentRunMetadata, MonitoringManager


@pytest.mark.parametrize("version", [0, 1, 3])
def test_agent_span_records_integer_version_and_optional_name(version):
    manager = Mock()
    manager.build_openinference_attributes.side_effect = lambda **kwargs: kwargs["attributes"]
    values = MonitoringManager.build_agent_run_attributes(
        manager, AgentRunMetadata(agent_version_no=version, agent_version_name="Release")
    )
    assert values["agent.version_no"] == version
    assert type(values["agent.version_no"]) is int
    assert values["agent.version_name"] == "Release"


@pytest.mark.parametrize("version", [None, True, -1, "3", 1.5, 2**63])
def test_unknown_or_invalid_versions_are_not_draft(version):
    manager = Mock()
    manager.build_openinference_attributes.side_effect = lambda **kwargs: kwargs["attributes"]
    values = MonitoringManager.build_agent_run_attributes(
        manager, AgentRunMetadata(agent_version_no=version, agent_version_name="untrusted")
    )
    assert "agent.version_no" not in values
    assert "agent.version_name" not in values
    assert values["nexent.availability.agent_version_no"] in {"not_captured", "invalid"}


@pytest.mark.parametrize("kind", ["LLM", "TOOL", "CHAIN"])
def test_model_and_tool_spans_do_not_duplicate_agent_version(kind):
    manager = Mock()
    manager.build_openinference_attributes.side_effect = lambda **kwargs: kwargs["attributes"]
    values = MonitoringManager.build_agent_run_attributes(
        manager, AgentRunMetadata(agent_version_no=3), span_kind=kind
    )
    assert "agent.version_no" not in values
    assert "nexent.availability.agent_version_no" not in values


@pytest.mark.parametrize("version", [3, 0, None])
def test_worker_uses_final_config_instead_of_request_metadata(monkeypatch, version):
    factory = ModuleType("nexent.core.agents.nexent_agent")
    factory.NexentAgent = Mock()
    factory.ProcessType = Mock()
    factory.cleanup_run_workspace = Mock()
    source = Path(__file__).resolve().parents[3] / "sdk/nexent/core/agents/run_agent.py"
    spec = spec_from_file_location("nexent.core.agents._version_worker_test", source)
    run_agent = module_from_spec(spec)
    with patch.dict(sys.modules, {"nexent.core.agents.nexent_agent": factory}):
        spec.loader.exec_module(run_agent)

    seen = []

    @contextmanager
    def start(metadata):
        seen.append(metadata)
        yield None

    manager = SimpleNamespace(is_enabled=False, start_agent_run=start)
    monkeypatch.setattr(run_agent, "get_monitoring_manager", lambda: manager)
    monkeypatch.setattr(run_agent, "get_agent_monitoring_context", lambda: AgentRunMetadata(agent_version_no=99))
    worker = Mock()
    monkeypatch.setattr(run_agent, "_agent_run_thread", worker)
    info = SimpleNamespace(agent_config=SimpleNamespace(version_no=version, version_name="Frozen"), query="q")
    run_agent.agent_run_thread(info)
    assert seen[0].agent_version_no == version
    assert seen[0].agent_version_name == "Frozen"
    worker.assert_called_once_with(info)


@pytest.mark.parametrize("version", [2, 1, 0, None])
@pytest.mark.parametrize("failed", [False, True])
def test_subagent_uses_own_version_and_preserves_call_outcome(monkeypatch, version, failed):
    from nexent.core.agents import subagent_wrapper as module

    seen = []

    @contextmanager
    def operation(*args, **attributes):
        seen.append(attributes)
        yield None

    manager = Mock()
    manager.build_openinference_attributes.side_effect = lambda **kwargs: kwargs["attributes"]
    manager.build_agent_run_attributes.side_effect = lambda *args, **kwargs: (
        MonitoringManager.build_agent_run_attributes(manager, *args, **kwargs)
    )
    manager.trace_operation = operation
    monkeypatch.setattr(module, "get_monitoring_manager", lambda: manager)
    monkeypatch.setattr(module, "get_agent_monitoring_context", lambda: AgentRunMetadata(agent_version_no=3))
    inner = Mock(return_value="done", name="child")
    inner.name = "child"
    if failed:
        inner.side_effect = ValueError("controlled")
    observer = Mock()
    wrapper = module.SubAgentToolWrapper(inner, observer, runtime_identity={"version_no": version})
    if failed:
        with pytest.raises(ValueError, match="controlled"):
            wrapper(task="q")
    else:
        assert wrapper(task="q") == "done"
    assert seen[0].get("agent.version_no") == version
    if version is None:
        assert "agent.version_no" not in seen[0]
    inner.assert_called_once_with(task="q")
    observer.add_subagent_end.assert_called_once()
