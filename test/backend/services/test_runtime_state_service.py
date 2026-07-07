from backend.services import runtime_state_service as runtime_state_module
from backend.services.runtime_state_service import RuntimeStateService


class FakeRedisClient:
    def __init__(self):
        self.hsets = []
        self.expires = []

    def hset(self, key, mapping):
        self.hsets.append((key, mapping))

    def expire(self, key, ttl):
        self.expires.append((key, ttl))


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
