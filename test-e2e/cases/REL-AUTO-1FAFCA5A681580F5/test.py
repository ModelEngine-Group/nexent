"""D5 special-case reliability test.

Case ID: REL-AUTO-1FAFCA5A681580F5
Contract: backend/apps/runtime_app.py:56-90 (runtime_lifespan graceful shutdown).

Verifies the shutdown sequence
    stop_agent_automation_scheduler
    -> shutdown_agent_stream_tasks (remaining grace timeout)
    -> SandboxPoolManager.shutdown
    -> runtime_thread_manager.shutdown (remaining grace timeout)
    -> finally: clear_default_thread_manager(runtime_thread_manager)
including timeout cleanup of hanging agent stream tasks, the pending-task
warning, and the guarantee that the default thread manager is cleared on both
success and failure paths.
"""

from __future__ import annotations

import asyncio
import re
import time

import pytest

from shared.cases import special_case_params

CASE_ID = "REL-AUTO-1FAFCA5A681580F5"

_STOP_SCHEDULER = "stop_scheduler"
_STREAM_TASKS = "shutdown_agent_stream_tasks"
_SANDBOX = "sandbox_pool_shutdown"
_THREAD_MGR = "thread_manager_shutdown"
_CLEAR = "clear_default_thread_manager"

_EXPECTED_ORDER = (
    _STOP_SCHEDULER,
    _STREAM_TASKS,
    _SANDBOX,
    _THREAD_MGR,
    _CLEAR,
)

_SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+/=-]{8,}|sk-[a-z0-9]{16,}"
    r"|(?:api[_-]?key|access[_-]?key|secret|password|token)\s*[:=]\s*\S{6,})"
)

_PENDING_TASK_NAMES = ("hang-task-1", "hang-task-2")


def _install_shutdown_collaborators(monkeypatch, *, raise_thread_shutdown: bool):
    """Patch every shutdown collaborator so the test isolates the ordering contract."""
    import apps.runtime_app as runtime_app
    from services.thread_lifecycle_service import runtime_thread_manager
    from services.runtime_state_service import runtime_state_service
    import management.services.agent.run as agent_run
    import nexent.core.agents.sandbox as sandbox_mod

    events: list[tuple[str, object]] = []

    async def _noop(*_args, **_kwargs):
        return None

    async def stop_scheduler():
        events.append((_STOP_SCHEDULER, None))

    async def shutdown_stream_tasks(timeout):
        events.append((_STREAM_TASKS, timeout))
        return _PENDING_TASK_NAMES

    async def shutdown_thread_manager(timeout):
        events.append((_THREAD_MGR, timeout))
        if raise_thread_shutdown:
            raise RuntimeError("simulated thread manager shutdown failure")

    def clear_manager(manager):
        assert manager is runtime_thread_manager
        events.append((_CLEAR, None))

    class _FakeSandboxPool:
        def shutdown(self, logger_):
            events.append((_SANDBOX, None))

    monkeypatch.setattr(runtime_app, "start_agent_automation_scheduler", _noop)
    monkeypatch.setattr(runtime_app, "set_default_thread_manager", lambda *a, **k: None)
    monkeypatch.setattr(runtime_app, "stop_agent_automation_scheduler", stop_scheduler)
    monkeypatch.setattr(runtime_app, "clear_default_thread_manager", clear_manager)
    monkeypatch.setattr(runtime_state_service, "set_thread_manager", lambda manager: None)
    monkeypatch.setattr(runtime_thread_manager, "start", lambda: None)
    monkeypatch.setattr(runtime_thread_manager, "shutdown", shutdown_thread_manager)
    monkeypatch.setattr(agent_run, "shutdown_agent_stream_tasks", shutdown_stream_tasks)
    monkeypatch.setattr(sandbox_mod.SandboxPoolManager, "_instance", _FakeSandboxPool())

    return runtime_app, events


async def _enter_and_exit_lifespan(runtime_app) -> float:
    started = time.monotonic()
    async with runtime_app.runtime_lifespan(None):
        pass
    return time.monotonic() - started


@pytest.mark.parametrize("case", special_case_params([CASE_ID]))
def test_runtime_lifespan_graceful_shutdown_order(case, monkeypatch, caplog):
    assert case["id"] == CASE_ID

    # Path 1: normal shutdown.
    runtime_app, events = _install_shutdown_collaborators(monkeypatch, raise_thread_shutdown=False)
    elapsed = asyncio.run(_enter_and_exit_lifespan(runtime_app))

    names = [name for name, _ in events]
    assert names == list(_EXPECTED_ORDER), f"shutdown order mismatch: {names}"

    stream_timeout = events[names.index(_STREAM_TASKS)][1]
    thread_timeout = events[names.index(_THREAD_MGR)][1]
    assert isinstance(stream_timeout, (int, float)) and stream_timeout >= 0
    assert isinstance(thread_timeout, (int, float)) and thread_timeout >= 0
    assert elapsed < 10, f"shutdown did not complete promptly: {elapsed:.2f}s"

    assert any(
        "Agent stream tasks exceeded shutdown grace" in rec.message
        and str(len(_PENDING_TASK_NAMES)) in rec.message
        for rec in caplog.records
    ), "pending agent stream tasks were not logged as a warning"

    for rec in caplog.records:
        assert not _SECRET_RE.search(rec.getMessage()), f"plaintext secret in log: {rec.getMessage()}"

    # Path 2: thread-manager shutdown failure still clears the default manager.
    caplog.clear()
    runtime_app, events = _install_shutdown_collaborators(monkeypatch, raise_thread_shutdown=True)
    with pytest.raises(RuntimeError, match="simulated thread manager shutdown failure"):
        asyncio.run(_enter_and_exit_lifespan(runtime_app))
    names = [name for name, _ in events]
    assert _CLEAR in names, f"clear_default_thread_manager missing on failure path: {names}"
    assert names.index(_THREAD_MGR) < names.index(_CLEAR)
