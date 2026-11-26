# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run Creator worker generation fences against a Lua-capable Redis fake."""

import fakeredis
import pytest

from infrastructure.redis import run_state


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setattr(run_state, "RUNTIME_STATE_REDIS_URL", "redis://test")
    service = run_state.RuntimeStateService()
    service._client = fakeredis.FakeRedis(decode_responses=True)
    return service


def test_management_seal_rejects_late_runtime_start(state):
    run_id = "a" * 32
    assert state.claim_creator_run("owner", 91, run_id, execution_id=run_id)
    assert state.creator_worker_state("owner", 91, run_id, "seal") == "closed"
    assert state.creator_worker_state("owner", 91, run_id, "start") is None
    assert state.creator_worker_state("owner", 91, run_id, "seal") == "closed"


def test_runtime_attachment_requires_exact_run_and_worker_completion(state):
    run_id, next_run_id = "a" * 32, "b" * 32
    assert state.claim_creator_run("owner", 91, run_id, execution_id=run_id)
    assert state.creator_worker_state("other", 91, run_id, "start") is None
    assert state.creator_worker_state("owner", 92, run_id, "start") is None
    assert state.creator_worker_state("owner", 91, next_run_id, "start") is None
    assert state.creator_worker_state("owner", 91, run_id, "complete") is None
    assert state.creator_worker_state("owner", 91, run_id, "start") == "running"
    assert state.creator_worker_state("owner", 91, run_id, "start") is None
    assert state.creator_worker_state("owner", 91, run_id, "seal") == "running"
    assert state.creator_worker_state("owner", 91, run_id, "complete") == "closed"
    assert state.creator_worker_state("owner", 91, run_id, "seal") == "closed"

    assert state.claim_creator_run("owner", 91, next_run_id, execution_id=next_run_id)
    assert state.creator_worker_state("owner", 91, run_id, "complete") is None
    assert state.creator_worker_state("owner", 91, next_run_id, "start") == "running"


def test_finished_stream_keeps_worker_marker_until_runtime_acknowledges(state, monkeypatch):
    monkeypatch.setattr(run_state, "RUNTIME_RUN_TTL_SECONDS", 90)
    monkeypatch.setattr(run_state, "RUNTIME_COMPLETED_TTL_SECONDS", 10)
    run_id = "a" * 32
    assert state.claim_creator_run("owner", 91, run_id, execution_id=run_id)
    assert state.creator_worker_state("owner", 91, run_id, "start") == "running"
    state.mark_stream_completed("owner", 91, "stopped", generation=run_id)
    state.mark_run_finished("owner", 91, "stopped", generation=run_id)

    assert 10 < state.client.ttl(state._run_key("owner", 91)) <= 90
    assert 0 < state.client.ttl(state._stream_done_key("owner", 91)) <= 10
    assert state.creator_worker_state("owner", 91, run_id, "seal") == "running"
    assert state.creator_worker_state("owner", 91, run_id, "complete") == "closed"
    assert state.creator_worker_state("owner", 91, run_id, "seal") == "closed"
    assert 0 < state.client.ttl(state._run_key("owner", 91)) <= 10


def test_redis_replay_remains_compatible_with_an_old_numeric_creator_reference(state):
    assert state.claim_creator_run("owner", 91, "execution:42", execution_id=42)
    assert state.bind_execution_message("owner", 91, 42, 101)
    state.mark_stream_completed("owner", 91, "completed", generation="execution:42")

    snapshot = state.read_execution_stream("owner", 91, 42)

    assert snapshot["generation"] == "execution:42"
    assert snapshot["terminal_status"] == "completed"
    assert snapshot["message_id"] == 101
