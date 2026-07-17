"""Unit tests for ``backend.services.memory_backend_adapter`` (Phase 2).

These tests exercise the async bridge between the SDK ``MemoryService``
facade and the backend services. Both sides are stubbed, so the tests
focus on argument translation and policy enforcement.
"""

import asyncio
import sys
import types
from unittest.mock import MagicMock

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


class _Singleton:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class MemoryLayer:
    TENANT = _Singleton("tenant", "tenant")
    USER = _Singleton("user", "user")
    AGENT = _Singleton("agent", "agent")
    _registry = {"tenant": TENANT, "user": USER, "agent": AGENT}

    def __new__(cls, value):
        inst = cls._registry.get(value)
        if inst is None:
            raise ValueError(value)
        return inst


class MemorySearchRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemorySearchResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


memory_models.MemoryLayer = MemoryLayer
memory_models.MemoryType = type("MemoryType", (), {})  # placeholder for service imports
memory_models.MemorySearchRequest = MemorySearchRequest
memory_models.MemorySearchResult = MemorySearchResult


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

record_service_mod.get_memory_record_service = MagicMock(
    name="get_memory_record_service"
)
retrieval_service_mod.get_memory_retrieval_service = MagicMock(
    name="get_memory_retrieval_service"
)

sys.modules["services.memory_record_service"] = record_service_mod
sys.modules["services.memory_retrieval_service"] = retrieval_service_mod


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
