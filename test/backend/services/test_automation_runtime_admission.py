# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Background admission pins a single scoped run before contacting Runtime."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.errors.exceptions import RuntimeServiceUnavailableError
from infrastructure.local_execution_registry import LocalExecutionRegistry
from management.services.agent import background
from .test_agentos_background_dispatch import ACTOR, PAYLOAD, REFERENCE, dispatch


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["prepare", "start", "projection", None])
async def test_background_keeps_the_projection_marker_only_after_preparation(dispatch, failure):
    error = RuntimeServiceUnavailableError("controlled background failure")
    if failure == "prepare":
        dispatch.compile.side_effect = error
    elif failure == "start":
        dispatch.client.start_prepared_run.side_effect = error
    elif failure == "projection":
        dispatch.project.side_effect = error

    if failure is None:
        assert await background.dispatch_background(PAYLOAD, ACTOR) == dispatch.result
    else:
        with pytest.raises(RuntimeServiceUnavailableError) as caught:
            await background.dispatch_background(PAYLOAD, ACTOR)
        assert caught.value is error

    dispatch.compile.assert_awaited_once()
    if failure == "prepare":
        assert not dispatch.writes
        dispatch.client.start_prepared_run.assert_not_awaited()
    else:
        assert dispatch.writes == [{"projection_message_index": 9, "projection_memory_agent_id": 2}]
        dispatch.client.start_prepared_run.assert_awaited_once()
    if failure in {"prepare", "start"}:
        dispatch.project.assert_not_awaited()
    else:
        dispatch.project.assert_awaited_once_with(dispatch.client, REFERENCE, dispatch.record)
    dispatch.finish_task.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_background_never_writes_or_opens_another_run(dispatch):
    dispatch.record["status"] = "CANCELED"
    with pytest.raises(HTTPException) as caught:
        await background.dispatch_background(PAYLOAD, ACTOR)

    assert caught.value.status_code == 409
    assert not dispatch.writes
    dispatch.compile.assert_not_awaited()
    dispatch.client.start_prepared_run.assert_not_awaited()
    dispatch.project.assert_not_awaited()


@pytest.mark.parametrize("expected_matches", [False, True])
def test_identity_guard_cannot_stop_or_unregister_a_replacement_run(monkeypatch, expected_matches):
    monkeypatch.setattr(LocalExecutionRegistry, "_instance", None)
    registry = LocalExecutionRegistry()
    replacement = SimpleNamespace(stop_event=asyncio.Event())
    registry.register_agent_run(9, replacement, "owner")
    expected = replacement if expected_matches else object()

    assert registry.stop_agent_run(9, "owner", expected_run_info=expected) is expected_matches
    assert replacement.stop_event.is_set() is expected_matches
    assert registry.unregister_agent_run(9, "owner", agent_run_info=expected) is expected_matches
    assert registry.get_agent_run_info(9, "owner") is (None if expected_matches else replacement)
