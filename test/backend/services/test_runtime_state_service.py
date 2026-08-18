import asyncio

import pytest

from consts.exceptions import DistributedStateUnavailable
from backend.services import runtime_state_service as runtime_state_module
from backend.services.runtime_state_service import (
    RuntimeExecutionSuperseded,
    RuntimeStateService,
)


class FakePipeline:
    def __init__(self, client):
        self.client = client

    def incr(self, key):
        self.key = key
        return self

    def expire(self, key, ttl):
        self.ttl = (key, ttl)
        return self

    def execute(self):
        self.client._maybe_fail("pipeline")
        current = int(self.client.values.get(self.key, 0)) + 1
        self.client.values[self.key] = str(current)
        self.client.ttls[self.key] = self.ttl[1]
        return current, True


class FakeRedisClient:
    def __init__(self):
        self.hashes = {}
        self.values = {}
        self.streams = {}
        self.ttls = {}
        self.fail_next = set()
        self.eval_calls = []
        self.ping_result = True

    def _maybe_fail(self, method):
        if method in self.fail_next:
            self.fail_next.remove(method)
            raise RuntimeError(f"{method} failed")

    def ping(self):
        self._maybe_fail("ping")
        return self.ping_result

    def eval(self, script, numkeys, *values):
        self._maybe_fail("eval")
        keys = list(values[:numkeys])
        args = list(values[numkeys:])
        self.eval_calls.append((script, keys, args))

        if "redis.call('DEL', KEYS[1], KEYS[2], KEYS[3], KEYS[4])" in script:
            for key in keys:
                self.hashes.pop(key, None)
                self.values.pop(key, None)
                self.streams.pop(key, None)
                self.ttls.pop(key, None)
            execution_id, now, ttl = args
            payload = {
                "execution_id": str(execution_id),
                "status": "running",
                "started_at": str(now),
                "updated_at": str(now),
            }
            self.hashes[keys[0]] = payload
            self.ttls[keys[0]] = int(ttl)
            return execution_id

        if "redis.call('HSET', KEYS[4]" in script:
            execution_id, status, now, completed_ttl, error, stream_ttl = args
            if self.hashes.get(keys[0], {}).get("execution_id") != execution_id:
                return 0
            current_status = self.hashes.get(keys[0], {}).get("status")
            if current_status != "running":
                return int(current_status == status)
            self.hashes[keys[0]].update({"status": status, "updated_at": now})
            self.hashes[keys[3]] = {
                "execution_id": execution_id,
                "status": status,
                "updated_at": now,
            }
            if error:
                self.hashes[keys[0]]["error"] = error
                self.hashes[keys[3]]["error"] = error
            self.values.pop(keys[1], None)
            self.ttls.pop(keys[1], None)
            self.ttls[keys[0]] = int(completed_ttl)
            self.ttls[keys[2]] = int(stream_ttl)
            self.ttls[keys[3]] = int(completed_ttl)
            return 1

        if "local execution_id = redis.call('HGET'" in script:
            execution_id = self.hashes.get(keys[0], {}).get("execution_id")
            if execution_id is None or self.hashes.get(keys[0], {}).get("status") != "running":
                return 0
            self.values[keys[1]] = execution_id
            self.ttls[keys[1]] = int(args[0])
            return 1

        if "redis.call('GET', KEYS[1]) == ARGV[1]" in script:
            return int(self.values.get(keys[0]) == args[0])

        if "return redis.call('DEL', KEYS[1])" in script:
            if self.values.get(keys[0]) != args[0]:
                return 0
            self.values.pop(keys[0], None)
            self.ttls.pop(keys[0], None)
            return 1

        if "redis.call('XADD'" in script:
            execution_id, chunk, _max_len, ttl = args
            run_state = self.hashes.get(keys[0], {})
            if run_state.get("execution_id") != execution_id or run_state.get("status") != "running":
                return None
            events = self.streams.setdefault(keys[1], [])
            event_id = f"{len(events) + 1}-0"
            events.append((event_id, {"chunk": chunk}))
            self.ttls[keys[1]] = int(ttl)
            return event_id

        execution_id, now, ttl = args
        run_state = self.hashes.get(keys[0], {})
        if run_state.get("execution_id") != execution_id or run_state.get("status") != "running":
            return 0
        self.hashes[keys[0]]["updated_at"] = now
        self.ttls[keys[0]] = int(ttl)
        return 1

    def delete(self, *keys):
        self._maybe_fail("delete")
        for key in keys:
            self.hashes.pop(key, None)
            self.values.pop(key, None)
            self.streams.pop(key, None)
            self.ttls.pop(key, None)

    def hgetall(self, key):
        self._maybe_fail("hgetall")
        return dict(self.hashes.get(key, {}))

    def xrange(self, key, min="-"):
        self._maybe_fail("xrange")
        events = list(self.streams.get(key, []))
        if min.startswith("("):
            after_id = min[1:]
            return [(event_id, values) for event_id, values in events if event_id > after_id]
        return events

    def xread(self, streams, count=100, block=1000):
        self._maybe_fail("xread")
        key, last_id = next(iter(streams.items()))
        events = [event for event in self.streams.get(key, []) if event[0] > last_id][:count]
        return [(key, events)] if events else []

    def set(self, key, value, nx=False, ex=None):
        self._maybe_fail("set")
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def pipeline(self):
        return FakePipeline(self)


@pytest.fixture
def client():
    return FakeRedisClient()


@pytest.fixture
def service(client):
    return RuntimeStateService(client=client)


def test_register_run_replaces_old_state_without_owner_pod(service, client, monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_RUN_TTL_SECONDS", 60)
    client.hashes["runtime:run:user-1:42"] = {"execution_id": "old"}
    client.values["runtime:cancel:user-1:42"] = "old"
    client.streams["runtime:stream:user-1:42"] = [("1-0", {"chunk": "old"})]

    execution_id = service.register_run("user-1", 42, execution_id="new")

    assert execution_id == "new"
    assert client.hashes["runtime:run:user-1:42"] == {
        "execution_id": "new",
        "status": "running",
        "started_at": client.hashes["runtime:run:user-1:42"]["started_at"],
        "updated_at": client.hashes["runtime:run:user-1:42"]["updated_at"],
    }
    assert "owner_pod" not in client.hashes["runtime:run:user-1:42"]
    assert "runtime:cancel:user-1:42" not in client.values
    assert "runtime:stream:user-1:42" not in client.streams
    assert client.ttls["runtime:run:user-1:42"] == 60


def test_execution_id_fences_heartbeat_and_finish(service, client):
    service.register_run("user-1", 42, execution_id="first")
    service.register_run("user-1", 42, execution_id="second")

    assert service.heartbeat_run("user-1", 42, "first") is False
    assert service.mark_run_finished("user-1", 42, "first", "completed") is False
    assert client.hashes["runtime:run:user-1:42"]["status"] == "running"

    assert service.heartbeat_run("user-1", 42, "second") is True
    assert service.mark_run_finished("user-1", 42, "second", "completed") is True
    assert client.hashes["runtime:run:user-1:42"]["status"] == "completed"
    assert client.hashes["runtime:stream:done:user-1:42"]["execution_id"] == "second"


def test_finish_sets_terminal_state_error_and_completed_ttl(service, client, monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_COMPLETED_TTL_SECONDS", 300)
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STREAM_TTL_SECONDS", 86400)
    service.register_run("user-1", 42, execution_id="run-1")
    service.append_stream_event("user-1", 42, "run-1", "chunk")
    service.set_cancel_signal("user-1", 42)

    assert service.mark_run_finished("user-1", 42, "run-1", "failed", "model error") is True

    assert client.hashes["runtime:stream:done:user-1:42"]["status"] == "failed"
    assert client.hashes["runtime:stream:done:user-1:42"]["error"] == "model error"
    assert client.ttls["runtime:run:user-1:42"] == 300
    assert client.ttls["runtime:stream:done:user-1:42"] == 300
    assert client.ttls["runtime:stream:user-1:42"] == 86400
    assert "runtime:cancel:user-1:42" not in client.values


def test_terminal_run_rejects_heartbeat_cancel_and_append(service):
    service.register_run("user-1", 42, execution_id="run-1")
    assert service.mark_run_finished("user-1", 42, "run-1", "completed") is True
    assert service.mark_run_finished("user-1", 42, "run-1", "completed") is True
    assert service.heartbeat_run("user-1", 42, "run-1") is False
    assert service.set_cancel_signal("user-1", 42) is False
    with pytest.raises(RuntimeExecutionSuperseded):
        service.append_stream_event("user-1", 42, "run-1", "late")


def test_finish_rejects_unknown_terminal_status(service):
    service.register_run("user-1", 42, execution_id="run-1")
    with pytest.raises(ValueError, match="Unsupported runtime terminal status"):
        service.mark_run_finished("user-1", 42, "run-1", "running")


def test_cancel_signal_is_bound_to_current_execution(service, client, monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_CANCEL_TTL_SECONDS", 60)
    assert service.set_cancel_signal("user-1", 42) is False

    service.register_run("user-1", 42, execution_id="run-1")
    assert service.set_cancel_signal("user-1", 42) is True
    assert client.values["runtime:cancel:user-1:42"] == "run-1"
    assert client.ttls["runtime:cancel:user-1:42"] == 60
    assert service.is_cancelled("user-1", 42, "run-1") is True
    assert service.is_cancelled("user-1", 42, "run-2") is False


def test_stream_append_is_fenced_and_can_be_replayed(service, client, monkeypatch):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STREAM_TTL_SECONDS", 120)
    service.register_run("user-1", 42, execution_id="run-1")

    assert service.append_stream_event("user-1", 42, "run-1", "chunk-1") == "1-0"
    assert service.append_stream_event("user-1", 42, "run-1", "chunk-2") == "2-0"
    assert service.read_stream_events("user-1", 42) == [("1-0", "chunk-1"), ("2-0", "chunk-2")]
    assert service.read_stream_events("user-1", 42, after_id="1-0") == [("2-0", "chunk-2")]
    assert service.wait_for_stream_events("user-1", 42, "1-0") == [("2-0", "chunk-2")]
    assert client.ttls["runtime:stream:user-1:42"] == 120

    with pytest.raises(RuntimeExecutionSuperseded):
        service.append_stream_event("user-1", 42, "old-run", "stale")


@pytest.mark.parametrize(
    ("method", "args", "failure"),
    [
        ("register_run", ("user-1", 42), "eval"),
        ("get_run_state", ("user-1", 42), "hgetall"),
        ("read_stream_events", ("user-1", 42), "xrange"),
        ("wait_for_stream_events", ("user-1", 42, "0-0"), "xread"),
        ("acquire_idempotency", ("key", 30), "set"),
        ("consume_rate_limit", ("tenant", 10), "pipeline"),
    ],
)
def test_redis_failures_raise_distributed_state_unavailable(service, client, method, args, failure):
    client.fail_next.add(failure)
    with pytest.raises(DistributedStateUnavailable):
        getattr(service, method)(*args)


def test_missing_configuration_and_ping_failure_raise_distributed_error(monkeypatch, client):
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STATE_REDIS_URL", "")
    with pytest.raises(DistributedStateUnavailable, match="RUNTIME_STATE_REDIS_URL"):
        RuntimeStateService().ping()

    client.ping_result = False
    with pytest.raises(DistributedStateUnavailable, match="Redis PING"):
        RuntimeStateService(client=client).ping()


def test_idempotency_and_rate_limit_use_redis(service):
    token = service.acquire_idempotency("request", 30)
    assert token
    assert service.acquire_idempotency("request", 30) is None
    assert service.release_idempotency("request", "wrong-token") is False
    assert service.acquire_idempotency("request", 30) is None
    assert service.release_idempotency("request", token) is True
    assert service.acquire_idempotency("request", 30)

    assert service.consume_rate_limit("tenant", 1) == 1
    with pytest.raises(ValueError, match="rate limit exceeded"):
        service.consume_rate_limit("tenant", 1)


def test_status_reads_are_strict(service, client):
    service.register_run("user-1", 42, execution_id="run-1")
    service.append_stream_event("user-1", 42, "run-1", "chunk")
    service.mark_run_finished("user-1", 42, "run-1", "completed")
    assert service.get_run_state("user-1", 42)["status"] == "completed"
    assert service.get_stream_status("user-1", 42)["status"] == "completed"

def test_client_is_created_from_configured_url(monkeypatch, client):
    fake_redis_module = type(
        "FakeRedisModule",
        (),
        {"from_url": staticmethod(lambda *args, **kwargs: client)},
    )
    monkeypatch.setattr(runtime_state_module, "redis", fake_redis_module)
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STATE_REDIS_URL", "redis://example")

    service = RuntimeStateService()

    assert service.client is client
    assert service.client is client


def test_client_creation_failures_are_distributed_errors(monkeypatch):
    class FailingRedisModule:
        @staticmethod
        def from_url(*args, **kwargs):
            raise RuntimeError("connection setup failed")

    monkeypatch.setattr(runtime_state_module, "redis", None)
    monkeypatch.setattr(runtime_state_module, "RUNTIME_STATE_REDIS_URL", "redis://example")
    with pytest.raises(DistributedStateUnavailable, match="redis package"):
        RuntimeStateService().client

    monkeypatch.setattr(runtime_state_module, "redis", FailingRedisModule)
    with pytest.raises(DistributedStateUnavailable, match="create Redis client"):
        RuntimeStateService().client


def test_async_wrappers_preserve_execution_contract(service):
    async def run():
        assert await service.ping_async() is True
        execution_id = await service.register_run_async("user-1", 42, execution_id="run-1")
        assert execution_id == "run-1"
        assert (await service.get_run_state_async("user-1", 42))["execution_id"] == "run-1"
        assert await service.heartbeat_run_async("user-1", 42, "run-1") is True
        assert await service.is_cancelled_async("user-1", 42, "run-1") is False
        assert await service.set_cancel_signal_async("user-1", 42) is True
        assert await service.is_cancelled_async("user-1", 42, "run-1") is True
        assert await service.append_stream_event_async("user-1", 42, "run-1", "chunk") == "1-0"
        assert await service.read_stream_events_async("user-1", 42) == [("1-0", "chunk")]
        assert await service.wait_for_stream_events_async("user-1", 42, "0-0") == [("1-0", "chunk")]
        assert service.mark_stream_completed("user-1", 42, "run-1", "completed") is True
        assert (await service.get_stream_status_async("user-1", 42))["status"] == "completed"

        execution_id = await service.register_run_async("user-1", 42, execution_id="run-2")
        assert execution_id == "run-2"
        assert await service.mark_stream_completed_async("user-1", 42, "run-2", "stopped") is True

        token = await service.acquire_idempotency_async("request", 30)
        assert token
        assert await service.release_idempotency_async("request", token) is True
        assert await service.consume_rate_limit_async("tenant", 2) == 1

    asyncio.run(run())
