"""Unit tests for ``backend.services.memory_backend_adapter`` (Phase 2).

These tests exercise the async bridge between the SDK ``MemoryService``
facade and the backend services. Both sides are stubbed, so the tests
focus on argument translation and policy enforcement.
"""

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# Path setup
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# ---------------------------------------------------------------------------
# CRITICAL: Stub nexent package hierarchy FIRST, before any real module
# that imports nexent.storage can be loaded.
# ``__path__`` on each stub package is required so Python treats it as a
# package and can resolve submodules during relative imports.
# ---------------------------------------------------------------------------
nexent_pkg = types.ModuleType("nexent")
nexent_pkg.__path__ = []

memory_pkg = types.ModuleType("nexent.memory")
memory_pkg.__path__ = []
nexent_pkg.memory = memory_pkg

memory_models = types.ModuleType("nexent.memory.models")
memory_policy = types.ModuleType("nexent.memory.policy")
memory_service = types.ModuleType("nexent.memory.service")
embedding_model = types.ModuleType("nexent.memory.embedding_model")
memory_pkg.models = memory_models
memory_pkg.policy = memory_policy
memory_pkg.service = memory_service
memory_pkg.embedding_model = embedding_model

sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg
sys.modules["nexent.memory.models"] = memory_models
sys.modules["nexent.memory.policy"] = memory_policy
sys.modules["nexent.memory.service"] = memory_service
sys.modules["nexent.memory.embedding_model"] = embedding_model


# Only stub the ONE module that blocks everything else from loading:
# ``nexent.storage`` is an optional dependency not installed in the test env.
# Stub as a package so submodules like ``nexent.storage.storage_client_factory`` resolve.
_storage_pkg = types.ModuleType("nexent.storage")
_storage_pkg.__path__ = []
_storage_factory = types.ModuleType("nexent.storage.storage_client_factory")
_storage_factory.create_storage_client_from_config = MagicMock()
_storage_factory.MinIOStorageConfig = type("MinIOStorageConfig", (), {})
_storage_pkg.storage_client_factory = _storage_factory
sys.modules["nexent.storage"] = _storage_pkg
sys.modules["nexent.storage.storage_client_factory"] = _storage_factory


class _EnumBase:
    _registry: dict = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._registry = {}

    def __new__(cls, value):
        inst = cls._registry.get(value)
        if inst is None:
            raise ValueError(value)
        return inst

    def __init__(self, name=None, value=None):
        if name is not None:
            self.name = name
            self.value = value

    def __repr__(self):
        return f"{type(self).__name__}.{self.name}"


class MemoryLayer(_EnumBase):
    pass


MemoryLayer.TENANT = object.__new__(MemoryLayer)
MemoryLayer.TENANT.name = "tenant"
MemoryLayer.TENANT.value = "tenant"
MemoryLayer.USER = object.__new__(MemoryLayer)
MemoryLayer.USER.name = "user"
MemoryLayer.USER.value = "user"
MemoryLayer.AGENT = object.__new__(MemoryLayer)
MemoryLayer.AGENT.name = "agent"
MemoryLayer.AGENT.value = "agent"
MemoryLayer.tenant = MemoryLayer.TENANT
MemoryLayer.user = MemoryLayer.USER
MemoryLayer.agent = MemoryLayer.AGENT
MemoryLayer._registry = {"tenant": MemoryLayer.TENANT, "user": MemoryLayer.USER, "agent": MemoryLayer.AGENT}


class MemorySearchRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemorySearchResult:
    def __init__(self, **kwargs):
        kwargs.setdefault("source", "internal")
        kwargs.setdefault("is_external", False)
        kwargs.setdefault("metadata", {})
        self.__dict__.update(kwargs)


class MemoryIngestUnit:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemoryIngestRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


memory_models.MemoryLayer = MemoryLayer
class MemoryType(_EnumBase):
    pass


MemoryType.SHORT_TERM = object.__new__(MemoryType)
MemoryType.SHORT_TERM.name = "short_term"
MemoryType.SHORT_TERM.value = "short_term"
MemoryType.LONG_TERM = object.__new__(MemoryType)
MemoryType.LONG_TERM.name = "long_term"
MemoryType.LONG_TERM.value = "long_term"
MemoryType.short_term = MemoryType.SHORT_TERM
MemoryType.long_term = MemoryType.LONG_TERM
MemoryType._registry = {"short_term": MemoryType.SHORT_TERM, "long_term": MemoryType.LONG_TERM}


memory_models.MemoryType = MemoryType
memory_models.MemorySearchRequest = MemorySearchRequest
memory_models.MemorySearchResult = MemorySearchResult
memory_models.MemoryIngestUnit = MemoryIngestUnit
memory_models.MemoryIngestRequest = MemoryIngestRequest


class EmbeddingModelInfo:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def get_index_name(self):
        return "mem_idx"


embedding_model.EmbeddingModelInfo = EmbeddingModelInfo


class MemoryService:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


memory_service.MemoryService = MemoryService


# ---------------------------------------------------------------------------
# Stub services modules
# ---------------------------------------------------------------------------
record_service_mod = types.ModuleType("services.memory_record_service")
retrieval_service_mod = types.ModuleType("services.memory_retrieval_service")
external_provider_service_mod = types.ModuleType("services.memory_external_provider_service")
ingestion_event_service_mod = types.ModuleType("services.memory_ingestion_event_service")

record_service_mod.get_memory_record_service = MagicMock(
    name="get_memory_record_service"
)
record_service_mod.MemoryRecordError = type("MemoryRecordError", (Exception,), {})
record_service_mod._resolve_tenant_embedding_model_info = MagicMock(
    name="_resolve_tenant_embedding_model_info",
    return_value=EmbeddingModelInfo(),
)
retrieval_service_mod.get_memory_retrieval_service = MagicMock(
    name="get_memory_retrieval_service"
)
external_provider_service_mod.get_memory_external_provider_service = MagicMock(
    name="get_memory_external_provider_service"
)
ingestion_event_service_mod.MemoryIngestionEventService = MagicMock(
    name="MemoryIngestionEventService"
)

sys.modules["services.memory_record_service"] = record_service_mod
sys.modules["services.memory_retrieval_service"] = retrieval_service_mod
sys.modules["backend.services.memory_record_service"] = record_service_mod
sys.modules["backend.services.memory_retrieval_service"] = retrieval_service_mod
sys.modules["services.memory_external_provider_service"] = external_provider_service_mod
sys.modules["backend.services.memory_external_provider_service"] = external_provider_service_mod
sys.modules["services.memory_ingestion_event_service"] = ingestion_event_service_mod
sys.modules["backend.services.memory_ingestion_event_service"] = ingestion_event_service_mod


from backend.services import memory_backend_adapter


@pytest.fixture
def fake_record_service():
    svc = MagicMock()
    svc.create_memory = MagicMock(
        return_value={"memory_id": 1, "event": "ADD"}
    )
    record_service_mod.get_memory_record_service.return_value = svc
    return svc


@pytest.fixture
def fake_retrieval_service():
    svc = MagicMock()
    fake_result = MemorySearchResult(memory_id="1", score=0.9, content="x", layer=MemoryLayer.agent)
    async def _search(*args, **kwargs):
        return [fake_result]
    svc.search = _search
    retrieval_service_mod.get_memory_retrieval_service.return_value = svc
    return svc


def test_backend_store_hook_forwards_layer_and_type(fake_record_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "hi",
        "layer": "agent",
        "memory_type": "short_term",
        "agent_id": "a1",
        "conversation_id": "c1",
        "idempotency_key": "k1",
    }
    result = asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_store_hook(payload)
    )
    assert result["memory_id"] == 1
    fake_record_service.create_memory.assert_called_once()
    kwargs = fake_record_service.create_memory.call_args.kwargs
    assert kwargs["layer"] == "agent"
    assert kwargs["memory_type"] == "short_term"
    assert kwargs["actor"] == "agent"


def test_backend_store_hook_normalizes_integer_conversation_id(fake_record_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "hi",
        "layer": "agent",
        "memory_type": "short_term",
        "agent_id": "a1",
        "conversation_id": 167,
        "idempotency_key": "k1",
    }

    asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_store_hook(payload)
    )

    kwargs = fake_record_service.create_memory.call_args.kwargs
    assert kwargs["conversation_id"] == "167"


def test_backend_store_hook_fails_without_embedding_model(fake_record_service):
    resolver = record_service_mod._resolve_tenant_embedding_model_info
    previous = resolver.return_value
    resolver.return_value = None
    try:
        with pytest.raises(record_service_mod.MemoryRecordError):
            asyncio.get_event_loop().run_until_complete(
                memory_backend_adapter._backend_store_hook(
                    {
                        "tenant_id": "t1",
                        "user_id": "u1",
                        "content": "hi",
                        "layer": "agent",
                        "memory_type": "short_term",
                    }
                )
            )
        fake_record_service.create_memory.assert_not_called()
    finally:
        resolver.return_value = previous


def test_backend_search_hook_returns_serialized_results(fake_retrieval_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "agent_id": "a1",
        "conversation_id": None,
        "layers": [MemoryLayer.agent],
        "query": "hi",
        "top_k": 5,
        "threshold": 0.5,
    }
    results = asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_search_hook(payload)
    )
    assert len(results) == 1
    assert results[0]["memory_id"] == "1"
    assert results[0]["layer"] == "agent"


def test_backend_search_hook_returns_empty_without_embedding_model(
    fake_retrieval_service,
):
    retrieval_service_mod.get_memory_retrieval_service.reset_mock()
    resolver = record_service_mod._resolve_tenant_embedding_model_info
    previous = resolver.return_value
    resolver.return_value = None
    try:
        results = asyncio.get_event_loop().run_until_complete(
            memory_backend_adapter._backend_search_hook(
                {
                    "tenant_id": "t1",
                    "user_id": "u1",
                    "query": "hi",
                }
            )
        )
        assert results == []
        retrieval_service_mod.get_memory_retrieval_service.assert_not_called()
    finally:
        resolver.return_value = previous


def test_build_memory_service_for_agent_returns_memory_service():
    svc = memory_backend_adapter.build_memory_service_for_agent(
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
    )
    assert isinstance(svc, MemoryService)
    assert callable(svc.kwargs.get("backend_store"))
    assert callable(svc.kwargs.get("backend_search"))


def test_build_memory_service_for_dreaming_returns_memory_service():
    svc = memory_backend_adapter.build_memory_service_for_dreaming()
    assert isinstance(svc, MemoryService)
    assert callable(svc.kwargs.get("backend_store"))
    assert svc.kwargs.get("backend_search") is None


def test_fanout_external_ingest_skips_without_enabled_providers(monkeypatch):
    provider_service = MagicMock()
    provider_service._config_service.get_enabled_providers.return_value = []
    monkeypatch.setattr(
        memory_backend_adapter,
        "get_memory_external_provider_service",
        MagicMock(return_value=provider_service),
    )

    asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._fanout_external_ingest(
            {"tenant_id": "t1", "user_id": "u1", "content": "remember me"},
            {"memory_id": "m1"},
        )
    )

    provider_service._config_service.get_enabled_providers.assert_called_once_with("t1")


def test_build_ingestion_event_service_uses_shared_provider_config(monkeypatch):
    provider_service = MagicMock()
    constructor = MagicMock()
    monkeypatch.setattr(
        memory_backend_adapter,
        "get_memory_external_provider_service",
        MagicMock(return_value=provider_service),
    )
    monkeypatch.setattr(memory_backend_adapter, "MemoryIngestionEventService", constructor)

    result = memory_backend_adapter._build_ingestion_event_service()

    constructor.assert_called_once_with(
        provider_service._config_service,
        provider_service,
    )
    assert result is constructor.return_value


def test_fanout_external_ingest_sends_agent_unit_to_all_enabled(monkeypatch):
    provider_service = MagicMock()
    provider_service._config_service.get_enabled_providers.return_value = [
        {"provider_name": "mem0"},
        {"provider_name": "partner"},
    ]
    monkeypatch.setattr(
        memory_backend_adapter,
        "get_memory_external_provider_service",
        MagicMock(return_value=provider_service),
    )
    ingestion_service = MagicMock()
    ingestion_service.send_ingest_all_enabled = AsyncMock(
        return_value=[types.SimpleNamespace(status="ok"), types.SimpleNamespace(status="error")]
    )
    monkeypatch.setattr(
        memory_backend_adapter,
        "_build_ingestion_event_service",
        MagicMock(return_value=ingestion_service),
    )

    asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._fanout_external_ingest(
            {
                "tenant_id": "t1",
                "user_id": "u1",
                "agent_id": "a1",
                "conversation_id": "c1",
                "content": "remember me",
                "layer": MemoryLayer.AGENT,
            },
            {"memory_id": "m1"},
        )
    )

    kwargs = ingestion_service.send_ingest_all_enabled.await_args.kwargs
    assert kwargs["tenant_id"] == "t1"
    assert kwargs["event_id"] == "m1"
    assert kwargs["units"][0].unit_type == "agent"
    assert kwargs["units"][0].unit_content == "remember me"


def test_backend_store_hook_normalizes_enum_layer(fake_record_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "hi",
        "layer": MemoryLayer.AGENT,
        "memory_type": "short_term",
    }
    asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_store_hook(payload)
    )
    kwargs = fake_record_service.create_memory.call_args.kwargs
    assert kwargs["layer"] == "agent"


def test_backend_store_hook_normalizes_enum_memory_type(fake_record_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "hi",
        "layer": "agent",
        "memory_type": MemoryType.SHORT_TERM,
    }
    asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_store_hook(payload)
    )
    kwargs = fake_record_service.create_memory.call_args.kwargs
    assert kwargs["memory_type"] == "short_term"


def test_backend_store_hook_skips_embedding_resolution_when_provided(fake_record_service):
    resolver = record_service_mod._resolve_tenant_embedding_model_info
    previous = resolver.return_value
    resolver.return_value = None
    try:
        payload = {
            "tenant_id": "t1",
            "user_id": "u1",
            "content": "hi",
            "layer": "agent",
            "memory_type": "short_term",
            "embedding": [0.1, 0.2, 0.3],
        }
        result = asyncio.get_event_loop().run_until_complete(
            memory_backend_adapter._backend_store_hook(payload)
        )
        assert result["memory_id"] == 1
        fake_record_service.create_memory.assert_called_once()
        kwargs = fake_record_service.create_memory.call_args.kwargs
        assert kwargs["embedding"] == [0.1, 0.2, 0.3]
    finally:
        resolver.return_value = previous


def test_backend_store_hook_none_conversation_id(fake_record_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "hi",
        "layer": "agent",
        "memory_type": "short_term",
        "conversation_id": None,
    }
    asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_store_hook(payload)
    )
    kwargs = fake_record_service.create_memory.call_args.kwargs
    assert kwargs["conversation_id"] is None


def test_backend_store_hook_empty_string_conversation_id(fake_record_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "hi",
        "layer": "agent",
        "memory_type": "short_term",
        "conversation_id": "",
    }
    asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_store_hook(payload)
    )
    kwargs = fake_record_service.create_memory.call_args.kwargs
    assert kwargs["conversation_id"] is None


def test_backend_store_hook_minimal_payload(fake_record_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "hi",
        "layer": "agent",
        "memory_type": "short_term",
    }
    asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_store_hook(payload)
    )
    kwargs = fake_record_service.create_memory.call_args.kwargs
    assert kwargs["agent_id"] is None
    assert kwargs["conversation_id"] is None
    assert kwargs["idempotency_key"] is None


def test_backend_search_hook_uses_defaults(fake_retrieval_service):
    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "query": "hi",
    }
    results = asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_search_hook(payload)
    )
    assert len(results) == 1


def test_backend_search_hook_serializes_string_layer(fake_retrieval_service):
    retrieval_service_mod.get_memory_retrieval_service.reset_mock()
    svc = MagicMock()
    fake_result = MemorySearchResult(
        memory_id="2", score=0.8, content="y", layer="user"
    )

    async def _search(*args, **kwargs):
        return [fake_result]

    svc.search = _search
    retrieval_service_mod.get_memory_retrieval_service.return_value = svc

    payload = {
        "tenant_id": "t1",
        "user_id": "u1",
        "query": "hi",
    }
    results = asyncio.get_event_loop().run_until_complete(
        memory_backend_adapter._backend_search_hook(payload)
    )
    assert results[0]["layer"] == "user"
