# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real isolated Redis, channel publication and reconnect cursor collaboration."""

import asyncio
import json
import subprocess
import time
import uuid
from contextlib import contextmanager

import pytest
import redis

from infrastructure.redis import run_state
from management.services.agent.channels import StreamingChannel
from management.services.agent.replay import subscribe_shared_checkpoint


CASE_ID = "WB-EXECUTION-RECOVERY-D3-001"


@contextmanager
def owned_redis():
    name = "nexent-execution-replay-" + uuid.uuid4().hex[:12]
    client = None
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name,
                    "--label", "nexent.test.case=" + CASE_ID, "-p", "127.0.0.1::6379",
                    "redis:alpine", "redis-server", "--save", "", "--appendonly", "no"],
                   check=True, capture_output=True, timeout=45)
    try:
        address = subprocess.check_output(["docker", "port", name, "6379/tcp"], text=True, timeout=10).strip()
        client = redis.Redis(host="127.0.0.1", port=int(address.rsplit(":", 1)[1]),
                             decode_responses=True, socket_timeout=3)
        deadline = time.monotonic() + 10
        while True:
            try:
                if client.ping():
                    break
            except redis.ConnectionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        yield client
    finally:
        if client is not None:
            client.close()
        subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True, timeout=15)
    assert subprocess.run(["docker", "inspect", name], capture_output=True, timeout=10).returncode != 0


def event(kind, content, **metadata):
    return "data: " + json.dumps({"type": kind, "content": content, **metadata}) + "\n\n"


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
async def test_execution_checkpoint_replay_and_generation_ownership(monkeypatch):
    with owned_redis() as client:
        class State(run_state.RuntimeStateService):
            @property
            def enabled(self):
                return True

            @property
            def client(self):
                return client

        service = State()
        monkeypatch.setattr("management.services.agent.channels.runtime_state_service", service)
        monkeypatch.setattr(run_state, "RUNTIME_STREAM_MAX_LEN", 2)
        monkeypatch.setattr("management.services.agent.channels.RUNTIME_STREAM_LOCAL_REPLAY_MAX_BYTES", 128)
        service.reset_stream("owner", 91, generation="first")
        service.register_run("owner", 91)
        channel = StreamingChannel("91", "owner", history_size=2)
        channel.generation = "first"
        await channel.publish(event("parse", "first-code", unit_index=0))
        await channel.publish(event("execution_logs", "first-output", unit_index=1))
        await channel.publish(event("token_count", '{"duration":2}', unit_index=2))
        for _ in range(205):
            await channel.publish(event("model_output_thinking", "x", unit_index=3))
        initial = service.read_replay_checkpoint("owner", 91)
        assert initial and len(initial["entries"]) == 4
        shared = subscribe_shared_checkpoint(service, "owner", 91, initial)
        assert "first-code" in await anext(shared)
        await channel.publish(event("parse", "second-code", unit_index=4))
        await channel.publish(event("token_count", '{"duration":3}', unit_index=5))
        for _ in range(205):
            await channel.publish(event("model_output_thinking", "y", unit_index=6))
        await channel.publish(event("parse", "third-code", unit_index=7))
        await channel.publish(event("token_count", '{"duration":4}', unit_index=8))
        await channel.publish(event("final_answer", "finished", unit_index=9))
        client.xtrim(service._stream_key("owner", 91), maxlen=2, approximate=False)
        assert len(service.read_stream_events("owner", 91)) == 2
        channel.complete("failed")
        service.mark_stream_completed("owner", 91, "failed", generation="first")
        shared_events = [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in shared]
        assert [p["content"] for p in shared_events if p.get("type") == "parse"] == ["second-code", "third-code"]
        assert [p["content"] for p in shared_events if p.get("type") == "model_output_thinking"] == ["x" * 205, "y" * 205]
        assert [p["content"] for p in shared_events if p.get("type") == "execution_logs"] == ["first-output"]
        assert sum(json.loads(p["content"])["duration"] for p in shared_events if p.get("type") == "token_count") == 9
        assert shared_events[-1] == {"status": "failed"}
        local_events = [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in
                        channel.subscribe_with_history(include_replay_checkpoint=True)]
        assert [p["content"] for p in local_events if p.get("type") == "parse"] == ["first-code", "second-code", "third-code"]
        assert [p["content"] for p in local_events if p.get("type") == "model_output_thinking"] == ["x" * 205, "y" * 205]
        assert not channel.has_subscribers
        for outcome in ("completed", "stopped"):
            service.reset_stream("owner", 91, generation=outcome)
            assert service.read_replay_checkpoint("owner", 91) is None
            retry = StreamingChannel("91", "owner")
            retry.generation = outcome
            await retry.publish(event("final_answer", outcome))
            before = service.read_replay_checkpoint("owner", 91)
            await channel.publish(event("final_answer", "late old run"))
            assert service.append_stream_event("owner", 91, event("final_answer", "stale"),
                                               generation="first", replay_update={"slot": 0, "append": False,
                                               "payload": {"type": "final_answer", "content": "stale"}}) is None
            assert service.read_replay_checkpoint("owner", 91) == before
            service.mark_stream_completed("owner", 91, outcome, generation=outcome)
            result = [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in
                      subscribe_shared_checkpoint(service, "owner", 91, before)]
            assert result[-1] == {"status": outcome}
            assert [p.get("content") for p in result[:-1]] == [outcome]
