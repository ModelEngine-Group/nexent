"""Unit tests for ``backend.services.memory_record_service`` (Phase 2).

The tests stub the database access layer and the ES index service so we
can verify the service's policy enforcement, idempotency handling, and
delegation to the index service.
"""

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
# Stub backend.database
# ---------------------------------------------------------------------------
database_pkg = types.ModuleType("database")
database_pkg.memory_record_db = MagicMock(name="memory_record_db")
database_pkg.model_management_db = MagicMock(name="model_management_db")
sys.modules["database"] = database_pkg
sys.modules["backend.database"] = database_pkg


# ---------------------------------------------------------------------------
# Stub SDK nexent hierarchy
# ---------------------------------------------------------------------------
nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")
memory_models = types.ModuleType("nexent.memory.models")
memory_policy = types.ModuleType("nexent.memory.policy")
embedding_model_pkg = types.ModuleType("nexent.memory.embedding_model")


class _Singleton:
    """Simple object with a ``.value`` attribute used as layer/type singleton."""

    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __repr__(self):
        return f"MemoryLayer.{self.name.upper()}"


class MemoryLayer:
    """Stub matching the real ``nexent.memory.models.MemoryLayer`` interface."""

    tenant = _Singleton("tenant", "tenant")
    user = _Singleton("user", "user")
    agent = _Singleton("agent", "agent")

    # Aliases so both lowercase and UPPER access work.
    TENANT = tenant
    USER = user
    AGENT = agent

    _registry = {"tenant": tenant, "user": user, "agent": agent}

    def __new__(cls, value):
        inst = cls._registry.get(value)
        if inst is None:
            raise ValueError(value)
        return inst


class MemoryType:
    """Stub matching the real ``nexent.memory.models.MemoryType`` interface."""

    short_term = _Singleton("short_term", "short_term")
    long_term = _Singleton("long_term", "long_term")

    SHORT_TERM = short_term
    LONG_TERM = long_term

    _registry = {"short_term": short_term, "long_term": long_term}

    def __new__(cls, value):
        inst = cls._registry.get(value)
        if inst is None:
            raise ValueError(value)
        return inst


class _MemoryType:
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"

    def __init__(self, value):
        self.value = value


memory_models.MemoryLayer = MemoryLayer
memory_models.MemoryType = MemoryType
memory_pkg.models = memory_models


class MemoryAccessPolicy:
    AGENT_WRITEABLE_LAYERS = {MemoryLayer.agent}
    AGENT_WRITEABLE_TYPES = {MemoryType.short_term}
    DREAMING_WRITEABLE_LAYERS = {MemoryLayer.user}
    DREAMING_WRITEABLE_TYPES = {MemoryType.long_term}

    @classmethod
    def can_agent_write(cls, layer, memory_type):
        return layer in cls.AGENT_WRITEABLE_LAYERS and memory_type in cls.AGENT_WRITEABLE_TYPES

    @classmethod
    def can_dreaming_write(cls, layer, memory_type):
        return layer in cls.DREAMING_WRITEABLE_LAYERS and memory_type in cls.DREAMING_WRITEABLE_TYPES


class MemoryStoragePolicy:
    FULL_CONTEXT_LAYERS = {MemoryLayer.tenant, MemoryLayer.user}
    VECTOR_INDEXED_LAYERS = {MemoryLayer.agent}

    @classmethod
    def uses_full_context_for_layer(cls, layer):
        try:
            layer_enum = layer if isinstance(layer, MemoryLayer) else MemoryLayer(layer)
        except ValueError:
            return False
        return layer_enum in cls.FULL_CONTEXT_LAYERS


memory_policy.MemoryAccessPolicy = MemoryAccessPolicy
memory_policy.MemoryStoragePolicy = MemoryStoragePolicy
memory_pkg.policy = memory_policy
nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg
sys.modules["nexent.memory.models"] = memory_models
sys.modules["nexent.memory.policy"] = memory_policy


class _FakeEmbeddingModelInfo:
    def __init__(self, index_name="mem_test_1536"):
        self._index_name = index_name

    def get_index_name(self):
        return self._index_name


embedding_model_pkg.EmbeddingModelInfo = _FakeEmbeddingModelInfo
memory_pkg.embedding_model = embedding_model_pkg
sys.modules["nexent.memory.embedding_model"] = embedding_model_pkg


# Stub SDK nexent.vector_database
vector_db_pkg = types.ModuleType("nexent.vector_database")
es_core_pkg = types.ModuleType("nexent.vector_database.elasticsearch_core")
es_core_pkg.ElasticSearchCore = MagicMock(name="ElasticSearchCore")
vector_db_pkg.elasticsearch_core = es_core_pkg
sys.modules["nexent.vector_database"] = vector_db_pkg
sys.modules["nexent.vector_database.elasticsearch_core"] = es_core_pkg


# Stub the ``services`` package so that relative imports within the package work.
services_pkg = types.ModuleType("services")
sys.modules["services"] = services_pkg


# ---------------------------------------------------------------------------
# Stub consts
# ---------------------------------------------------------------------------
consts_pkg = types.ModuleType("consts")
consts_mod = types.ModuleType("consts.const")
consts_mod.ES_API_KEY = ""
consts_mod.ES_HOST = ""
sys.modules["consts"] = consts_pkg
sys.modules["consts.const"] = consts_mod


# ---------------------------------------------------------------------------
# Stub services.memory_index_service
# ---------------------------------------------------------------------------
memory_index_service_mod = types.ModuleType("services.memory_index_service")


class MemoryIndexService:
    def __init__(self):
        self.index_record = MagicMock(return_value=True)
        self.delete_record = MagicMock(return_value=True)
        self.search_similar = MagicMock(return_value=[])


memory_index_service_mod.MemoryIndexService = MemoryIndexService
memory_index_service_mod.get_memory_index_service = lambda: MemoryIndexService()
sys.modules["services.memory_index_service"] = memory_index_service_mod


# ---------------------------------------------------------------------------
# Stub services.memory_retrieval_service for app-layer imports.
# ---------------------------------------------------------------------------
memory_retrieval_service_mod = types.ModuleType("services.memory_retrieval_service")
memory_retrieval_service_mod.MemoryRetrievalService = MemoryIndexService
memory_retrieval_service_mod.get_memory_retrieval_service = lambda: MemoryIndexService()
sys.modules["services.memory_retrieval_service"] = memory_retrieval_service_mod


# ---------------------------------------------------------------------------
# Reload the record service so the imports pick up the stubs.
# ---------------------------------------------------------------------------
from backend.services import memory_record_service  # noqa: E402


@pytest.fixture
def fake_db(monkeypatch):
    fake = MagicMock(name="memory_record_db")
    fake.generate_memory_id = lambda: None
    fake.insert_memory_record = MagicMock(return_value=1)
    fake.upsert_memory_record_by_idempotency = MagicMock(return_value=1)
    fake.find_by_idempotency = MagicMock(return_value=None)
    fake.update_memory_record = MagicMock(return_value=True)
    fake.soft_delete_memory_record = MagicMock(return_value=True)
    fake.get_memory_record = MagicMock(return_value={"memory_id": 1, "es_index_name": "mem_idx"})
    fake.list_memory_records = MagicMock(return_value=[])

    fake_model_db = MagicMock(name="model_management_db")
    fake_model_db.get_model_records.return_value = []

    fake_client = MagicMock(name="embedding_client")
    fake_client.get_embeddings.return_value = [[0.1, 0.2]]

    monkeypatch.setattr(memory_record_service, "memory_record_db", fake)
    monkeypatch.setattr(memory_record_service, "model_management_db", fake_model_db)
    monkeypatch.setattr(memory_record_service, "get_embedding_client", fake_client)
    return fake


@pytest.fixture
def service(fake_db):
    svc = memory_record_service.MemoryRecordService()
    svc.index_service = MagicMock()
    svc.index_service.index_record.return_value = True
    svc.index_service.delete_record.return_value = True
    return svc


def test_create_memory_agent_short_term_writes_pg_and_es(service, fake_db):
    fake_index_info = MagicMock()
    fake_index_info.get_index_name.return_value = "mem_test_1536"
    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="hello",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        conversation_id="c1",
        idempotency_key="k1",
        embedding_model_info=fake_index_info,
    )
    assert result["event"] == "ADD"
    assert result["memory_id"] == 1
    assert result["indexed"] is True
    fake_db.insert_memory_record.assert_called_once()
    service.index_service.index_record.assert_called_once()


def test_create_memory_agent_without_idempotency_key_generates_one(service, fake_db):
    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="hello",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
    )
    assert result["event"] == "ADD"
    assert result["memory_id"] == 1
    # ``idempotency_key`` is passed as the first positional argument to
    # ``insert_memory_record`` (record dict), not as a kwarg.
    call_args = fake_db.insert_memory_record.call_args
    record_passed = call_args.args[0] if call_args.args else call_args.kwargs
    assert record_passed.get("idempotency_key")


def test_create_memory_user_long_term_is_pg_only(service, fake_db):
    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="preference",
        layer="user",
        memory_type="long_term",
        idempotency_key="k2",
        actor="system",
    )
    assert result["event"] == "ADD"
    assert result["indexed"] is False
    service.index_service.index_record.assert_not_called()


def test_create_memory_agent_policy_violation(service, fake_db):
    with pytest.raises(memory_record_service.MemoryRecordError):
        service.create_memory(
            tenant_id="t1",
            user_id="u1",
            content="x",
            layer="user",
            memory_type="long_term",
            actor="agent",
        )


def test_create_memory_idempotent_update(service, fake_db):
    fake_db.find_by_idempotency.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "old",
        "memory_type": "long_term",
        "layer": "user",
        "es_index_name": None,
    }
    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="updated",
        layer="user",
        memory_type="long_term",
        idempotency_key="k1",
        actor="system",
    )
    assert result["event"] == "UPDATE"
    fake_db.insert_memory_record.assert_not_called()
    fake_db.upsert_memory_record_by_idempotency.assert_called_once()


def test_soft_delete_memory_cascades_to_index(service, fake_db):
    ok = service.soft_delete_memory(1, "t1", updated_by="u1", cascade_index=True)
    assert ok is True
    fake_db.soft_delete_memory_record.assert_called_once()
    service.index_service.delete_record.assert_called_once_with(1, "mem_idx")


def test_list_memories_delegates_to_db(service, fake_db):
    fake_db.list_memory_records.return_value = [{"memory_id": 1}]
    rows = service.list_memories("t1", user_id="u1", layer="agent")
    assert rows == [{"memory_id": 1}]
    fake_db.list_memory_records.assert_called_once()


def test_create_memory_agent_auto_resolves_tenant_embedding_model(service, fake_db, monkeypatch):
    fake_db.find_by_idempotency.return_value = None
    fake_db.get_model_records = MagicMock(
        return_value=[
            {
                "model_name": "text-embedding-3-small",
                "model_repo": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "max_tokens": 1536,
                "ssl_verify": True,
                "connect_status": "available",
            }
        ]
    )

    fake_index_info = _FakeEmbeddingModelInfo(index_name="mem_openai_text_embedding_3_small_1536")
    fake_client = MagicMock(name="embedding_client")
    fake_client.get_embeddings.return_value = [[0.1, 0.2]]
    monkeypatch.setattr(memory_record_service, "get_embedding_client", fake_client)

    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="hello",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        conversation_id="c1",
        idempotency_key="k1",
    )
    assert result["event"] == "ADD"
    assert result["indexed"] is True
    fake_client.assert_called_once_with(
        model_name="text-embedding-3-small",
        dimension=1536,
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_repo="openai",
        ssl_verify=True,
    )
    fake_client.return_value.get_embeddings.assert_called_once_with(
        "hello", timeout=30, retries=2, retry_timeout_step=5.0
    )
    service.index_service.index_record.assert_called_once()
    index_call = service.index_service.index_record.call_args
    assert index_call.kwargs["embedding"] == [0.1, 0.2]
    assert index_call.kwargs["embedding_model_info"] == fake_index_info


def test_create_memory_agent_without_tenant_embedding_model_stays_pg_only(service, fake_db):
    fake_db.find_by_idempotency.return_value = None
    fake_db.get_model_records = MagicMock(return_value=[])

    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="hello",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        idempotency_key="k1",
    )
    assert result["event"] == "ADD"
    assert result["indexed"] is False
    service.index_service.index_record.assert_not_called()


def test_create_memory_agent_embedding_compute_failure_degrades_gracefully(service, fake_db, monkeypatch):
    fake_db.find_by_idempotency.return_value = None
    fake_db.get_model_records = MagicMock(
        return_value=[
            {
                "model_name": "text-embedding-3-small",
                "model_repo": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "max_tokens": 1536,
                "ssl_verify": True,
                "connect_status": "available",
            }
        ]
    )

    fake_client = MagicMock(name="embedding_client")
    fake_client.return_value.get_embeddings.side_effect = RuntimeError("upstream timeout")
    monkeypatch.setattr(memory_record_service, "get_embedding_client", fake_client)

    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="hello",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        idempotency_key="k1",
    )
    assert result["event"] == "ADD"
    assert result["memory_id"] == 1
    assert result["indexed"] is False
    fake_db.insert_memory_record.assert_called_once()
    service.index_service.index_record.assert_not_called()