from types import SimpleNamespace

import pytest

from sdk.nexent.memory import memory_core


def _memory_config(*, telemetry_enabled: bool):
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": "test-llm",
                "api_key": "test-key",
                "openai_base_url": "http://llm.test",
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "test-embedding",
                "api_key": "test-key",
                "openai_base_url": "http://embedding.test",
                "embedding_dims": 8,
            },
        },
        "vector_store": {
            "provider": "elasticsearch",
            "config": {
                "collection_name": "test-memory",
                "host": "localhost",
                "port": 9200,
                "embedding_model_dims": 8,
                "api_key": "test-key",
            },
        },
        "telemetry": {"enabled": telemetry_enabled},
    }


@pytest.fixture(autouse=True)
def _clear_memory_cache():
    memory_core._MEMORY_CACHE.clear()
    memory_core._CACHE_LOCKS.clear()
    yield
    memory_core._MEMORY_CACHE.clear()
    memory_core._CACHE_LOCKS.clear()


@pytest.mark.asyncio
async def test_disabled_telemetry_skips_mem0_capture_during_and_after_creation(monkeypatch):
    captured_events = []
    created_memory = SimpleNamespace()

    def capture_event(event_name, memory_instance, additional_data=None):
        captured_events.append((event_name, memory_instance, additional_data))

    class FakeAsyncMemory:
        @classmethod
        async def from_config(cls, config):
            memory_core._capture_mem0_event("mem0.init", created_memory)
            return created_memory

    monkeypatch.setattr(memory_core, "_ORIGINAL_MEM0_CAPTURE_EVENT", capture_event)
    monkeypatch.setattr(memory_core, "AsyncMemory", FakeAsyncMemory)
    monkeypatch.setattr(memory_core, "EmbedderAdaptor", lambda config: object())

    memory = await memory_core.get_memory_instance(
        _memory_config(telemetry_enabled=False)
    )
    memory_core._capture_mem0_event("mem0.search", memory)

    assert memory is created_memory
    assert memory._nexent_telemetry_disabled is True
    assert captured_events == []


@pytest.mark.asyncio
async def test_enabled_telemetry_preserves_mem0_capture(monkeypatch):
    captured_events = []
    created_memory = SimpleNamespace()

    def capture_event(event_name, memory_instance, additional_data=None):
        captured_events.append((event_name, memory_instance, additional_data))

    class FakeAsyncMemory:
        @classmethod
        async def from_config(cls, config):
            memory_core._capture_mem0_event("mem0.init", created_memory)
            return created_memory

    monkeypatch.setattr(memory_core, "_ORIGINAL_MEM0_CAPTURE_EVENT", capture_event)
    monkeypatch.setattr(memory_core, "AsyncMemory", FakeAsyncMemory)
    monkeypatch.setattr(memory_core, "EmbedderAdaptor", lambda config: object())

    memory = await memory_core.get_memory_instance(
        _memory_config(telemetry_enabled=True)
    )
    memory_core._capture_mem0_event("mem0.search", memory)

    assert [event[0] for event in captured_events] == ["mem0.init", "mem0.search"]
    assert not hasattr(memory, "_nexent_telemetry_disabled")
