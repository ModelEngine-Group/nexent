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
from contracts.errors.exceptions import AgentRunConcurrencyExceededError
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
        return callback(*args, **kwargs)

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
@pytest.mark.parametrize(("version", "scope"), [(None, "agent:7"), (4, "workbench_main")])
async def test_fixed_replicas_apply_tenant_quota_before_publishing(monkeypatch, payload, runtime, version, scope):
    monkeypatch.setattr(prepared_run, "NEXENT_RECOVERY_MODE", "maintenance")
    start_worker = AsyncMock()
    monkeypatch.setattr(prepared_run._AdmissionSlot, "start_worker", start_worker)
    runtime.begin.side_effect = AgentRunConcurrencyExceededError
    with pytest.raises(AgentRunConcurrencyExceededError):
        await prepared_run.start_prepared_run(payload.model_copy(update={"workbench_config_version": version}), ACTOR)

    assert runtime.begin.call_args.args[0].tenant_id == ACTOR.tenant_id
    assert runtime.begin.call_args.kwargs == {
        "agent_scope": scope, "agent_limit": prepared_run.RUNTIME_AGENT_ID_MAX_CONCURRENT_RUNS,
    }
    runtime.journal.assert_not_called()
    runtime.prepare.assert_not_awaited()
    start_worker.assert_awaited_once_with(RUN_ID)
    runtime.registry.release_agent_capacity.assert_called_once()


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


# Captured first model response from PW-TASK-01 (conversation 3305), with the test marker normalized.
_RECORDED_NO_TOOL_REPLY = """<final_answer>当前会话中没有可用的定时任务调度工具（仅提供文件下载/上传、并行执行、执行输出读取与记忆存储能力），因此我无法为你建立「每 60 分钟」的周期性提醒，也无法在后台按小时主动推送 `TASK-REGRESSION`。

可选的做法：
1. 如果平台侧已开放定时任务能力，请在支持该能力的入口提交："每60分钟告诉我 TASK-REGRESSION"。
2. 你也可以现在把 `TASK-REGRESSION` 对应的具体内容（任务说明、检查项、数据源等）告诉我，我可以即时为你处理，并在本次会话内按需重复输出。

补充：本轮并没有实际的定时任务被创建。若你希望我改为一次性输出该任务标识，或需要我说明如何在你的环境里配置每小时提醒，告诉我即可。</final_answer>"""


@pytest.mark.asyncio
async def test_automation_entry_does_not_end_with_recorded_no_tool_reply(monkeypatch, payload, runtime):
    data = payload.model_dump()
    data["automation_proposal_only"] = True
    data["resource"]["tools"] = [{"tool_id": "create_scheduled_task_proposal", "version": "1"}]
    data["input"]["query"] = "每60分钟告诉我 TASK-REGRESSION"
    dedicated_payload = PreparedAgentRun.model_validate(data)

    async def chat_runner(_info, **_kwargs):
        yield json.dumps({"type": "final_answer", "content": _RECORDED_NO_TOOL_REPLY})

    monkeypatch.setattr(prepared_run, "agent_run", chat_runner)
    proposal = {"proposal_id": 73, "status": "PENDING", "task_id": None}
    request_proposal = AsyncMock(return_value={
        "status": "proposal_ready", "proposal": proposal, "user_message": "Review and confirm.",
    })
    monkeypatch.setattr(prepared_run, "request_automation_proposal", request_proposal, raising=False)

    for request, expected in [
        (payload, [{"type": "final_answer", "content": _RECORDED_NO_TOOL_REPLY}]),
        (dedicated_payload, [
            {"type": "automation_proposal", "content": json.dumps(proposal, ensure_ascii=False)},
            {"type": "final_answer", "content": "Review and confirm."},
        ]),
    ]:
        journal = runtime.journal.return_value
        journal.reset_mock()
        await prepared_run.start_prepared_run(request, ACTOR)
        await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)
        entries = [json.loads(call.args[1].split("\ndata: ", 1)[1]) for call in journal.append.call_args_list]
        assert entries == expected
        journal.repair_terminal.assert_called_once_with("completed")
    request_proposal.assert_awaited_once_with(AgentRunReference(conversation_id=42, run_id=RUN_ID), ACTOR)


@pytest.mark.asyncio
@pytest.mark.parametrize(("result", "language", "final", "terminal"), [
    ({"status": "needs_clarification", "user_message": "Which interval?"}, "en", "Which interval?", "completed"),
    ({"status": "not_automation", "user_message": "Specify the schedule."}, "en", "Specify the schedule.", "completed"),
    ({"status": "error", "user_message": "Provider failed. Try again."}, "en", "Provider failed. Try again.", "failed"),
    ({"status": "proposal_ready", "user_message": "Incomplete result"}, "zh",
     "暂时无法生成定时任务提案，请稍后重试。", "failed"),
    ({"status": "proposal_ready", "proposal": {}, "user_message": "Missing proposal ID"}, "zh",
     "暂时无法生成定时任务提案，请稍后重试。", "failed"),
    ({"status": "proposal_ready", "proposal": {"proposal_id": 73}}, "en",
     "The scheduled-task proposal could not be generated. Try again shortly.", "failed"),
    ({"status": "proposal_ready", "proposal": {"proposal_id": 73}, "user_message": ""}, "en",
     "The scheduled-task proposal could not be generated. Try again shortly.", "failed"),
    (None, "zh", "暂时无法生成定时任务提案，请稍后重试。", "failed"),
])
async def test_automation_entry_reports_clarification_or_retry_without_card(
    monkeypatch, payload, runtime, result, language, final, terminal,
):
    call = AsyncMock(return_value=result) if result else AsyncMock(side_effect=RuntimeError("unavailable"))
    monkeypatch.setattr(prepared_run, "request_automation_proposal", call)
    data = payload.model_dump()
    data["resource"]["tools"] = [{"tool_id": "create_scheduled_task_proposal", "version": "1"}]
    request = PreparedAgentRun.model_validate({**data, "automation_proposal_only": True, "language": language})

    await prepared_run.start_prepared_run(request, ACTOR)
    await asyncio.wait_for(asyncio.gather(*runtime.tasks), timeout=2)

    journal = runtime.journal.return_value
    journal.append.assert_called_once()
    event = json.loads(journal.append.call_args.args[1].split("\ndata: ", 1)[1])
    assert event == {"type": "final_answer", "content": final}
    journal.repair_terminal.assert_called_once_with(terminal)


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
@pytest.mark.parametrize(("owned", "terminal_written"), [(False, True), (True, True), (True, False)])
async def test_prepared_execution_retains_occupancy_until_worker_cleanup(
    monkeypatch, payload, runtime, owned, terminal_written,
):
    running = asyncio.Event()
    detached = asyncio.Event()
    worker = Future()
    assert worker.set_running_or_notify_cancel()
    runtime.info.thread_future = worker
    ownership = SimpleNamespace(coordinator=Mock()) if owned else None
    reserve = AsyncMock(return_value=ownership)

    def finish(identity, status):
        runtime.release.assert_called_once_with(runtime.info, 42, "actor", status)
        assert worker.done()
        return terminal_written

    async def release_ownership(_ownership, _worker):
        runtime.journal.return_value.repair_terminal.assert_called_once_with("stopped")

    runtime.finish.side_effect = finish
    release = AsyncMock(side_effect=release_ownership)
    monkeypatch.setattr(prepared_run, "reserve_agentos_sandbox", reserve)
    monkeypatch.setattr(prepared_run, "release_agentos_sandbox", release)

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
        if owned:
            reserve.await_args.kwargs["cancel"]()
        else:
            runtime.stop.return_value = True
        await asyncio.wait_for(detached.wait(), timeout=2)
        await asyncio.sleep(0)
        runtime.finish.assert_not_called()
        runtime.release.assert_not_called()
        release.assert_not_awaited()
    finally:
        worker.set_result(None)
        await asyncio.wait_for(producer, timeout=2)

    runtime.release.assert_called_once_with(runtime.info, 42, "actor", "stopped")
    runtime.finish.assert_called_once_with(runtime.begin.call_args.args[0], "stopped")
    if owned and terminal_written:
        release.assert_awaited_once_with(ownership, worker)
        ownership.coordinator.signal_lost.assert_not_called()
    else:
        release.assert_not_awaited()
        if owned:
            ownership.coordinator.signal_lost.assert_called_once_with()
            runtime.journal.return_value.repair_terminal.assert_not_called()


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
