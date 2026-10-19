"""Child selection, snapshot isolation and adapter ownership contracts."""

from concurrent.futures import Future
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import AgentConfig, AgentRunInfo, ModelConfig
from nexent.core.agents.core_adapters.children import child_run_info, invoke_child
from nexent.core.agents.core_adapters.jiuwen import JiuwenAdapter
from nexent.core.agents.core_adapters.smolagents import SmolagentsAdapter
from nexent.core.concurrency import RunCancellationScope
from nexent.core.utils.observer import MessageObserver


def configuration(core="jiuwen"):
    return AgentConfig(name="child", description="Child", model_name="shared", tools=[], agent_core=core)


@pytest.mark.parametrize("core", ["jiuwen", "smolagents"])
def test_child_keeps_own_binding_and_has_no_parent_history_or_workspace_ownership(core):
    child = configuration(core)
    child.runtime_model_config = ModelConfig(cite_name="shared", model_name="child-model", url="http://child",
                                           api_key="child-only", temperature=0.2, extra_body={"nested": {"a": 1}})
    parent = AgentRunInfo(query="parent", agent_config=configuration(), observer=MessageObserver(), stop_event=Event(),
        model_config_list=[ModelConfig(cite_name="shared", model_name="parent-model", url="http://parent",
                                      api_key="parent-only", temperature=0.9)],
        history=[{"role": "user", "content": "parent-secret"}], workspace_run_id="parent-owned")
    scope = RunCancellationScope(parent_stop_event=parent.stop_event)
    info = child_run_info(parent, child, scope)
    selected = info.model_config_list[0]
    assert info.agent_config.agent_core == core
    assert (selected.model_name, selected.url, selected.api_key, selected.temperature) == (
        "child-model", "http://child", "child-only", 0.2)
    assert info.history is None and info.context_input is None and info.workspace_run_id is None
    assert info.stop_event is scope.stop_event and info.observer is parent.observer
    selected.extra_body["nested"]["a"] = 2
    assert child.runtime_model_config.extra_body["nested"]["a"] == 1
    assert parent.model_config_list[0].temperature == 0.9
    assert "runtime_model_config" not in child.model_dump()


@pytest.mark.parametrize("failure", [None, "validate", "prepare", "run"])
def test_child_factory_selects_core_and_always_closes(mocker, failure):
    info = Mock()
    adapter = Mock()
    adapter.run.return_value = "child-result"
    if failure:
        getattr(adapter, failure).side_effect = RuntimeError("controlled failure")
    factory = mocker.patch("nexent.core.agents.core_adapters.children.AgentCoreFactory.create", return_value=adapter)
    if failure:
        with pytest.raises(RuntimeError, match="controlled failure"):
            invoke_child(info, "child-task")
    else:
        assert invoke_child(info, "child-task") == "child-result"
    factory.assert_called_once_with(info)
    adapter.close.assert_called_once()
    assert info.query == "child-task"


@pytest.mark.parametrize("task", ["", " ", None, 1])
def test_empty_or_non_string_child_task_allocates_nothing(mocker, task):
    factory = mocker.patch("nexent.core.agents.core_adapters.children.AgentCoreFactory.create")
    with pytest.raises(ValueError):
        invoke_child(Mock(), task)
    factory.assert_not_called()


def test_smol_parent_accepts_child_with_different_core():
    parent = configuration("smolagents")
    parent.worker_agents = [configuration("jiuwen")]
    SmolagentsAdapter(Mock(agent_config=parent)).validate()


def test_child_binding_alias_mismatch_is_rejected():
    child = configuration()
    child.runtime_model_config = ModelConfig(cite_name="other", model_name="child", url="http://child")
    with pytest.raises(ValueError, match="alias mismatch"):
        child_run_info(SimpleNamespace(model_config_list=[]), child, RunCancellationScope())


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", ["control-io", "model-tool-io"])
async def test_only_collaboration_deadline_cancels_owner(lane, caplog):
    future = Future()
    if lane == "model-tool-io":
        future.set_exception(TimeoutError("tool-local timeout"))
    info = SimpleNamespace(collaboration_timeout_seconds=0.01, model_deadline=None, observer=Mock())
    adapter = JiuwenAdapter(info)
    adapter.scope = RunCancellationScope()
    adapter.manager = Mock()
    adapter.manager.submit.return_value = SimpleNamespace(future=future, execution_id="owned")
    adapter._observe_tool = Mock(return_value=nullcontext())
    with pytest.raises(TimeoutError):
        await adapter._business_handler("delegate", lambda: None, lane=lane)()
    assert adapter.scope.cancelled == (lane == "control-io")
    if lane == "control-io":
        assert future.cancelled()
        adapter.manager.cancel.assert_called_once()
        assert "event=agent_collaboration_timeout" in caplog.text
        assert "phase=queue_or_execution" in caplog.text
    else:
        adapter.manager.cancel.assert_not_called()
