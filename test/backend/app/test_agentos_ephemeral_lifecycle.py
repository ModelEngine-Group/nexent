# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check request-owned Runtime streaming, cancellation, and capacity cleanup."""

import asyncio
import json
from concurrent.futures import Future
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from contracts.agentos import PreparedAgentCreatorRun, PreparedEphemeralRun, PreparedSkillCreatorRun
from contracts.constants.constants import SAFE_AGENT_STREAM_ERROR_MESSAGE
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.concurrency import ThreadCapacityExceeded
from runtime.agentos import ephemeral

ACTOR = ServicePrincipal("actor", "tenant")
RUN_ID = "a" * 32


@pytest.fixture
def payload():
    return PreparedEphemeralRun.model_validate({
        "run_id": RUN_ID, "mode": "nexent", "debug": True, "native_knowledge": True,
        "resource": {"agent_id": 7, "version_no": 3, "name": "test", "description": "", "prompt_templates": {}},
        "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "revision-1"}},
        "input": {"query": "question"},
    })


@pytest.fixture
def runtime(mocker):
    execution = SimpleNamespace(execution_id="worker", cancel_event=asyncio.Event(), future=Future())
    info = SimpleNamespace(stop_event=asyncio.Event(), workspace_run_id=RUN_ID, attempt_outcome="completed")
    manager = mocker.Mock(submit=mocker.Mock(return_value=execution), wait_until_started=AsyncMock())
    registry = mocker.Mock()
    materialize = mocker.patch.object(ephemeral, "load_prepared_run", return_value=info)
    mocker.patch.object(ephemeral, "runtime_thread_manager", manager)
    mocker.patch.object(ephemeral, "agent_run_manager", registry)
    mocker.patch.object(ephemeral, "runtime_state_service", SimpleNamespace(enabled=False))
    release = mocker.patch.object(ephemeral, "unregister_after_worker_exit")
    discard = mocker.patch.object(ephemeral, "discard_prepared_workspace")
    mocker.patch.object(ephemeral, "agent_monitoring_context", return_value=nullcontext())

    async def inline(_task, callback, *args, lane, owner):
        assert (lane, owner) == ("control-io", "runtime")
        return callback(*args)

    mocker.patch.object(ephemeral, "run_blocking", side_effect=inline)
    return SimpleNamespace(
        execution=execution, info=info, manager=manager, registry=registry,
        materialize=materialize, release=release, discard=discard,
    )


async def test_debug_response_registers_run_and_cleans_up_after_last_frame(payload, runtime, mocker):
    async def events(*args, **kwargs):
        yield json.dumps({"type": "skill_artifact", "content": "internal"})
        yield json.dumps({"type": "text", "content": "answer"})
        runtime.execution.future.set_result(None)

    mocker.patch.object(ephemeral, "agent_run", side_effect=events)
    response = await ephemeral._open_ephemeral(payload, ACTOR)
    send = AsyncMock()
    owner = ephemeral.debug_owner(ACTOR)

    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, AsyncMock(), send)

    assert response.headers["run_id"] == f"debug-{RUN_ID}"
    assert [call.args[0]["body"] for call in send.await_args_list[1:]] == [
        b": agentos-ready\n\n", b'data: {"type":"text","content":"answer"}\n\n', b"",
    ]
    runtime.registry.register_agent_run.assert_called_once_with(f"debug-{RUN_ID}", runtime.info, owner)
    runtime.release.assert_called_once_with(
        runtime.registry, f"debug-{RUN_ID}", owner, "completed", runtime.info,
    )
    runtime.discard.assert_called_once_with(runtime.info)
    runtime.registry.release_agent_capacity.assert_called_once_with(
        runtime.registry.reserve_agent_capacity.return_value,
    )
    runtime.manager.cancel.assert_not_called()


@pytest.mark.parametrize("before_submission", [False, True])
async def test_failed_ephemeral_open_releases_capacity_at_worker_exit(payload, runtime, before_submission):
    failure = ThreadCapacityExceeded("agent-run", 1, 0)
    if before_submission:
        runtime.manager.submit.side_effect = failure
    else:
        runtime.manager.wait_until_started.side_effect = failure

    with pytest.raises(ThreadCapacityExceeded):
        await ephemeral._open_ephemeral(payload, ACTOR)

    runtime.materialize.assert_not_awaited()
    if before_submission:
        runtime.manager.cancel.assert_not_called()
    else:
        runtime.manager.cancel.assert_called_once_with(
            "worker", reason="ephemeral AgentOS stream closed", wait_timeout=0, mark_stuck_on_timeout=False,
        )
        runtime.registry.release_agent_capacity.assert_not_called()
        runtime.execution.future.cancel()
    runtime.registry.release_agent_capacity.assert_called_once_with(
        runtime.registry.reserve_agent_capacity.return_value,
    )


async def test_skill_creator_reports_worker_failure_without_exposing_error(runtime, mocker):
    creator = PreparedSkillCreatorRun(
        mode="nl2skill", run_id=RUN_ID, input={"query": "draft"},
        model={"model_id": 11, "alias": "llm", "revision": "revision-1"},
        input_budget=512, context_window_tokens=1024,
    )

    async def events(*args, **kwargs):
        yield json.dumps({"type": "text", "content": "started"})
        runtime.execution.future.set_exception(RuntimeError("private implementation detail"))

    mocker.patch.object(ephemeral, "agent_run", side_effect=events)
    response = await ephemeral._open_ephemeral(creator, ACTOR)
    assert [chunk async for chunk in response.body_iterator] == [
        'data: {"type":"text","content":"started"}\n\n',
        'event: agentos_execution_error\ndata: {"type":"error","content":"NL2Skill execution failed."}\n\n',
    ]
    runtime.materialize.assert_awaited_once_with(creator, ACTOR, ephemeral.prepare_skill_creator_run)
    assert "run_id" not in response.headers
    runtime.registry.reserve_agent_capacity.assert_not_called()


def creator_payload(mode, **fields):
    creator_type = PreparedAgentCreatorRun if mode == "nl2agent" else PreparedSkillCreatorRun
    return creator_type.model_validate({
        "mode": mode, "run_id": RUN_ID, "input": {"query": "prepared", "user_query": "original"},
        "model": {"model_id": 11, "alias": "llm", "revision": "revision-1"},
        "input_budget": 512, "context_window_tokens": 1024,
        **({"agent_id": 201, "bound_resources": "Verified"} if mode == "nl2agent" else {}),
        **fields,
    })


@pytest.mark.parametrize("mode", ["nl2agent", "nl2skill"])
@pytest.mark.parametrize("trajectory, expected_source_id", [
    ({"conversation_id": 9, "source_message_id": 10}, "10"),
    ({"conversation_id": 9}, None),
    (None, None),
], ids=["saved-turn", "saved-session", "unsaved"])
async def test_trajectory_metadata_uses_signed_creator_scope(runtime, mode, trajectory, expected_source_id):
    runtime.info.agent_config = SimpleNamespace(agent_core="jiuwen")
    persisted = trajectory is not None
    creator = creator_payload(mode, **({
        "system_agent": {"agent_id": 77, "version_no": 1},
        "trajectory": trajectory,
    } if persisted else {}))
    response = await ephemeral._open_ephemeral(creator, ACTOR)
    metadata = response.metadata
    assert (metadata.user_id, metadata.tenant_id, metadata.query) == (ACTOR.user_id, ACTOR.tenant_id, "original")
    assert metadata.is_debug is not persisted
    assert metadata.conversation_id == (9 if persisted else None)
    assert metadata.agent_id == (77 if persisted else 201 if mode == "nl2agent" else None)
    if expected_source_id is None:
        assert "trajectory_source_message_id" not in metadata.extra_metadata
    else:
        assert metadata.extra_metadata["trajectory_source_message_id"] == expected_source_id
    assert metadata.extra_metadata.get("core_type") == ("jiuwen" if persisted else None)
    assert response.debug_run_id is None
    runtime.registry.reserve_agent_capacity.assert_not_called()
    assert not hasattr(runtime.info, "conversation_id")


@pytest.mark.parametrize(("reference", "trajectory"), [
    (None, {"conversation_id": 9}),
    ({"agent_id": 77, "version_no": 1}, {"conversation_id": "9"}),
    ({"agent_id": 77, "version_no": 1}, {"conversation_id": 0}),
    ({"agent_id": 77, "version_no": 1}, {"conversation_id": 9, "source_message_id": True}),
    ({"agent_id": 77, "version_no": 1}, {"conversation_id": 9, "user_id": "other"}),
])
def test_invalid_creator_trajectory_scope_is_rejected(reference, trajectory):
    with pytest.raises(ValidationError):
        creator_payload("nl2skill", system_agent=reference, trajectory=trajectory)


async def test_debug_watcher_stops_only_the_registered_execution(runtime, mocker):
    state = mocker.patch.object(
        ephemeral, "runtime_state_service", SimpleNamespace(is_cancelled_async=AsyncMock(return_value=True)),
    )
    owner = ephemeral.debug_owner(ACTOR)
    await ephemeral._watch_debug_stop(f"debug-{RUN_ID}", owner, runtime.info)
    state.is_cancelled_async.assert_awaited_once_with(owner, f"debug-{RUN_ID}")
    runtime.registry.stop_local_run.assert_called_once_with(
        f"debug-{RUN_ID}", owner, expected_run=runtime.info,
    )


@pytest.mark.parametrize("stopped", [False, True])
async def test_observer_preserves_disconnect_but_drains_agent_card_on_explicit_stop(runtime, mocker, stopped):
    card = {"type": "nl2a", "content": "draft"}
    runtime.info.observer = SimpleNamespace(
        boundary_reached=True, get_cached_message=lambda: [json.dumps(card)],
    )
    if stopped:
        runtime.info.stop_event.set()

    async def cancelled(*args, **kwargs):
        yield json.dumps(None)
        raise asyncio.CancelledError

    mocker.patch.object(ephemeral, "agent_run", side_effect=cancelled)
    stream = ephemeral._observer_stream(runtime.info, runtime.execution, None, creator_mode="nl2agent")
    if stopped:
        assert [chunk async for chunk in stream] == ['data: {"type":"nl2a","content":"draft"}\n\n']
    else:
        with pytest.raises(asyncio.CancelledError):
            await anext(stream)


async def test_ephemeral_model_error_is_rendered_as_safe_sse(runtime, mocker):
    async def events(*args, **kwargs):
        yield json.dumps(None)
        raise RuntimeError("private implementation detail")

    mocker.patch.object(ephemeral, "agent_run", side_effect=events)
    stream = ephemeral._observer_stream(runtime.info, runtime.execution, None)
    assert [json.loads(chunk.removeprefix("data: ")) async for chunk in stream] == [
        {"type": "error", "content": SAFE_AGENT_STREAM_ERROR_MESSAGE},
    ]
