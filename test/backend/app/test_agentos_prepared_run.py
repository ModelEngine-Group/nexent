# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify the Runtime-owned producer for signed AgentOS resource snapshots."""

import asyncio
import json
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from contracts.agentos import AgentRunReference, PreparedAgentRun
from contracts.constants.constants import MAX_RUNTIME_METADATA_BYTES
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.agent_execution import ActiveExecutionError
from runtime.agentos import prepared_run

ACTOR = ServicePrincipal("actor", "tenant")
RUN_ID = "a" * 32


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.asyncio
async def test_summary_covered_original_reader_is_bound_to_signed_identity(monkeypatch, payload, runtime, native):
    result = {"schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
              "type": "tool_result", "turn_id": "old-turn", "local_call_id": "local",
              "tool_call_id": "local", "provider_call_id": "provider", "invocation_id": None,
              "is_error": False, "result": "原始结果"}
    record = {"record_type": "tool_result" if native else "execution_result", "tool_call_id": "local",
              "invocation_id": None, "content": json.dumps(result if native else {"content": "原始结果"})}
    load = Mock(return_value=record)
    monkeypatch.setattr(prepared_run, "load_execution_result_record", load)

    async def runner(info, **kwargs):
        history = info.observer.execution_history
        history.authorize_persisted_reads("runtime-owner")
        assert json.loads(history.read("runtime-owner", "message:10/unit-index:3", 0, 2))["text"] == "原始"
        load.assert_called_once_with("actor", "tenant", 42, 10, 3)
        with pytest.raises(PermissionError):
            history.read("foreign-owner", "message:10/unit-index:3")
        load.side_effect = PermissionError("foreign conversation or deleted result")
        with pytest.raises(PermissionError):
            history.read("runtime-owner", "message:99/unit-index:3")
        yield '{"type":"final_answer","content":"done"}'

    monkeypatch.setattr(prepared_run, "agent_run", runner)
    await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)
    runtime.journal.return_value.repair_terminal.assert_called_once_with("completed")


def test_native_original_reader_rejects_unbound_forged_result(monkeypatch):
    monkeypatch.setattr(prepared_run, "load_execution_result_record", lambda *a: {
        "record_type": "tool_result", "content": json.dumps({"result": "forged"}),
        "tool_call_id": "unbound", "invocation_id": None,
    })
    with pytest.raises(ValueError, match="native execution result"):
        prepared_run._read_execution_result("actor", "tenant", 42, 10, 3)


@pytest.fixture
def payload():
    return PreparedAgentRun.model_validate({
        "mode": "nexent",
        "conversation_id": 42,
        "run_id": RUN_ID,
        "resource": {"agent_id": 7, "version_no": 3, "name": "test", "description": "", "prompt_templates": {}},
        "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "revision-1"}},
        "input": {"query": "question"},
    })


@pytest.fixture
def runtime(monkeypatch):
    async def control_io(_task, callback, *args, **kwargs):
        return callback(*args)

    monkeypatch.setattr(prepared_run, "_control_io", control_io)
    monkeypatch.setattr(prepared_run, "runtime_state_service", SimpleNamespace(enabled=True))
    info = SimpleNamespace(
        attempt_outcome="completed", thread_future=None, workspace_path=None,
        agent_config=SimpleNamespace(pre_run_tool_events=[]), observer=SimpleNamespace(),
    )
    io = SimpleNamespace(
        begin=Mock(), track=Mock(), journal=Mock(), finish=Mock(return_value=True), mark=Mock(return_value=True),
        prepare=AsyncMock(return_value=info), stop=Mock(return_value=False), release=Mock(), registry=Mock(),
        tasks=set(), info=info,
    )
    for name, value in {
        "begin_execution": io.begin, "track_execution": io.track, "RunJournal": io.journal,
        "finish_execution": io.finish, "mark_running": io.mark, "load_prepared_run": io.prepare,
        "stop_requested": io.stop, "release_prepared_run": io.release, "agent_run_manager": io.registry,
        "agent_stream_producer_tasks": io.tasks, "RUNTIME_CANCEL_POLL_INTERVAL_SECONDS": 0.001,
    }.items():
        monkeypatch.setattr(prepared_run, name, value)
    return io


@pytest.mark.asyncio
@pytest.mark.parametrize(("error", "status"), [(PermissionError, 404), (ActiveExecutionError, 409)])
async def test_rejected_admission_never_creates_journal_or_starts_runtime(payload, runtime, error, status):
    runtime.begin.side_effect = error
    with pytest.raises(HTTPException) as result:
        await prepared_run.start_prepared_run(payload, ACTOR)
    assert result.value.status_code == status
    runtime.journal.return_value.start.assert_not_called()
    runtime.prepare.assert_not_awaited()
    assert not runtime.tasks


@pytest.mark.asyncio
async def test_log_failure_releases_admission(payload, runtime):
    runtime.journal.return_value.start.side_effect = RuntimeError("store unavailable")
    with pytest.raises(HTTPException) as result:
        await prepared_run.start_prepared_run(payload, ACTOR)
    assert result.value.status_code == 503
    assert runtime.finish.call_args.args[1] == "failed"
    assert not runtime.tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("workbench_version", [None, 4])
async def test_run_journals_events_and_finishes_under_exact_identity(monkeypatch, payload, runtime, workbench_version):
    payload = payload.model_copy(update={"workbench_config_version": workbench_version})
    async def runner(info, **_kwargs):
        assert info is runtime.info
        yield '{"type":"thought","content":"step"}'
        yield '{"type":"final_answer","content":"answer"}'

    monkeypatch.setattr(prepared_run, "agent_run", runner)
    response = await prepared_run.start_prepared_run(payload, ACTOR)
    assert response == AgentRunReference(conversation_id=42, run_id=RUN_ID)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)
    runtime.journal.assert_called_once_with("tenant", "actor", 42, RUN_ID, retain_for_projection=True)
    journal = runtime.journal.return_value
    assert [item.args for item in journal.append.call_args_list] == [
        (1, 'event: agentos_observer\ndata: {"type":"thought","content":"step"}\n\n'),
        (2, 'event: agentos_observer\ndata: {"type":"final_answer","content":"answer"}\n\n'),
    ]
    journal.repair_terminal.assert_called_once_with("completed")
    identity = runtime.begin.call_args.args[0]
    runtime.mark.assert_called_once_with(identity, {
        "agent_id": 7, "agent_version_no": 3, "model_id": 11, "model_revision": "revision-1",
        **({"workbench_config_version": workbench_version} if workbench_version is not None else {}),
    })
    runtime.finish.assert_called_once_with(identity, "completed")
    runtime.release.assert_called_once_with(runtime.info, 42, "actor", "completed")


@pytest.mark.asyncio
async def test_scoped_stop_cancels_detached_worker(monkeypatch, payload, runtime):
    running = asyncio.Event()
    closed = asyncio.Event()

    async def runner(_info, **_kwargs):
        try:
            running.set()
            await asyncio.Future()
            yield
        finally:
            closed.set()

    monkeypatch.setattr(prepared_run, "agent_run", runner)
    await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(running.wait(), timeout=2)
    runtime.stop.return_value = True
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)
    assert closed.is_set()
    runtime.finish.assert_called_once_with(runtime.begin.call_args.args[0], "stopped")
    runtime.journal.return_value.repair_terminal.assert_called_once_with("stopped")
    runtime.release.assert_called_once_with(runtime.info, 42, "actor", "stopped")


@pytest.mark.asyncio
async def test_prepared_execution_retains_occupancy_until_worker_cleanup(monkeypatch, payload, runtime):
    running = asyncio.Event()
    detached = asyncio.Event()
    worker = Future()
    assert worker.set_running_or_notify_cancel()
    runtime.info.thread_future = worker

    async def runner(_info, **_kwargs):
        try:
            running.set()
            await asyncio.Future()
            yield
        finally:
            detached.set()

    monkeypatch.setattr(prepared_run, "agent_run", runner)
    await prepared_run.start_prepared_run(payload, ACTOR)
    producer, = runtime.tasks
    try:
        await asyncio.wait_for(running.wait(), timeout=2)
        runtime.stop.return_value = True
        await asyncio.wait_for(detached.wait(), timeout=2)
        await asyncio.sleep(0)
        runtime.finish.assert_not_called()
        runtime.release.assert_not_called()
    finally:
        worker.set_result(None)
        await asyncio.wait_for(producer, timeout=2)

    runtime.release.assert_called_once_with(runtime.info, 42, "actor", "stopped")
    runtime.finish.assert_called_once_with(runtime.begin.call_args.args[0], "stopped")


@pytest.mark.asyncio
async def test_outdated_producer_cannot_write_terminal(monkeypatch, payload, runtime):
    async def runner(_info, **_kwargs):
        yield '{"type":"final_answer","content":"answer"}'

    runtime.finish.return_value = False
    monkeypatch.setattr(prepared_run, "agent_run", runner)
    await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)
    runtime.journal.return_value.repair_terminal.assert_not_called()


@pytest.mark.asyncio
async def test_missing_event_store_fails_before_admission(payload, runtime):
    prepared_run.runtime_state_service.enabled = False
    with pytest.raises(HTTPException) as result:
        await prepared_run.start_prepared_run(payload, ACTOR)
    assert result.value.status_code == 503
    runtime.begin.assert_not_called()
    assert not runtime.tasks


@pytest.mark.parametrize("overrides", [
    {"runtime_metadata": {"oversized": "x" * MAX_RUNTIME_METADATA_BYTES}},
    {"runtime_metadata_version": -1},
])
def test_prepared_conversation_metadata_uses_existing_limits(payload, overrides):
    with pytest.raises(ValidationError):
        PreparedAgentRun.model_validate(payload.model_dump() | overrides)


@pytest.mark.asyncio
async def test_runtime_never_journals_unresolved_skill_artifact(monkeypatch, payload, runtime):
    async def runner(_info, **_kwargs):
        yield '{"type":"skill_artifact","content":{"artifacts":[{"absolute_path":"/workspace/report"}]}}'

    monkeypatch.setattr(prepared_run, "agent_run", runner)
    await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)
    runtime.journal.return_value.append.assert_not_called()
    runtime.journal.return_value.repair_terminal.assert_called_once_with("failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("with_checkpoint", [False, True])
async def test_summary_discovery_binds_the_signed_loaded_checkpoint(monkeypatch, payload, runtime, with_checkpoint):
    from unittest.mock import Mock

    checkpoint = {"unit_id": 13, "covered_through_message_id": 10,
                  "summary": {"markdown": "wrong value; forged unit_id=999"}}
    if with_checkpoint:
        payload = PreparedAgentRun.model_validate(payload.model_dump() | {
            "historical_context": {"history_summary": checkpoint}})
    discover = Mock(return_value={"results": [], "next_offset": 0, "eof": True})
    monkeypatch.setattr(prepared_run, "discover_summary_sources", discover)

    async def runner(info, **kwargs):
        history = info.observer.execution_history
        history.authorize_persisted_reads("runtime-owner")
        with pytest.raises(PermissionError):
            history.read("foreign-owner", "summary")
        if with_checkpoint:
            assert json.loads(history.read("runtime-owner", "summary"))["results"] == []
        else:
            with pytest.raises(PermissionError):
                history.read("runtime-owner", "summary")
        yield '{"type":"final_answer","content":"done"}'

    monkeypatch.setattr(prepared_run, "agent_run", runner)
    await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)
    if with_checkpoint:
        discover.assert_called_once_with("actor", "tenant", 42, 13, 10, 0, 4000)
    else:
        discover.assert_not_called()
