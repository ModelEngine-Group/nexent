"""Unit tests for ``backend.services.memory_retrieval_service`` (Phase 2)."""

import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.anyio

_MODULE_PREFIXES = ("database", "backend.database", "nexent", "services")
_ORIGINAL_MODULES = {
    name: module
    for name, module in sys.modules.items()
    if name in _MODULE_PREFIXES or name.startswith(tuple(prefix + "." for prefix in _MODULE_PREFIXES))
}


# Path setup
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# Stub database
database_pkg = types.ModuleType("database")
database_pkg.memory_long_term_db = MagicMock(name="memory_long_term_db")
database_pkg.memory_long_term_db.get_active.return_value = None
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
sys.modules["nexent.memory.embedding_model"] = embedding_model_pkg

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
        external_id=None,
        **kwargs,
    ):
        self.memory_id = memory_id
        self.content = content
        self.score = score
        self.layer = layer
        self.source = source
        self.is_external = is_external
        self.metadata = metadata or {}
        self.external_id = external_id


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

# The imported module keeps its boundary doubles; restore global import state
# immediately so collection order cannot corrupt unrelated service/SDK tests.
for _name in list(sys.modules):
    if _name in _MODULE_PREFIXES or _name.startswith(tuple(prefix + "." for prefix in _MODULE_PREFIXES)):
        if _name not in _ORIGINAL_MODULES:
            del sys.modules[_name]
sys.modules.update(_ORIGINAL_MODULES)


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
    memory_retrieval_service.memory_long_term_db.get_active.return_value = {
        "version_id": 1, "version_no": 1, "scope": "tenant", "content": "tenant memory",
        "source": "manual", "evidence_ids": [],
    }
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
    results = asyncio.new_event_loop().run_until_complete(
        service.search(request, write_hits=False)
    )

    assert len(results) == 1
    assert results[0].external_id == "long-term-version:1"
    assert results[0].layer == memory_retrieval_service.MemoryLayer.TENANT


def test_ac047_user_context_returns_exactly_one_active_document(service):
    memory_retrieval_service.memory_long_term_db.get_active.return_value = {
        "version_id": 8,
        "version_no": 2,
        "scope": "user",
        "content": "dreaming long-term memory",
        "source": "dreaming",
        "evidence_ids": ["46", "47"],
    }
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        layers=[memory_retrieval_service.MemoryLayer.USER],
        query="",
        top_k=1,
        threshold=0.65,
    )

    import asyncio

    results = asyncio.new_event_loop().run_until_complete(
        service.search(request, write_hits=False)
    )

    assert len(results) == 1
    dreaming = results[0]
    assert dreaming.content == "dreaming long-term memory"
    assert dreaming.layer == memory_retrieval_service.MemoryLayer.USER
    assert dreaming.source == "dreaming"
    assert dreaming.metadata["version_id"] == 8
    assert dreaming.metadata["source_evidence_ids"] == ["46", "47"]
    memory_retrieval_service.memory_long_term_db.get_active.assert_called_with(
        "tn", "user", "u1"
    )
    memory_retrieval_service.memory_long_term_db.get_active.return_value = None


def test_search_returns_vector_results(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        conversation_id=None,
        layers=[memory_retrieval_service.MemoryLayer.AGENT],
        query="hello",
        top_k=5,
        threshold=0.5,
        embedding=[0.1, 0.2, 0.3],
    )

    import asyncio
    embedding_model_info = MagicMock()
    embedding_model_info.get_index_name = MagicMock(return_value="test_index")
    results = asyncio.new_event_loop().run_until_complete(
        service.search(request, embedding_model_info=embedding_model_info, write_hits=False)
    )

    assert len(results) == 1
    assert results[0].memory_id == 1
    assert results[0].layer == memory_retrieval_service.MemoryLayer.AGENT


def test_search_filters_by_threshold(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        conversation_id=None,
        layers=[memory_retrieval_service.MemoryLayer.AGENT],
        query="hello",
        top_k=5,
        threshold=0.95,
        embedding=[0.1, 0.2, 0.3],
    )

    import asyncio
    embedding_model_info = MagicMock()
    embedding_model_info.get_index_name = MagicMock(return_value="test_index")
    results = asyncio.new_event_loop().run_until_complete(
        service.search(request, embedding_model_info=embedding_model_info, write_hits=False)
    )

    # 0.9 < 0.95 → filtered out
    assert results == []


def test_search_writes_hits(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        conversation_id=None,
        layers=[memory_retrieval_service.MemoryLayer.AGENT],
        query="hello",
        top_k=5,
        threshold=0.5,
        embedding=[0.1, 0.2, 0.3],
    )

    import asyncio
    embedding_model_info = MagicMock()
    embedding_model_info.get_index_name = MagicMock(return_value="test_index")
    asyncio.new_event_loop().run_until_complete(
        service.search(request, embedding_model_info=embedding_model_info, write_hits=True)
    )



@pytest.mark.asyncio
async def test_search_uses_default_layers_without_truncating_full_context(
    service, monkeypatch
):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        layers=None, query="hello", top_k=1, threshold=0.5
    )
    full_result = memory_retrieval_service.MemorySearchResult(memory_id=10)
    vector_result = memory_retrieval_service.MemorySearchResult(memory_id=11)
    monkeypatch.setattr(service, "_full_context_search", MagicMock(return_value=[full_result]))
    monkeypatch.setattr(service, "_vector_search", MagicMock(return_value=[vector_result]))

    results = await service.search(request, write_hits=False)

    assert results == [full_result, full_result, vector_result]
    service._full_context_search.assert_any_call(request=request, layer="tenant")
    service._full_context_search.assert_any_call(request=request, layer="user")
    service._vector_search.assert_called_once()




@pytest.mark.asyncio
async def test_search_logs_unsupported_layer(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", layers=[object()], query="hello", top_k=5
    )

    assert await service.search(request, write_hits=False) == []


def test_vector_search_handles_invalid_result_memory_id(service, monkeypatch):
    class InvalidMemoryId:
        def __int__(self):
            raise ValueError("invalid result id")

    class Result:
        memory_id = InvalidMemoryId()
        content = "text"
        score = 0.8
        metadata = {}

    monkeypatch.setattr(
        memory_retrieval_service,
        "MemorySearchResult",
        MagicMock(return_value=Result()),
    )
    service.index_service.search_similar.return_value = [
        {"memory_id": "4", "score": 0.8, "content": "text", "metadata": {}}
    ]
    monkeypatch.setattr(
        memory_retrieval_service.memory_record_db,
        "get_memory_records_by_ids",
        MagicMock(return_value=[]),
    )
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        embedding=[0.1], threshold=0.5, query="hello"
    )
    model_info = MagicMock(get_index_name=MagicMock(return_value="index"))

    results = service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=model_info
    )

    assert len(results) == 1
    assert results[0].memory_id.__class__ is InvalidMemoryId


def test_serialize_record_as_result_defaults_and_handles_invalid_layer():
    result = memory_retrieval_service._serialize_record_as_result(
        {"memory_id": 1, "content": "text", "layer": "unknown", "concept_tags": None},
        score="0.8",
        is_external=True,
    )

    assert result.memory_id == 1
    assert result.score == 0.8
    assert result.layer == memory_retrieval_service.MemoryLayer.USER
    assert result.is_external is True
    assert result.metadata["concept_tags"] == []


@pytest.mark.asyncio
async def test_search_memories_resolves_layers_embedding_and_delegates(service, monkeypatch):
    embedding_info = MagicMock(model_name="model")
    monkeypatch.setattr(
        memory_retrieval_service,
        "_resolve_tenant_embedding_model_info",
        MagicMock(return_value=embedding_info),
    )
    monkeypatch.setattr(
        memory_retrieval_service,
        "_compute_content_embedding",
        MagicMock(return_value=[0.1, 0.2]),
    )
    expected = [memory_retrieval_service.MemorySearchResult(memory_id=1)]
    search_mock = AsyncMock(return_value=expected)
    monkeypatch.setattr(service, "search", search_mock)

    results = await service.search_memories(
        "tn",
        "u1",
        "hello",
        layers=[" AGENT ", "invalid", "USER"],
        agent_id="a1",
        conversation_id="c1",
        top_k=3,
        threshold=0.7,
        write_hits=False,
        hybrid=True,
        weight_accurate=0.4,
    )

    assert results == expected
    search_mock.assert_called_once()
    request = search_mock.call_args.args[0]
    assert request.layers == [
        memory_retrieval_service.MemoryLayer.AGENT,
        memory_retrieval_service.MemoryLayer.USER,
    ]
    assert request.embedding == [0.1, 0.2]
    assert request.hybrid is True
    assert request.weight_accurate == 0.4


@pytest.mark.asyncio
async def test_search_memories_skips_embedding_for_empty_query(service, monkeypatch):
    embedding_info = MagicMock(model_name="model")
    resolve_mock = MagicMock(return_value=embedding_info)
    embed_mock = MagicMock(return_value=[0.1])
    search_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(memory_retrieval_service, "_resolve_tenant_embedding_model_info", resolve_mock)
    monkeypatch.setattr(memory_retrieval_service, "_compute_content_embedding", embed_mock)
    monkeypatch.setattr(service, "search", search_mock)

    await service.search_memories("tn", "u1", "", layers=None)

    embed_mock.assert_not_called()
    assert search_mock.call_args.args[0].layers == [memory_retrieval_service.MemoryLayer.AGENT]


def test_vector_search_returns_empty_for_missing_inputs(service):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        embedding=None, threshold=0.5, query="hello"
    )
    model_info = MagicMock(get_index_name=MagicMock(return_value="index"))
    assert service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=model_info
    ) == []
    request.embedding = [0.1]
    assert service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=None
    ) == []
    model_info.get_index_name.return_value = None
    assert service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=model_info
    ) == []


def test_vector_search_filters_invalid_hits_and_enriches_records(service, monkeypatch):
    service.index_service.search_similar.return_value = [
        {"memory_id": "bad", "score": 0.99, "content": "bad"},
        {"memory_id": "2", "score": 0.4, "content": "below"},
        {"memory_id": "3", "score": 0.9, "content": "missing", "layer": "invalid"},
        {"memory_id": "4", "score": 0.8, "content": "enriched", "metadata": {"x": 1}},
    ]
    monkeypatch.setattr(
        memory_retrieval_service.memory_record_db,
        "get_memory_records_by_ids",
        MagicMock(
            return_value=[
                {"memory_id": 4, "memory_type": "short_term", "status": "active", "concept_tags": ["x"]}
            ]
        ),
    )
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        embedding=[0.1], threshold=0.5, query="hello"
    )
    model_info = MagicMock(get_index_name=MagicMock(return_value="index"))

    results = service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=model_info
    )

    assert [result.memory_id for result in results] == [3, 4]
    assert results[0].layer == memory_retrieval_service.MemoryLayer.AGENT
    assert results[1].metadata["memory_type"] == "short_term"
    assert results[1].metadata["concept_tags"] == ["x"]
    memory_retrieval_service.memory_record_db.get_memory_records_by_ids.assert_called_once_with(
        [3, 4], "tn"
    )


def test_vector_search_uses_default_threshold_and_skips_unmatched_record(service, monkeypatch):
    service.index_service.search_similar.return_value = [
        {"memory_id": "1", "score": 0.7, "content": "text", "metadata": {}}
    ]
    monkeypatch.setattr(
        memory_retrieval_service.memory_record_db,
        "get_memory_records_by_ids",
        MagicMock(return_value=[]),
    )
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        embedding=[0.1], threshold=None, query="hello"
    )
    model_info = MagicMock(get_index_name=MagicMock(return_value="index"))

    results = service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=model_info
    )

    assert len(results) == 1
    assert results[0].metadata == {}


def test_vector_search_returns_empty_when_index_returns_no_hits(service):
    service.index_service.search_similar.return_value = []
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        embedding=[0.1], threshold=0.5, query="hello"
    )
    model_info = MagicMock(get_index_name=MagicMock(return_value="index"))

    assert service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=model_info
    ) == []


def test_vector_search_hybrid_builds_client(service, monkeypatch):
    embedding_client = object()
    get_client = MagicMock(return_value=embedding_client)
    embedding_module = importlib.import_module("nexent.memory.embedding_model")
    monkeypatch.setattr(embedding_module, "get_embedding_client", get_client)
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        embedding=[0.1], threshold=0.5,
        query="hello", hybrid=True, weight_accurate=0.6,
    )
    model_info = MagicMock(
        model_name="model", dimension=2, base_url="url", api_key="key",
        model_repo="repo", ssl_verify=True,
        get_index_name=MagicMock(return_value="index"),
    )

    service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=model_info
    )

    assert get_client.call_args.kwargs["model_name"] == "model"
    assert service.index_service.search_similar.call_args.kwargs["embedding_model"] is embedding_client


def test_vector_search_hybrid_client_failure_falls_back(service, monkeypatch):
    get_client = MagicMock(side_effect=RuntimeError("client failure"))
    embedding_module = importlib.import_module("nexent.memory.embedding_model")
    monkeypatch.setattr(embedding_module, "get_embedding_client", get_client)
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        embedding=[0.1], threshold=0.5,
        query="hello", hybrid=True,
    )
    model_info = MagicMock(get_index_name=MagicMock(return_value="index"))

    results = service._vector_search(
        request=request, layer="agent", top_k=5, embedding_model_info=model_info
    )

    assert results
    assert service.index_service.search_similar.call_args.kwargs["embedding_model"] is None


def test_record_hits_skips_invalid_ids_and_handles_insert_failure(service, monkeypatch):
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", agent_id="a1", conversation_id="c1",
        query="hello"
    )
    results = [
        memory_retrieval_service.MemorySearchResult(memory_id=0),
        memory_retrieval_service.MemorySearchResult(memory_id="bad"),
        memory_retrieval_service.MemorySearchResult(memory_id=5, score=0.9),
    ]
    insert_mock = MagicMock(side_effect=RuntimeError("write failure"))
    monkeypatch.setattr(
        memory_retrieval_service.memory_retrieval_hit_db,
        "insert_retrieval_hits",
        insert_mock,
    )

    service._record_hits(request=request, results=results)

    insert_mock.assert_called_once()
    payload = insert_mock.call_args.args[0]
    assert len(payload) == 1
    assert payload[0]["memory_id"] == 5
    assert len(payload[0]["query_hash"]) == 64
    assert payload[0]["day"] == memory_retrieval_service._iso_day(payload[0]["occurred_at"])


def test_record_hits_does_nothing_when_no_valid_results(service, monkeypatch):
    insert_mock = MagicMock()
    monkeypatch.setattr(
        memory_retrieval_service.memory_retrieval_hit_db,
        "insert_retrieval_hits",
        insert_mock,
    )
    request = memory_retrieval_service.MemorySearchRequest(
        tenant_id="tn", user_id="u1", query="hello"
    )

    service._record_hits(
        request=request,
        results=[memory_retrieval_service.MemorySearchResult(memory_id=None)],
    )

    insert_mock.assert_not_called()


def test_service_accessors_cache_and_reset(monkeypatch):
    first = object()
    constructor = MagicMock(return_value=first)
    monkeypatch.setattr(memory_retrieval_service, "MemoryRetrievalService", constructor)
    memory_retrieval_service.reset_memory_retrieval_service()

    assert memory_retrieval_service.get_memory_retrieval_service() is first
    assert memory_retrieval_service.get_memory_retrieval_service() is first
    constructor.assert_called_once_with()
    memory_retrieval_service.reset_memory_retrieval_service()
