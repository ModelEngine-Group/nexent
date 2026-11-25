# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ensure the signed Runtime producer and the public subscriber have separate lifetimes."""

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from starlette.requests import ClientDisconnect

from contracts.agent import AgentRequest
from contracts.agentos import AgentResume, AgentStop
from infrastructure.rdb.agent_execution import ActiveExecutionError, RunIdentity
from management.services.agent import prepared_turn
from nexent.monitor import AgentRunMetadata
from runtime.agentos import ephemeral, prepared_run, resume
from ..app.test_agentos_prepared_run import ACTOR, RUN_ID, payload, runtime
from .test_prepared_public_turn import ACTOR as OWNER, PAYLOAD, REFERENCE, flow


async def settle(runtime):
    await asyncio.wait_for(asyncio.gather(*list(runtime.tasks)), timeout=2)


@pytest.mark.asyncio
async def test_headers_only_client_leaves_worker_to_finish_and_replay(payload, runtime, mocker):
    journal = runtime.journal.return_value
    entries = []

    def append(index, data):
        entries.append((f"{index}-0", {"kind": "event", "data": data}))

    def terminal(status):
        entries.append((f"{len(entries) + 1}-0", {"kind": "terminal", "status": status}))

    journal.append.side_effect = append
    journal.repair_terminal.side_effect = terminal
    journal.replay.side_effect = lambda _after: ([("0-0", {"kind": "start"})], entries, entries[-1:])

    async def source(info, **_kwargs):
        assert info is runtime.info
        yield '{"type":"final_answer","content":"answer"}'

    mocker.patch.object(prepared_run, "agent_run", side_effect=source)
    reference = await prepared_run.start_prepared_run(payload, ACTOR)
    await settle(runtime)
    runtime.finish.assert_called_once_with(runtime.begin.call_args.args[0], "completed")
    assert not runtime.tasks
    mocker.patch.object(resume, "_owned_journal", return_value=journal)

    async def io(_name, function, *args, **kwargs):
        return function(*args, **kwargs)

    mocker.patch.object(resume, "_control_io", side_effect=io)
    response = await resume.resume_run(AgentResume(**reference.model_dump()), ACTOR)
    output = "".join([event async for event in response.body_iterator])
    assert f"id: {RUN_ID}:1" in output and '"content":"answer"' in output
    assert f"id: {RUN_ID}:2" in output and '"status": "completed"' in output
    assert response.headers[resume.REPLAY_COUNT_HEADER] == "1"


@pytest.mark.asyncio
async def test_lost_ack_during_runtime_admission_settles_one_owned_run(payload, runtime, mocker):
    entered = asyncio.Event()
    proceed = asyncio.Event()

    async def io(name, function, *args):
        if name == "agentos-prepared-journal":
            entered.set()
            await proceed.wait()
        return function(*args)

    async def source(_info, **_kwargs):
        yield '{"type":"final_answer","content":"answer"}'

    mocker.patch.object(prepared_run, "_control_io", side_effect=io)
    mocker.patch.object(prepared_run, "agent_run", side_effect=source)
    request = asyncio.create_task(prepared_run.start_prepared_run(payload, ACTOR))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        request.cancel()
        await asyncio.sleep(0)
        assert not request.done()
        assert runtime.begin.call_count == 1
        runtime.begin.side_effect = ActiveExecutionError
        with pytest.raises(HTTPException) as duplicate:
            await prepared_run.start_prepared_run(payload, ACTOR)
        assert duplicate.value.status_code == 409
    finally:
        proceed.set()

    with pytest.raises(asyncio.CancelledError):
        await request
    await settle(runtime)
    runtime.journal.return_value.start.assert_called_once_with()
    runtime.prepare.assert_awaited_once()
    runtime.finish.assert_called_once_with(runtime.begin.call_args_list[0].args[0], "completed")


@pytest.mark.parametrize('debug', [False, True])
@pytest.mark.asyncio
async def test_admission_identity_reaches_worker_without_changing_response_ids(lifecycle, debug):
    env = lifecycle
    env.request.is_debug = debug
    seen = []

    async def source(request, **_kwargs):
        seen.append(request.__dict__['_runtime_execution_run_id'])
        env.channel.complete()
        env.future.set_result(None)
        yield 'data: done\n\n'

    response = await env.start(source)
    run_id = env.request.__dict__['_runtime_execution_run_id']
    spec = env.service.runtime_thread_manager.submit.call_args.args[1]
    assert spec.run_id == run_id
    assert len(run_id) == 32
    assert run_id != str(env.request.conversation_id)
    if debug:
        assert response.headers['run_id'].startswith('debug-')
        assert response.headers['run_id'] != run_id
    else:
        assert response.headers['conversation_id'] == '123'
        await asyncio.wait_for(asyncio.gather(*env.service._agent_stream_producer_tasks), timeout=1)
    _ = [chunk async for chunk in response.body_iterator]
    assert seen == [run_id]


@pytest.mark.asyncio
async def test_admission_identity_reaches_worker_without_changing_conversation_id(payload, runtime, mocker):
    async def source(info, **_kwargs):
        assert info is runtime.info
        yield '{"type":"final_answer","content":"done"}'

    mocker.patch.object(prepared_run, "agent_run", side_effect=source)
    reference = await prepared_run.start_prepared_run(payload, ACTOR)
    await settle(runtime)
    assert reference.run_id == payload.run_id
    assert reference.conversation_id == payload.conversation_id
    assert reference.run_id != str(reference.conversation_id)
    runtime.prepare.assert_awaited_once_with(payload, ACTOR, prepared_run.prepare_run_snapshot)


@pytest.mark.asyncio
async def test_preparation_failure_records_safe_terminal_and_releases_capacity(payload, runtime, mocker):
    runtime.prepare.side_effect = RuntimeError("private provider details")
    worker = mocker.patch.object(prepared_run, "agent_run")
    await prepared_run.start_prepared_run(payload, ACTOR)
    await settle(runtime)

    worker.assert_not_called()
    runtime.journal.return_value.append.assert_not_called()
    runtime.journal.return_value.repair_terminal.assert_called_once_with("failed")
    runtime.finish.assert_called_once_with(runtime.begin.call_args.args[0], "failed")
    runtime.registry.release_agent_capacity.assert_called_once_with(runtime.registry.reserve_agent_capacity.return_value)
    assert not runtime.tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("during", ["preparation", "execution"])
async def test_stop_reaches_owned_worker_even_without_a_subscriber(payload, runtime, mocker, during):
    entered = asyncio.Event()
    closed = asyncio.Event()

    async def waiting():
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    async def execute(_info, **_opts):
        await waiting()
        yield "unreachable"

    if during == "preparation":
        async def prepare(*_args):
            await waiting()

        runtime.prepare.side_effect = prepare
        execute_worker = mocker.patch.object(prepared_run, "agent_run")
    else:
        mocker.patch.object(prepared_run, "agent_run", new=execute)

    await prepared_run.start_prepared_run(payload, ACTOR)
    await asyncio.wait_for(entered.wait(), timeout=2)
    runtime.stop.return_value = True
    await settle(runtime)

    assert closed.is_set()
    expected = runtime.begin.call_args.args[0]
    runtime.stop.assert_called_with(expected)
    runtime.finish.assert_called_once_with(expected, "stopped")
    runtime.journal.return_value.repair_terminal.assert_called_once_with("stopped")
    if during == "preparation":
        execute_worker.assert_not_called()
    else:
        runtime.release.assert_called_once_with(runtime.info, payload.conversation_id, ACTOR.user_id, "stopped")


@pytest.mark.asyncio
async def test_stop_fence_after_preparation_prevents_sdk_dispatch(payload, runtime, mocker):
    runtime.mark.return_value = False
    worker = mocker.patch.object(prepared_run, "agent_run")
    await prepared_run.start_prepared_run(payload, ACTOR)
    await settle(runtime)

    runtime.prepare.assert_awaited_once()
    worker.assert_not_called()
    runtime.release.assert_called_once_with(runtime.info, payload.conversation_id, ACTOR.user_id, "stopped")
    runtime.journal.return_value.repair_terminal.assert_called_once_with("stopped")


@pytest.mark.asyncio
async def test_stop_polling_is_scoped_to_the_original_run_id(runtime):
    first = RunIdentity("tenant", "actor", 42, "a" * 32)
    later = RunIdentity("tenant", "actor", 42, "b" * 32)
    runtime.stop.side_effect = lambda record: record == first

    second = asyncio.create_task(prepared_run._wait_for_stop(later))
    try:
        await asyncio.sleep(0)
        await asyncio.wait_for(prepared_run._wait_for_stop(first), timeout=2)
        assert not second.done()
        assert {call.args[0] for call in runtime.stop.call_args_list} == {first, later}
    finally:
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)


@pytest.mark.asyncio
async def test_debug_disconnect_cancels_only_the_request_owned_worker(mocker):
    info = SimpleNamespace(stop_event=asyncio.Event(), attempt_outcome=None, workspace_run_id=RUN_ID)
    execution = SimpleNamespace(future=Future(), cancel_event=asyncio.Event(), execution_id="fixture")
    deferred = SimpleNamespace(cancel=Mock())
    closed = asyncio.Event()

    async def inline(_name, fn, *args, **_kwargs):
        return fn(*args)

    async def events(*_args, **_kwargs):
        try:
            yield '{"type":"thought","content":"started"}'
        finally:
            closed.set()

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("client disconnected")

    mocker.patch.object(ephemeral, "run_blocking", side_effect=inline)
    mocker.patch.object(ephemeral, "runtime_state_service", SimpleNamespace(enabled=False))
    mocker.patch.object(ephemeral, "agent_run", new=events)
    registry = mocker.patch.object(ephemeral, "agent_run_manager")
    manager = mocker.patch.object(ephemeral, "runtime_thread_manager")
    discard = mocker.patch.object(ephemeral, "discard_prepared_workspace")
    response = ephemeral._EphemeralResponse(info, execution, deferred, AgentRunMetadata(), debug_owner="actor")

    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, AsyncMock(), send)

    assert closed.is_set()
    registry.register_agent_run.assert_called_once_with(f"debug-{RUN_ID}", info, "actor")
    manager.cancel.assert_called_once()
    assert manager.cancel.call_args.args == ("fixture",)
    deferred.cancel.assert_called_once_with()
    discard.assert_called_once_with(info)


@pytest.mark.asyncio
async def test_claimed_conversation_binds_before_public_subscription_and_keeps_run_id(flow):
    operations, _, client, _ = flow
    request = AgentRequest.model_validate(PAYLOAD.request)
    response = await prepared_turn.start_turn(PAYLOAD, request, *OWNER, client)
    assert operations == ["stage", "start", "confirm"]
    staged = prepared_turn.store.stage_turn.call_args.args
    assert staged[1] == REFERENCE and staged[2:4] == OWNER
    client.resume.assert_awaited_once_with(AgentResume(**REFERENCE.model_dump()), *OWNER)
    assert response.headers["run_id"] == REFERENCE.run_id
    assert b"".join([frame async for frame in response.body_iterator]) == b"data: answer\n\n"


@pytest.mark.asyncio
async def test_confirmation_failure_stops_owned_run_before_releasing_admission(flow):
    operations, _, client, staged = flow
    prepared_turn.store.confirm_turn.side_effect = prepared_turn.store.PreparedTurnConflict

    async def stop(payload, user_id, tenant_id):
        assert (payload, user_id, tenant_id) == (AgentStop(**REFERENCE.model_dump(), prevent_start=True), *OWNER)
        assert operations == ["stage", "start"]
        operations.append("stop")

    client.stop_run = AsyncMock(side_effect=stop)
    with pytest.raises(HTTPException) as conflict:
        await prepared_turn.start_turn(PAYLOAD, AgentRequest.model_validate(PAYLOAD.request), *OWNER, client)

    assert conflict.value.status_code == 409
    assert operations == ["stage", "start", "stop", "close"]
    prepared_turn.store.close_turn.assert_called_once_with(staged)
    client.resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejected_lifecycle_without_event_store_leaves_no_owned_execution(payload, runtime):
    prepared_run.runtime_state_service.enabled = False
    with pytest.raises(HTTPException) as denied:
        await prepared_run.start_prepared_run(payload, ACTOR)

    assert denied.value.status_code == 503
    runtime.begin.assert_not_called()
    runtime.journal.assert_not_called()
    runtime.registry.reserve_agent_capacity.assert_not_called()
    assert not runtime.tasks
