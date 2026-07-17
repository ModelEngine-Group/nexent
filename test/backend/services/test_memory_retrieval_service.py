"""Unit tests for ``backend.services.memory_retrieval_service`` (Phase 2)."""

import sys
import types
from unittest.mock import MagicMock

import pytest


# Path setup
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# Stub database
database_pkg = types.ModuleType("database")
database_pkg.memory_record_db = MagicMock(name="memory_record_db")
database_pkg.memory_retrieval_hit_db = MagicMock(name="memory_retrieval_hit_db")
sys.modules["database"] = database_pkg
sys.modules["backend.database"] = database_pkg


# Stub SDK nexent memory
nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")
# ``__path__`` required so Python treats ``nexent.memory`` as a package.
memory_pkg.__path__ = []
embedding_model_pkg = types.ModuleType("nexent.memory.embedding_model")
embedding_model_pkg.EmbeddingModelInfo = MagicMock(name="EmbeddingModelInfo")
memory_pkg.embedding_model = embedding_model_pkg

memory_models = types.ModuleType("nexent.memory.models")


class _Singleton:
    """Simple value container with a ``.value`` attribute (used as enum instance)."""

    def __init__(self, name, value):
        self.name = name
        self.value = value


class MemoryLayer:
    tenant = _Singleton("tenant", "tenant")
    user = _Singleton("user", "user")
    agent = _Singleton("agent", "agent")
    TENANT = tenant
    USER = user
    AGENT = agent
    _registry = {"tenant": tenant, "user": user, "agent": agent}

    def __new__(cls, value):
        inst = cls._registry.get(value)
        if inst is None:
            raise ValueError(value)
        return inst


class MemorySearchRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemorySearchResult:
    def __init__(
        self,
        memory_id=None,
        content="",
        score=0.0,
        layer=MemoryLayer.AGENT,
        source="internal",
        is_external=False,
        metadata=None,
    ):
        self.memory_id = memory_id
        self.content = content
        self.score = score
        self.layer = layer
        self.source = source
        self.is_external = is_external
        self.metadata = metadata or {}


memory_models.MemoryLayer = MemoryLayer
memory_models.MemorySearchRequest = MemorySearchRequest
memory_models.MemorySearchResult = MemorySearchResult
memory_pkg.models = memory_models
sys.modules["nexent.memory.models"] = memory_models


memory_policy = types.ModuleType("nexent.memory.policy")


class MemoryRetrievalPolicy:
    DEFAULT_TOP_K = 5
    MAX_TOP_K = 100
    DEFAULT_THRESHOLD = 0.65
    FULL_CONTEXT_LAYERS = {MemoryLayer.TENANT, MemoryLayer.USER}
    VECTOR_SEARCH_LAYERS = {MemoryLayer.AGENT}

    @classmethod
    def validate_top_k(cls, top_k):
        if top_k <= 0:
            return cls.DEFAULT_TOP_K
        return min(top_k, cls.MAX_TOP_K)

    @classmethod
    def uses_full_context(cls, layer):
        return layer in cls.FULL_CONTEXT_LAYERS

    @classmethod
    def uses_vector_search(cls, layer):
        return layer in cls.VECTOR_SEARCH_LAYERS


memory_policy.MemoryRetrievalPolicy = MemoryRetrievalPolicy
memory_pkg.policy = memory_policy
sys.modules["nexent.memory.policy"] = memory_policy

nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg


# Stub services package so relative imports within the package work.
sys.modules["services"] = types.ModuleType("services")


# Stub services.memory_index_service
memory_index_service_mod = types.ModuleType("services.memory_index_service")
memory_index_service_mod.MemoryIndexService = MagicMock(name="MemoryIndexService")
memory_index_service_mod.get_memory_index_service = MagicMock(name="get_memory_index_service")
memory_index_service_mod.reset_memory_index_service = MagicMock(name="reset_memory_index_service")
sys.modules["services.memory_index_service"] = memory_index_service_mod


# Stub services.memory_record_service
memory_record_service_mod = types.ModuleType("services.memory_record_service")
memory_record_service_mod.MemoryRecordService = MagicMock(name="MemoryRecordService")
memory_record_service_mod._compute_content_embedding = MagicMock(name="_compute_content_embedding")
memory_record_service_mod._resolve_tenant_embedding_model_info = MagicMock(
    name="_resolve_tenant_embedding_model_info", return_value=None
)
memory_record_service_mod.get_memory_record_service = MagicMock(name="get_memory_record_service")
sys.modules["services.memory_record_service"] = memory_record_service_mod


from backend.services import memory_retrieval_service


@pytest.fixture
def fake_record_service():
    svc = MagicMock()
    svc.list_memories = MagicMock(return_value=[
        {
            "memory_id": 1,
            "tenant_id": "tn",
            "user_id": "u1",
            "content": "tenant memory",
            "layer": "tenant",
            "memory_type": "long_term",
        }
    ])
    return svc


@pytest.fixture
def fake_index_service():
    svc = MagicMock()
    svc.search_similar = MagicMock(return_value=[
        {
            # ES ``_id`` is always a string; the backend ``memory_id`` is int
            # and stringified on the way into Elasticsearch.
            "memory_id": "1",
            "content": "agent short term memory",
            "score": 0.9,
            "layer": "agent",
            "metadata": {"tenant_id": "tn"},
        }
    ])
    return svc


@pytest.fixture
def service(fake_record_service, fake_index_service):
    svc = memory_retrieval_service.MemoryRetrievalService(
        record_service=fake_record_service,
        index_service=fake_index_service,
    )
    return svc


def test_search_returns_full_context_memories(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        layers=[memory_retrieval_service.MemoryLayer.TENANT],
        query="",
        top_k=5,
        threshold=0.65,
    )

    results = []
    import asyncio
    results = asyncio.get_event_loop().run_until_complete(
        service.search(request, write_hits=False)
    )

    assert len(results) == 1
    assert results[0].memory_id == "1"
    assert results[0].layer == memory_retrieval_service.MemoryLayer.TENANT


def test_search_returns_vector_results(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        layers=[memory_retrieval_service.MemoryLayer.AGENT],
        query="hello",
        top_k=5,
        threshold=0.5,
        embedding=[0.1, 0.2, 0.3],
    )

    import asyncio
    results = asyncio.get_event_loop().run_until_complete(
        service.search(request, write_hits=False)
    )

    assert len(results) == 1
    assert results[0].memory_id == "1"
    assert results[0].layer == memory_retrieval_service.MemoryLayer.AGENT


def test_search_filters_by_threshold(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        layers=[memory_retrieval_service.MemoryLayer.AGENT],
        query="hello",
        top_k=5,
        threshold=0.95,
        embedding=[0.1, 0.2, 0.3],
    )

    import asyncio
    results = asyncio.get_event_loop().run_until_complete(
        service.search(request, write_hits=False)
    )

    # 0.9 < 0.95 → filtered out
    assert results == []


def test_search_writes_hits(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        layers=[memory_retrieval_service.MemoryLayer.AGENT],
        query="hello",
        top_k=5,
        threshold=0.5,
        embedding=[0.1, 0.2, 0.3],
    )

    import asyncio
    asyncio.get_event_loop().run_until_complete(
        service.search(request, write_hits=True)
    )

    service._record_hits  # noqa
    memory_retrieval_service.memory_retrieval_hit_db.insert_retrieval_hits.assert_called_once()