import asyncio

import pytest

from backend.services import runtime_state_service as runtime_state_module
from backend.services.runtime_state_service import RuntimeStateService


class FakeRedisClient:
    def __init__(self):
        self.hsets = []
        self.expires = []
        self.deletes = []
        self.setexes = []
        self.sets = []
        self.xadds = []
        self.xranges = []
        self.xreads = []
        self.hashes = {}
        self.values = {}
        self.stream_events = []
        self.fail_next = set()
        self.pipeline_result = (1, True)

    def _maybe_fail(self, method):
        if method in self.fail_next:
            self.fail_next.remove(method)
            raise RuntimeError(f"{method} failed")

    def hset(self, key, mapping):
        self._maybe_fail("hset")
        self.hsets.append((key, mapping))
        self.hashes.setdefault(key, {}).update(mapping)

    def expire(self, key, ttl):
        self._maybe_fail("expire")
        self.expires.append((key, ttl))

    def delete(self, *keys):
        self._maybe_fail("delete")
        self.deletes.append(keys)
        for key in keys:
            self.hashes.pop(key, None)
            self.values.pop(key, None)

    def hgetall(self, key):
        self._maybe_fail("hgetall")
        return dict(self.hashes.get(key, {}))

    def setex(self, key, ttl, value):
        self._maybe_fail("setex")
        self.setexes.append((key, ttl, value))
        self.values[key] = value
        return True

    def get(self, key):
        self._maybe_fail("get")
        return self.values.get(key)

    def xadd(self, key, values, maxlen=None, approximate=False):
        self._maybe_fail("xadd")
        event_id = f"{len(self.stream_events) + 1}-0"
        self.xadds.append((key, values, maxlen, approximate))
        self.stream_events.append((event_id, values))
        return event_id

    def xrange(self, key, min="-"):
        self._maybe_fail("xrange")
        self.xranges.append((key, min))
        if min == "-":
            return list(self.stream_events)
        if min.startswith("("):
            after_id = min[1:]
            return [(event_id, values) for event_id, values in self.stream_events if event_id > after_id]
        return list(self.stream_events)

    def xread(self, streams, count=100, block=1000):
        self._maybe_fail("xread")
        self.xreads.append((streams, count, block))
        if not self.stream_events:
            return []
        return [(next(iter(streams.keys())), list(self.stream_events[:count]))]

    def set(self, key, value, nx=False, ex=None):
        self._maybe_fail("set")
        self.sets.append((key, value, nx, ex))
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.operations = []

    def incr(self, key):
        self.operations.append(("incr", key))
        return self

    def expire(self, key, ttl):
        self.operations.append(("expire", key, ttl))
        return self

    def execute(self):
        self.client._maybe_fail("pipeline")
        return self.client.pipeline_result


class TestRuntimeStateService(RuntimeStateService):
    def __init__(self, client):
        super().__init__()
        self._fake_client = client

    @property
    def enabled(self):
        return True

    @property
    def client(self):
        return self._fake_client


def test_mark_run_finished_shortens_completed_runtime_key_ttls(monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_COMPLETED_TTL_SECONDS", 300)
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    service.mark_run_finished("user-1", 42, "completed")

    assert client.hsets[0][0] == "runtime:run:user-1:42"
    assert client.hsets[0][1]["status"] == "completed"
    assert set(client.expires) == {
        ("runtime:run:user-1:42", 300),
        ("runtime:cancel:user-1:42", 300),
        ("runtime:stream:user-1:42", 300),
        ("runtime:stream:done:user-1:42", 300),
    }


def test_mark_stream_completed_shortens_completed_runtime_key_ttls(monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_COMPLETED_TTL_SECONDS", 300)
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    service.mark_stream_completed("user-1", 42, "failed", error="model error")

    assert client.hsets[0][0] == "runtime:stream:done:user-1:42"
    assert client.hsets[0][1]["status"] == "failed"
    assert client.hsets[0][1]["error"] == "model error"
    assert set(client.expires) == {
        ("runtime:run:user-1:42", 300),
        ("runtime:cancel:user-1:42", 300),
        ("runtime:stream:user-1:42", 300),
        ("runtime:stream:done:user-1:42", 300),
    }


def test_disabled_service_methods_return_without_client(monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STATE_REDIS_URL", "")
    service = RuntimeStateService()

    assert service.enabled is False
    assert service.get_run_state("user-1", 42) == {}
    assert service.set_cancel_signal("user-1", 42) is False
    assert service.is_cancelled("user-1", 42) is False
    assert service.append_stream_event("user-1", 42, "chunk") is None
    assert service.get_stream_status("user-1", 42) == {}
    assert service.read_stream_events("user-1", 42) == []
    assert service.wait_for_stream_events("user-1", 42, "0-0") == []
    service.reset_stream("user-1", 42)
    service.register_run("user-1", 42)
    service.mark_run_finished("user-1", 42, "completed")
    service.mark_stream_completed("user-1", 42, "completed")


def test_client_property_requires_redis_url(monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STATE_REDIS_URL", "")
    service = RuntimeStateService()

    with pytest.raises(ValueError, match="RUNTIME_STATE_REDIS_URL"):
        _ = service.client


def test_client_property_requires_redis_package(monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STATE_REDIS_URL", "redis://test")
    monkeypatch.setattr(runtime_state_module, "redis", None)
    service = RuntimeStateService()

    with pytest.raises(ValueError, match="redis package"):
        _ = service.client


def test_client_property_lazily_creates_redis_client(monkeypatch):
    fake_client = FakeRedisClient()
    fake_redis = type("FakeRedisModule", (), {
        "from_url": staticmethod(lambda url, **kwargs: fake_client)
    })
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STATE_REDIS_URL", "redis://test")
    monkeypatch.setattr(runtime_state_module, "redis", fake_redis)
    service = RuntimeStateService()

    assert service.client is fake_client
    assert service.client is fake_client


def test_reset_stream_deletes_stream_and_done_keys():
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    service.reset_stream("user-1", 42)

    assert client.deletes == [("runtime:stream:user-1:42", "runtime:stream:done:user-1:42")]


def test_reset_stream_swallows_redis_errors(caplog):
    client = FakeRedisClient()
    client.fail_next.add("delete")
    service = TestRuntimeStateService(client)

    service.reset_stream("user-1", 42)

    assert "Failed to reset runtime stream state" in caplog.text


def test_register_run_writes_owner_status_ttl_and_clears_cancel(monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_RUN_TTL_SECONDS", 123)
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    service.register_run("user-1", 42, message_id=99)

    key, mapping = client.hsets[0]
    assert key == "runtime:run:user-1:42"
    assert mapping["status"] == "running"
    assert mapping["message_id"] == "99"
    assert ("runtime:run:user-1:42", 123) in client.expires
    assert ("runtime:cancel:user-1:42",) in client.deletes


def test_register_run_swallows_redis_errors(caplog):
    client = FakeRedisClient()
    client.fail_next.add("hset")
    service = TestRuntimeStateService(client)

    service.register_run("user-1", 42)

    assert "Failed to register runtime run state" in caplog.text


def test_get_run_state_returns_hash_and_handles_errors(caplog):
    client = FakeRedisClient()
    client.hashes["runtime:run:user-1:42"] = {"status": "running"}
    service = TestRuntimeStateService(client)

    assert service.get_run_state("user-1", 42) == {"status": "running"}

    client.fail_next.add("hgetall")
    assert service.get_run_state("user-1", 42) == {}
    assert "Failed to get runtime run state" in caplog.text


def test_mark_run_finished_swallows_redis_errors(caplog):
    client = FakeRedisClient()
    client.fail_next.add("hset")
    service = TestRuntimeStateService(client)

    service.mark_run_finished("user-1", 42, "failed")

    assert "Failed to mark runtime run state as finished" in caplog.text


def test_cancel_signal_set_and_read_with_error_paths(caplog):
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    assert service.set_cancel_signal("user-1", 42) is True
    assert client.setexes[0][0] == "runtime:cancel:user-1:42"
    assert service.is_cancelled("user-1", 42) is True

    client.fail_next.add("setex")
    assert service.set_cancel_signal("user-1", 42) is False
    client.fail_next.add("get")
    assert service.is_cancelled("user-1", 42) is False
    assert "Failed to set runtime cancel signal" in caplog.text
    assert "Failed to read runtime cancel signal" in caplog.text


def test_append_stream_event_success_and_error(monkeypatch, caplog):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STREAM_MAX_LEN", 10)
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STREAM_TTL_SECONDS", 20)
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    event_id = service.append_stream_event("user-1", 42, "chunk")

    assert event_id == "1-0"
    assert client.xadds == [("runtime:stream:user-1:42", {"chunk": "chunk"}, 10, True)]
    assert ("runtime:stream:user-1:42", 20) in client.expires

    client.fail_next.add("xadd")
    assert service.append_stream_event("user-1", 42, "chunk") is None
    assert "Failed to append runtime stream event" in caplog.text


def test_mark_stream_completed_without_error_and_error_path(caplog):
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    service.mark_stream_completed("user-1", 42, "completed")

    assert client.hsets[0][0] == "runtime:stream:done:user-1:42"
    assert client.hsets[0][1]["status"] == "completed"
    assert "error" not in client.hsets[0][1]

    client.fail_next.add("hset")
    service.mark_stream_completed("user-1", 42, "failed")
    assert "Failed to mark runtime stream completed" in caplog.text


def test_stream_status_returns_hash_and_handles_errors(caplog):
    client = FakeRedisClient()
    client.hashes["runtime:stream:done:user-1:42"] = {"status": "completed"}
    service = TestRuntimeStateService(client)

    assert service.get_stream_status("user-1", 42) == {"status": "completed"}

    client.fail_next.add("hgetall")
    assert service.get_stream_status("user-1", 42) == {}
    assert "Failed to get runtime stream status" in caplog.text


def test_read_stream_events_with_and_without_after_id_and_error(caplog):
    client = FakeRedisClient()
    client.stream_events = [
        ("1-0", {"chunk": "first"}),
        ("2-0", {"other": "missing chunk"}),
    ]
    service = TestRuntimeStateService(client)

    assert service.read_stream_events("user-1", 42) == [("1-0", "first"), ("2-0", "")]
    assert client.xranges[-1] == ("runtime:stream:user-1:42", "-")
    assert service.read_stream_events("user-1", 42, after_id="1-0") == [("2-0", "")]
    assert client.xranges[-1] == ("runtime:stream:user-1:42", "(1-0")

    client.fail_next.add("xrange")
    assert service.read_stream_events("user-1", 42) == []
    assert "Failed to read runtime stream events" in caplog.text


def test_wait_for_stream_events_success_empty_and_error(caplog):
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    assert service.wait_for_stream_events("user-1", 42, "0-0") == []

    client.stream_events = [("1-0", {"chunk": "first"}), ("2-0", {"other": "missing"})]
    assert service.wait_for_stream_events("user-1", 42, "0-0", block_ms=5, count=2) == [
        ("1-0", "first"),
        ("2-0", ""),
    ]
    assert client.xreads[-1] == ({"runtime:stream:user-1:42": "0-0"}, 2, 5)

    client.fail_next.add("xread")
    assert service.wait_for_stream_events("user-1", 42, "0-0") == []
    assert "Failed to wait for runtime stream events" in caplog.text


def test_idempotency_acquire_and_release():
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)
    redis_key = service._idempotency_key("request-key")

    assert service.acquire_idempotency("request-key", 60) is True
    assert client.sets[-1] == (redis_key, service._pod_name, True, 60)
    assert service.acquire_idempotency("request-key", 60) is False

    service.release_idempotency("request-key")

    assert (redis_key,) in client.deletes


def test_consume_rate_limit_success_and_limit_exceeded(monkeypatch):
    monkeypatch.setattr(runtime_state_module.time, "time", lambda: 120.0)
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    assert service.consume_rate_limit("tenant-1", 2) == 1

    client.pipeline_result = (3, True)
    with pytest.raises(ValueError, match="rate limit exceeded"):
        service.consume_rate_limit("tenant-1", 2)


def test_async_wrappers_delegate_to_sync_methods(monkeypatch):
    client = FakeRedisClient()
    service = TestRuntimeStateService(client)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(runtime_state_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        service,
        "reset_stream",
        lambda user_id, conversation_id: client.values.setdefault("reset", True),
    )
    monkeypatch.setattr(service, "get_run_state", lambda user_id, conversation_id: {"status": "running"})
    monkeypatch.setattr(service, "is_cancelled", lambda user_id, conversation_id: True)
    monkeypatch.setattr(service, "append_stream_event", lambda user_id, conversation_id, chunk: "1-0")
    monkeypatch.setattr(
        service,
        "mark_stream_completed",
        lambda *args, **kwargs: client.values.setdefault("done", True),
    )
    monkeypatch.setattr(service, "get_stream_status", lambda user_id, conversation_id: {"status": "completed"})
    monkeypatch.setattr(
        service,
        "read_stream_events",
        lambda user_id, conversation_id, after_id=None: [("1-0", "chunk")],
    )
    monkeypatch.setattr(service, "wait_for_stream_events", lambda *args, **kwargs: [("2-0", "chunk2")])
    monkeypatch.setattr(service, "acquire_idempotency", lambda key, ttl_seconds: True)
    monkeypatch.setattr(service, "release_idempotency", lambda key: client.values.setdefault("released", key))
    monkeypatch.setattr(service, "consume_rate_limit", lambda tenant_id, limit_per_minute: 1)

    async def run_checks():
        await service.reset_stream_async("user-1", 42)
        assert await service.get_run_state_async("user-1", 42) == {"status": "running"}
        assert await service.is_cancelled_async("user-1", 42) is True
        assert await service.append_stream_event_async("user-1", 42, "chunk") == "1-0"
        await service.mark_stream_completed_async("user-1", 42, "completed")
        assert await service.get_stream_status_async("user-1", 42) == {"status": "completed"}
        assert await service.read_stream_events_async("user-1", 42) == [("1-0", "chunk")]
        assert await service.wait_for_stream_events_async("user-1", 42, "1-0") == [("2-0", "chunk2")]
        assert await service.acquire_idempotency_async("request-key", 60) is True
        await service.release_idempotency_async("request-key")
        assert await service.consume_rate_limit_async("tenant-1", 2) == 1

    asyncio.run(run_checks())
