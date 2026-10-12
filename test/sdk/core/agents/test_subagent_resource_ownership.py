"""Invocation drains and shared skills obey root resource ownership."""

from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents import sandbox
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated


def owner():
    value = object.__new__(NexentAgent)
    value.stop_event = Event()
    value._subagent_invocations_lock = Lock()
    value._subagent_invocations = {}
    value._subagent_invocations_closed = False
    value.agent = None
    value._sandbox_executors = []
    value._sandbox_skill_runners = []
    value._sandbox_skill_cleanup_owner = value
    value.sandbox_config = None
    value.workspace_path = "shared-workspace"
    return value


def test_root_drain_cancels_children_before_closing_admission():
    root = owner()
    done = Event()
    child = RunCancellationScope(parent_stop_event=root.stop_event)
    child.register_closer(done.set)
    root._subagent_invocations[done] = child
    root._close_subagent_invocations(timeout=0)
    assert child.cancelled and done.is_set()
    assert not root.stop_event.is_set()
    with pytest.raises(RunTerminated, match="stopped accepting"), root._subagent_invocation(None, None, {}):
        pytest.fail("Closed admission cannot allocate or execute a child")


def test_stuck_child_drain_fails_without_claiming_resource_release():
    root = owner()
    done = Event()
    child = RunCancellationScope()
    root._subagent_invocations[done] = child
    with pytest.raises(RuntimeError, match="did not terminate"):
        root._close_subagent_invocations(timeout=0)
    assert child.cancelled and not done.is_set()
    assert root._subagent_invocations[done] is child


def test_child_releases_only_its_executor_and_root_cleans_shared_skills(mocker):
    root, child = owner(), owner()
    root_lease, child_lease, runner = Mock(), Mock(), Mock()
    root.agent = SimpleNamespace(python_executor=root_lease)
    child.agent = SimpleNamespace(python_executor=child_lease)
    child._sandbox_executors = [child_lease, child_lease]
    child._sandbox_skill_cleanup_owner = root
    child._sandbox_skill_runners.append(runner)
    cleanup = mocker.patch.object(sandbox, "cleanup_executor")
    child._cleanup_sandbox()
    runner.cleanup.assert_not_called()
    assert root._sandbox_skill_runners == [runner] and not child._sandbox_skill_runners
    assert child.agent.python_executor is None and not child._sandbox_executors
    assert root.agent.python_executor is root_lease
    assert cleanup.call_count == 1 and cleanup.call_args.args[0] is child_lease
    root._close_subagent_invocations()
    root._cleanup_sandbox()
    runner.cleanup.assert_called_once()
    assert cleanup.call_args.args[0] is root_lease
