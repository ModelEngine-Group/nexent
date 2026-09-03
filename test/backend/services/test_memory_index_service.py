"""Unit tests for ``backend.services.memory_index_service`` (Phase 2).

Focus: the hybrid (BM25 + kNN) branch of ``MemoryIndexService.search_similar``.
The pure-kNN branch is exercised end-to-end through the retrieval service
tests in :mod:`test_memory_retrieval_service`.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# ---------------------------------------------------------------------------
# Stubs for the SDK / project modules pulled in by ``memory_index_service``
# ---------------------------------------------------------------------------
nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")
memory_pkg.__path__ = []

embedding_model_pkg = types.ModuleType("nexent.memory.embedding_model")


class _FakeEmbeddingModelInfo:
    """Stand-in for the SDK dataclass that lets tests build deterministic
    ``get_index_name()`` values without going to the network."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get_index_name(self) -> str:
        repo = getattr(self, "model_repo", "") or ""
        name = getattr(self, "model_name", "")
        dim = getattr(self, "dimension", 0)
        if repo:
            return f"mem_{repo}_{name}_{dim}"
        return f"mem_{name}_{dim}"


embedding_model_pkg.EmbeddingModelInfo = _FakeEmbeddingModelInfo
memory_pkg.embedding_model = embedding_model_pkg
sys.modules["nexent.memory.embedding_model"] = embedding_model_pkg

memory_models = types.ModuleType("nexent.memory.models")


class _Singleton:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class MemoryLayer:
    AGENT = _Singleton("agent", "agent")
    _registry = {"agent": AGENT}

    def __new__(cls, value):
        inst = cls._registry.get(value)
        if inst is None:
            raise ValueError(value)
        return inst


memory_models.MemoryLayer = MemoryLayer
memory_pkg.models = memory_models
sys.modules["nexent.memory.models"] = memory_models

sys.modules["nexent.memory"] = memory_pkg


vector_db_pkg = types.ModuleType("nexent.vector_database")
vector_db_pkg.__path__ = []
vector_db_base = types.ModuleType("nexent.vector_database.base")


class VectorDatabaseCore:
    """Abstract stand-in; ``memory_index_service`` only references the type."""

    pass


vector_db_base.VectorDatabaseCore = VectorDatabaseCore
vector_db_pkg.base = vector_db_base
sys.modules["nexent.vector_database.base"] = vector_db_base

vector_db_es_core = types.ModuleType("nexent.vector_database.elasticsearch_core")


class ElasticSearchCore(VectorDatabaseCore):
    pass


vector_db_es_core.ElasticSearchCore = ElasticSearchCore
vector_db_pkg.elasticsearch_core = vector_db_es_core
sys.modules["nexent.vector_database.elasticsearch_core"] = vector_db_es_core

sys.modules["nexent.vector_database"] = vector_db_pkg
sys.modules["nexent"] = nexent_pkg


# ---------------------------------------------------------------------------
# Stub project modules that ``memory_index_service`` imports
# ---------------------------------------------------------------------------
consts_pkg = types.ModuleType("consts")
consts_const = types.ModuleType("consts.const")


class _VectorDatabaseType:
    ELASTICSEARCH = "elasticsearch"


consts_const.VectorDatabaseType = _VectorDatabaseType
consts_pkg.const = consts_const
sys.modules["consts"] = consts_pkg
sys.modules["consts.const"] = consts_const

vdb_service = types.ModuleType("management.services.knowledge_base.service")


def _fake_get_vector_db_core(db_type=None, tenant_id=None):
    return MagicMock(name="fake_vdb_core")


vdb_service.get_vector_db_core = _fake_get_vector_db_core

services_pkg = types.ModuleType("services")
services_pkg.vectordatabase_service = vdb_service
sys.modules["services"] = services_pkg
sys.modules["management.services.knowledge_base.service"] = vdb_service


from backend.services import memory_index_service  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def service():
    """Return a fresh ``MemoryIndexService`` whose ``vdb_core`` is a MagicMock
    that ``isinstance(..., ElasticSearchCore)`` evaluates to True so the
    hybrid branch is reachable."""
    fake_vdb = ElasticSearchCore()  # real subclass, so isinstance passes
    fake_vdb.search = MagicMock(name="vdb.search")
    fake_vdb.hybrid_search = MagicMock(name="vdb.hybrid_search", return_value=[])
    fake_vdb.create_index = MagicMock(name="vdb.create_index", return_value=True)
    fake_vdb.create_chunk = MagicMock(name="vdb.create_chunk", return_value=True)
    fake_vdb.delete_index = MagicMock(name="vdb.delete_index", return_value=True)
    fake_vdb.delete_chunk = MagicMock(name="vdb.delete_chunk", return_value=True)
    svc = memory_index_service.MemoryIndexService(vdb_core=fake_vdb)
    return svc


@pytest.fixture
def embedding():
    return [0.1] * 4


def _es_response(hits):
    """Build a minimal raw ES response payload."""
    return {
        "hits": {
            "total": {"value": len(hits), "relation": "eq"},
            "hits": hits,
        }
    }


def _es_hit(memory_id, content, score, layer="agent", status="active"):
    return {
        "_id": str(memory_id),
        "_score": score,
        "_source": {
            "id": str(memory_id),
            "content": content,
            "metadata": {
                "memory_id": str(memory_id),
                "tenant_id": "tn",
                "user_id": "u1",
                "agent_id": "a1",
                "layer": layer,
                "memory_type": "short_term",
                "status": status,
            },
        },
    }


# ---------------------------------------------------------------------------
# Pure-kNN branch (regression for the hybrid refactor)
# ---------------------------------------------------------------------------
def test_knn_branch_uses_agent_scope_filter_across_conversations(service, embedding):
    """Agent memory is scoped by tenant/user/agent, not conversation."""
    service.vdb_core.search.return_value = _es_response([
        _es_hit(7, "hello world", 0.91),
    ])

    results = service.search_similar(
        index_name="mem_baai_bge-m3_1024",
        embedding=embedding,
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        conversation_id="c1",
        top_k=5,
    )

    assert len(results) == 1
    assert results[0]["memory_id"] == "7"
    assert results[0]["content"] == "hello world"

    # Verify the kNN query body still uses the .keyword sub-fields for
    # tenant/user/agent isolation.
    service.vdb_core.search.assert_called_once()
    body = service.vdb_core.search.call_args.kwargs["query"]
    must_filters = body["knn"]["filter"]["bool"]["must"]
    paths = [next(iter(f["term"].keys())) for f in must_filters]
    assert "metadata.tenant_id.keyword" in paths
    assert "metadata.user_id.keyword" in paths
    assert "metadata.agent_id.keyword" in paths
    assert "metadata.conversation_id.keyword" not in paths
    assert "metadata.layer.keyword" in paths


def test_knn_branch_returns_empty_when_inputs_missing(service):
    """With no index_name the function must short-circuit before any call."""
    assert service.search_similar(
        index_name="",
        embedding=[0.1, 0.2],
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        top_k=5,
    ) == []
    service.vdb_core.search.assert_not_called()


def test_knn_branch_handles_es_failure(service, embedding):
    """If ES raises, search_similar must return [] rather than propagate."""
    service.vdb_core.search.side_effect = RuntimeError("ES down")

    assert service.search_similar(
        index_name="mem_baai_bge-m3_1024",
        embedding=embedding,
        tenant_id="tn",
        user_id="u1",
        top_k=5,
    ) == []


# ---------------------------------------------------------------------------
# Hybrid branch
# ---------------------------------------------------------------------------
def test_hybrid_branch_delegates_with_isolation_filter(service, embedding):
    """When hybrid=True the function must reuse ``vdb_core.hybrid_search``
    and inject the agent-scope ``filter`` so cross-tenant leaks remain
    impossible."""
    service.vdb_core.hybrid_search.return_value = [
        {
            "index": "mem_baai_bge-m3_1024",
            "score": 0.85,
            "scores": {"accurate_score": 0.9, "semantic_score": 0.8},
            "document": {
                "id": "9",
                "content": "hybrid winner",
                "metadata": {
                    "memory_id": "9",
                    "tenant_id": "tn",
                    "user_id": "u1",
                    "agent_id": "a1",
                    "layer": "agent",
                    "memory_type": "short_term",
                    "status": "active",
                },
            },
        },
    ]

    fake_model = MagicMock(name="embedding_model")
    results = service.search_similar(
        index_name="mem_baai_bge-m3_1024",
        embedding=embedding,
        tenant_id="tn",
        user_id="u1",
        agent_id="a1",
        conversation_id="c1",
        top_k=5,
        hybrid=True,
        query_text="hello",
        weight_accurate=0.7,
        embedding_model=fake_model,
    )

    service.vdb_core.hybrid_search.assert_called_once()
    kwargs = service.vdb_core.hybrid_search.call_args.kwargs

    assert kwargs["index_names"] == ["mem_baai_bge-m3_1024"]
    assert kwargs["query_text"] == "hello"
    assert kwargs["embedding_model"] is fake_model
    assert kwargs["weight_accurate"] == 0.7

    isolation = kwargs["filter"]["bool"]["must"]
    paths = [next(iter(f["term"].keys())) for f in isolation]
    assert "metadata.tenant_id.keyword" in paths
    assert "metadata.user_id.keyword" in paths
    assert "metadata.agent_id.keyword" in paths
    assert "metadata.conversation_id.keyword" not in paths
    assert "metadata.layer.keyword" in paths

    assert len(results) == 1
    assert results[0]["memory_id"] == "9"
    assert results[0]["content"] == "hybrid winner"
    assert results[0]["score_details"] == {
        "accurate_score": 0.9,
        "semantic_score": 0.8,
    }
    # The kNN branch must not have been invoked.
    service.vdb_core.search.assert_not_called()


def test_hybrid_branch_falls_back_to_knn_when_inputs_missing(service, embedding):
    """If hybrid is requested but query_text or embedding_model is absent,
    we must silently fall back to the legacy kNN path."""
    service.vdb_core.search.return_value = _es_response([
        _es_hit(11, "fallback hit", 0.4),
    ])

    results = service.search_similar(
        index_name="mem_baai_bge-m3_1024",
        embedding=embedding,
        tenant_id="tn",
        user_id="u1",
        top_k=5,
        hybrid=True,
        # query_text and embedding_model deliberately omitted.
    )

    service.vdb_core.hybrid_search.assert_not_called()
    service.vdb_core.search.assert_called_once()
    assert len(results) == 1


def test_hybrid_branch_falls_back_when_backend_is_not_elasticsearch(embedding):
    """A non-ES backend (e.g. DataMate / mock) doesn't accept ``filter``;
    the index service must silently degrade to its kNN path."""
    fake_vdb = MagicMock(name="data_mate_vdb")  # NOT an ElasticSearchCore
    fake_vdb.search.return_value = _es_response([
        _es_hit(13, "data-mate fallback", 0.42),
    ])
    svc = memory_index_service.MemoryIndexService(vdb_core=fake_vdb)

    results = svc.search_similar(
        index_name="kb_index",
        embedding=embedding,
        tenant_id="tn",
        user_id="u1",
        top_k=5,
        hybrid=True,
        query_text="hello",
        weight_accurate=0.5,
        embedding_model=MagicMock(name="embedding_model"),
    )

    fake_vdb.hybrid_search.assert_not_called()
    fake_vdb.search.assert_called_once()
    assert len(results) == 1
    assert results[0]["memory_id"] == "13"


def test_hybrid_branch_retries_without_filter_on_typeerror(service, embedding):
    """If a future SDK implementation is wired in that doesn't accept the
    ``filter`` kwarg the index service should still produce a result by
    retrying without the filter (matches the pre-refactor SDK contract)."""
    calls = {"n": 0}

    def fake_hybrid(*args, **kwargs):
        calls["n"] += 1
        if "filter" in kwargs:
            raise TypeError("unexpected kwarg 'filter'")
        return [{
            "index": "mem_baai_bge-m3_1024",
            "score": 0.6,
            "document": {"id": "5", "content": "fallback", "metadata": {}},
        }]

    service.vdb_core.hybrid_search.side_effect = fake_hybrid

    results = service.search_similar(
        index_name="mem_baai_bge-m3_1024",
        embedding=embedding,
        tenant_id="tn",
        user_id="u1",
        top_k=5,
        hybrid=True,
        query_text="hello",
        embedding_model=MagicMock(name="embedding_model"),
    )

    assert calls["n"] == 2  # tried twice: with filter, then without
    assert results[0]["memory_id"] == "5"


def test_memory_chunk_payload_uses_layer_specific_title_and_metadata():
    agent_record = {
        "memory_id": 7,
        "layer": "agent",
        "created_by": "user",
        "update_time": "2026-07-26T12:00:00",
        "content": "agent memory",
        "create_time": "2026-07-26T11:00:00",
        "tenant_id": "tn",
        "user_id": "u1",
        "agent_id": "a1",
        "conversation_id": "c1",
        "memory_type": "short_term",
        "status": "active",
        "idempotency_key": "idem-7",
    }
    agent_chunk = memory_index_service._memory_chunk_payload(
        agent_record, [0.1, 0.2], "memory-index"
    )

    assert agent_chunk["title"] == "Short-term Memory 7"
    assert agent_chunk["embedding_model_name"] == "memory-index"
    assert agent_chunk["embedding"] == [0.1, 0.2]
    assert agent_chunk["metadata"] == {
        "memory_id": "7",
        "tenant_id": "tn",
        "user_id": "u1",
        "agent_id": "a1",
        "conversation_id": "c1",
        "layer": "agent",
        "memory_type": "short_term",
        "status": "active",
        "idempotency_key": "idem-7",
    }

    user_chunk = memory_index_service._memory_chunk_payload(
        {"memory_id": 8, "layer": "user"}, None, "memory-index"
    )
    assert user_chunk["title"] == "Long-term user memory 8"
    assert user_chunk["content"] == ""
    assert user_chunk["author"] is None


def test_lazy_vdb_core_and_singleton_accessor(mocker):
    memory_index_service.reset_memory_index_service()
    fake_vdb = MagicMock(name="lazy_vdb")
    get_core = mocker.patch.object(
        memory_index_service, "get_vector_db_core", return_value=fake_vdb
    )

    service = memory_index_service.MemoryIndexService()
    assert service.vdb_core is fake_vdb
    assert service.vdb_core is fake_vdb
    get_core.assert_called_once_with(memory_index_service.VectorDatabaseType.ELASTICSEARCH)

    first = memory_index_service.get_memory_index_service()
    second = memory_index_service.get_memory_index_service()
    assert first is second
    memory_index_service.reset_memory_index_service()
    assert memory_index_service.get_memory_index_service() is not first
    memory_index_service.reset_memory_index_service()


def test_index_lifecycle_returns_false_when_backend_fails(service):
    service.vdb_core.create_index.side_effect = RuntimeError("create failed")
    service.vdb_core.delete_index.side_effect = RuntimeError("delete failed")

    assert service.ensure_index("memory-index", embedding_dim=4) is False
    assert service.drop_index("memory-index") is False


def test_index_record_resolves_model_index_and_writes_payload(service):
    model_info = _FakeEmbeddingModelInfo(model_repo="repo", model_name="model", dimension=4)
    record = {"memory_id": 12, "layer": "agent", "content": "remember this"}

    assert service.index_record(record, [0.1] * 4, model_info) is True

    service.vdb_core.create_index.assert_called_once_with(
        "mem_repo_model_4", embedding_dim=4
    )
    create_call = service.vdb_core.create_chunk.call_args
    assert create_call.kwargs["index_name"] == "mem_repo_model_4"
    assert create_call.kwargs["chunk"]["id"] == "12"
    assert create_call.kwargs["chunk"]["content"] == "remember this"


def test_index_record_rejects_missing_index_and_handles_write_failure(service, mocker):
    assert service.index_record({"memory_id": 1}, [0.1]) is False
    service.vdb_core.create_chunk.side_effect = RuntimeError("write failed")
    mocker.patch.object(service, "ensure_index", return_value=True)

    assert service.index_record(
        {"memory_id": 2, "es_index_name": "memory-index"}, [0.1]
    ) is False


def test_delete_record_converts_result_and_handles_failure(service):
    service.vdb_core.delete_chunk.return_value = 1
    assert service.delete_record(9, "memory-index") is True
    service.vdb_core.delete_chunk.assert_called_once_with("memory-index", "9")

    service.vdb_core.delete_chunk.side_effect = RuntimeError("delete failed")
    assert service.delete_record(10, "memory-index") is False


def test_knn_handles_response_body_objects_and_hit_defaults(service, embedding):
    class Response:
        body = _es_response([{
            "_id": None,
            "_score": None,
            "_source": {"id": "from-source", "content": "minimal"},
        }])

    service.vdb_core.search.return_value = Response()
    results = service.search_similar(
        index_name="memory-index",
        embedding=embedding,
        tenant_id="tn",
        user_id="u1",
        top_k=0,
    )

    query = service.vdb_core.search.call_args.kwargs["query"]
    assert query["knn"]["k"] == 1
    assert query["knn"]["num_candidates"] == 50
    assert results == [{
        "memory_id": "from-source",
        "content": "minimal",
        "score": 0.0,
        "layer": "agent",
        "memory_type": "short_term",
        "source": "internal",
        "is_external": False,
        "metadata": {},
    }]


def test_hybrid_returns_empty_when_backend_raises(service, embedding):
    service.vdb_core.hybrid_search.side_effect = RuntimeError("hybrid failed")

    assert service.search_similar(
        index_name="memory-index",
        embedding=embedding,
        tenant_id="tn",
        user_id="u1",
        hybrid=True,
        query_text="hello",
        embedding_model=MagicMock(name="embedding-model"),
    ) == []


def test_safe_score_preview_handles_empty_none_and_invalid_responses():
    assert memory_index_service._safe_score_preview({}) is None
    assert memory_index_service._safe_score_preview(
        {"hits": {"hits": [{"_score": None}]}}
    ) is None
    assert memory_index_service._safe_score_preview(
        {"hits": {"hits": [{"_score": 0.2}, {"_score": 0.8}]}}
    ) == {"min": 0.2, "max": 0.8}

    class BrokenResponse:
        def get(self, _key):
            raise RuntimeError("invalid response")

    assert memory_index_service._safe_score_preview(BrokenResponse()) is None
