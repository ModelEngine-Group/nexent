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
    def __init__(self, index_name=None, **kwargs):
        self.__dict__.update(kwargs)
        if index_name is not None:
            self._index_name = index_name
        else:
            components = [
                "mem",
                kwargs.get("model_repo"),
                kwargs.get("model_name"),
                str(kwargs.get("dimension")),
            ]
            self._index_name = "_".join(
                str(value).lower() for value in components if value
            )

    def get_index_name(self):
        return self._index_name


embedding_model_pkg.EmbeddingModelInfo = _FakeEmbeddingModelInfo
embedding_model_pkg.get_embedding_client = MagicMock()
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
sys.modules["backend.services.memory_index_service"] = memory_index_service_mod


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

    fake_client = MagicMock(name="embedding_client")
    fake_client.get_embeddings.return_value = [[0.1, 0.2]]

    monkeypatch.setattr(memory_record_service, "memory_record_db", fake)
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
    fake_index_info = _FakeEmbeddingModelInfo(index_name="mem_current")
    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="hello",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        embedding=[0.1, 0.2],
        embedding_model_info=fake_index_info,
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


def test_list_memories_marks_agent_embedding_compatibility(
    service, fake_db, monkeypatch
):
    fake_db.list_memory_records.return_value = [
        {
            "memory_id": 1,
            "layer": "agent",
            "es_index_name": "mem_current",
        },
        {
            "memory_id": 2,
            "layer": "agent",
            "es_index_name": "mem_previous",
        },
    ]
    monkeypatch.setattr(
        memory_record_service,
        "get_tenant_memory_index_name",
        lambda _tenant_id: "mem_current",
    )
    rows = service.list_memories("t1", user_id="u1", layer="agent")
    assert rows[0]["embedding_compatible"] is True
    assert rows[1]["embedding_compatible"] is False
    fake_db.list_memory_records.assert_called_once()


def test_create_memory_agent_auto_resolves_tenant_embedding_model(service, fake_db, monkeypatch):
    fake_db.find_by_idempotency.return_value = None

    fake_index_info = _FakeEmbeddingModelInfo(index_name="mem_openai_text_embedding_3_small_1536")
    fake_index_info.model_name = "text-embedding-3-small"
    fake_index_info.dimension = 1536
    fake_index_info.base_url = "https://api.openai.com/v1"
    fake_index_info.api_key = "sk-test"
    fake_index_info.model_repo = "openai"
    fake_index_info.ssl_verify = True
    monkeypatch.setattr(
        memory_record_service,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: fake_index_info,
    )
    fake_client = MagicMock(name="embedding_client")
    fake_client.return_value.get_embeddings.return_value = [[0.1, 0.2]]
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


def test_create_memory_agent_without_tenant_embedding_model_fails(service, fake_db, monkeypatch):
    fake_db.find_by_idempotency.return_value = None
    monkeypatch.setattr(
        memory_record_service,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: None,
    )

    with pytest.raises(memory_record_service.MemoryRecordError):
        service.create_memory(
            tenant_id="t1",
            user_id="u1",
            content="hello",
            layer="agent",
            memory_type="short_term",
            agent_id="a1",
            idempotency_key="k1",
        )
    fake_db.insert_memory_record.assert_not_called()
    service.index_service.index_record.assert_not_called()


def test_create_memory_agent_embedding_compute_failure_degrades_gracefully(service, fake_db, monkeypatch):
    fake_db.find_by_idempotency.return_value = None
    fake_index_info = _FakeEmbeddingModelInfo(index_name="mem_current")
    fake_index_info.model_name = "text-embedding-3-small"
    fake_index_info.dimension = 1536
    fake_index_info.base_url = "https://api.openai.com/v1"
    fake_index_info.api_key = "sk-test"
    fake_index_info.model_repo = "openai"
    fake_index_info.ssl_verify = True
    monkeypatch.setattr(
        memory_record_service,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: fake_index_info,
    )

    fake_client = MagicMock(name="embedding_client")
    fake_client.return_value.get_embeddings.side_effect = RuntimeError("upstream timeout")
    monkeypatch.setattr(memory_record_service, "get_embedding_client", fake_client)
    service.index_service.index_record.side_effect = (
        lambda *, embedding, **_kwargs: embedding is not None
    )

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
    service.index_service.index_record.assert_called_once()
    assert service.index_service.index_record.call_args.kwargs["embedding"] is None


def test_resolve_tenant_embedding_model_uses_configured_model(monkeypatch):
    tenant_config_db = types.ModuleType("database.tenant_config_db")
    tenant_config_db.get_single_config_info = MagicMock(
        return_value={"config_value": "42"}
    )
    config_utils = types.ModuleType("utils.config_utils")
    config_utils.tenant_config_manager = MagicMock()
    config_utils.tenant_config_manager.get_model_config.return_value = {
        "model_name": "embedding-current",
        "model_repo": "repo",
        "base_url": "https://embedding.example/v1",
        "api_key": "secret",
        "max_tokens": 1024,
        "ssl_verify": True,
    }
    monkeypatch.setitem(
        sys.modules,
        "database.tenant_config_db",
        tenant_config_db,
    )
    monkeypatch.setitem(sys.modules, "utils.config_utils", config_utils)

    result = memory_record_service._resolve_tenant_embedding_model_info("t1")

    assert result.model_name == "embedding-current"
    assert result.get_index_name() == "mem_repo_embedding-current_1024"
    config_utils.tenant_config_manager.get_model_config.assert_called_once_with(
        "EMBEDDING_ID",
        tenant_id="t1",
    )


def test_resolve_tenant_embedding_model_requires_active_config(monkeypatch):
    tenant_config_db = types.ModuleType("database.tenant_config_db")
    tenant_config_db.get_single_config_info = MagicMock(return_value={})
    config_utils = types.ModuleType("utils.config_utils")
    config_utils.tenant_config_manager = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "database.tenant_config_db",
        tenant_config_db,
    )
    monkeypatch.setitem(sys.modules, "utils.config_utils", config_utils)

    assert (
        memory_record_service._resolve_tenant_embedding_model_info("t1")
        is None
    )
    config_utils.tenant_config_manager.get_model_config.assert_not_called()


def test_resolve_tenant_embedding_model_lookup_exception(monkeypatch):
    # ``_resolve_tenant_embedding_model_info`` swallows DB/config lookup
    # exceptions and returns ``None``.
    tenant_config_db = types.ModuleType("database.tenant_config_db")

    def _raise(*_args, **_kwargs):
        raise RuntimeError("config db down")

    tenant_config_db.get_single_config_info = _raise
    config_utils = types.ModuleType("utils.config_utils")
    config_utils.tenant_config_manager = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "database.tenant_config_db",
        tenant_config_db,
    )
    monkeypatch.setitem(sys.modules, "utils.config_utils", config_utils)

    assert (
        memory_record_service._resolve_tenant_embedding_model_info("t1")
        is None
    )


def test_resolve_tenant_embedding_model_missing_model_config(monkeypatch):
    # Active EMBEDDING_ID but no resolvable model config.
    tenant_config_db = types.ModuleType("database.tenant_config_db")
    tenant_config_db.get_single_config_info = MagicMock(
        return_value={"config_value": "42"}
    )
    config_utils = types.ModuleType("utils.config_utils")
    config_utils.tenant_config_manager = MagicMock()
    config_utils.tenant_config_manager.get_model_config.return_value = None
    monkeypatch.setitem(
        sys.modules,
        "database.tenant_config_db",
        tenant_config_db,
    )
    monkeypatch.setitem(sys.modules, "utils.config_utils", config_utils)

    assert (
        memory_record_service._resolve_tenant_embedding_model_info("t1")
        is None
    )


def test_resolve_tenant_embedding_model_incomplete_config(monkeypatch):
    # Missing base_url / dimension causes the function to bail out.
    tenant_config_db = types.ModuleType("database.tenant_config_db")
    tenant_config_db.get_single_config_info = MagicMock(
        return_value={"config_value": "42"}
    )
    config_utils = types.ModuleType("utils.config_utils")
    config_utils.tenant_config_manager = MagicMock()
    config_utils.tenant_config_manager.get_model_config.return_value = {
        "model_name": "embedding-x",
        # base_url omitted
        "max_tokens": 1024,
    }
    monkeypatch.setitem(
        sys.modules,
        "database.tenant_config_db",
        tenant_config_db,
    )
    monkeypatch.setitem(sys.modules, "utils.config_utils", config_utils)

    assert (
        memory_record_service._resolve_tenant_embedding_model_info("t1")
        is None
    )


def test_resolve_tenant_embedding_model_invalid_dimension(monkeypatch):
    tenant_config_db = types.ModuleType("database.tenant_config_db")
    tenant_config_db.get_single_config_info = MagicMock(
        return_value={"config_value": "42"}
    )
    config_utils = types.ModuleType("utils.config_utils")
    config_utils.tenant_config_manager = MagicMock()
    config_utils.tenant_config_manager.get_model_config.return_value = {
        "model_name": "embedding-x",
        "base_url": "https://embedding.example/v1",
        "max_tokens": "not-a-number",
    }
    monkeypatch.setitem(
        sys.modules,
        "database.tenant_config_db",
        tenant_config_db,
    )
    monkeypatch.setitem(sys.modules, "utils.config_utils", config_utils)

    assert (
        memory_record_service._resolve_tenant_embedding_model_info("t1")
        is None
    )


def test_resolve_tenant_embedding_model_default_api_key(monkeypatch):
    # When api_key is missing, the function falls back to ``sk-no-api-key``.
    tenant_config_db = types.ModuleType("database.tenant_config_db")
    tenant_config_db.get_single_config_info = MagicMock(
        return_value={"config_value": "42"}
    )
    config_utils = types.ModuleType("utils.config_utils")
    config_utils.tenant_config_manager = MagicMock()
    config_utils.tenant_config_manager.get_model_config.return_value = {
        "model_name": "embedding-x",
        "model_repo": "repo-x",
        "base_url": "https://embedding.example/v1",
        "max_tokens": 768,
        # api_key intentionally absent -> falls back to placeholder
        "ssl_verify": False,
    }
    monkeypatch.setitem(
        sys.modules,
        "database.tenant_config_db",
        tenant_config_db,
    )
    monkeypatch.setitem(sys.modules, "utils.config_utils", config_utils)

    info = memory_record_service._resolve_tenant_embedding_model_info("t1")
    assert info is not None
    assert info.api_key == "sk-no-api-key"
    assert info.ssl_verify is False


def test_is_tenant_embedding_configured(monkeypatch):
    tenant_config_db = types.ModuleType("database.tenant_config_db")
    monkeypatch.setitem(
        sys.modules,
        "database.tenant_config_db",
        tenant_config_db,
    )

    tenant_config_db.get_single_config_info = MagicMock(
        return_value={"config_value": "42"}
    )
    assert memory_record_service.is_tenant_embedding_configured("t1") is True

    tenant_config_db.get_single_config_info = MagicMock(return_value={})
    assert memory_record_service.is_tenant_embedding_configured("t1") is False

    tenant_config_db.get_single_config_info = MagicMock(return_value=None)
    assert memory_record_service.is_tenant_embedding_configured("t1") is False

    tenant_config_db.get_single_config_info = MagicMock(
        return_value={"config_value": ""}
    )
    assert memory_record_service.is_tenant_embedding_configured("t1") is False


def test_get_tenant_memory_index_name(monkeypatch):
    # With a configured model the index name is derived from the model info.
    fake_info = _FakeEmbeddingModelInfo(
        index_name="mem_resolved",
        model_repo="openai",
        model_name="text-embedding-3-small",
        dimension=1536,
    )
    monkeypatch.setattr(
        memory_record_service,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: fake_info,
    )
    assert memory_record_service.get_tenant_memory_index_name("t1") == "mem_resolved"

    # Without a configured model the index name is ``None``.
    monkeypatch.setattr(
        memory_record_service,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: None,
    )
    assert memory_record_service.get_tenant_memory_index_name("t1") is None


def test_compute_content_embedding_empty_returns_none(monkeypatch):
    fake_model_info = _FakeEmbeddingModelInfo(
        index_name="mem_x",
        model_name="m",
        model_repo="openai",
        dimension=1,
        base_url="https://embedding.example/v1",
        api_key="sk-test",
        ssl_verify=True,
    )

    fake_client_instance = MagicMock(name="embedding_client_instance")
    fake_client_instance.get_embeddings.return_value = []

    fake_client_factory = MagicMock(name="embedding_client_factory")
    fake_client_factory.return_value = fake_client_instance
    monkeypatch.setattr(memory_record_service, "get_embedding_client", fake_client_factory)

    assert (
        memory_record_service._compute_content_embedding("hello", fake_model_info)
        is None
    )


def test_compute_content_embedding_invalid_vector_type(monkeypatch):
    fake_model_info = _FakeEmbeddingModelInfo(
        index_name="mem_x",
        model_name="m",
        model_repo="openai",
        dimension=1,
        base_url="https://embedding.example/v1",
        api_key="sk-test",
        ssl_verify=True,
    )

    fake_client_instance = MagicMock(name="embedding_client_instance")
    fake_client_instance.get_embeddings.return_value = ["not-a-list"]

    fake_client_factory = MagicMock(name="embedding_client_factory")
    fake_client_factory.return_value = fake_client_instance
    monkeypatch.setattr(memory_record_service, "get_embedding_client", fake_client_factory)

    assert (
        memory_record_service._compute_content_embedding("hello", fake_model_info)
        is None
    )


def test_compute_content_embedding_exception(monkeypatch):
    fake_model_info = _FakeEmbeddingModelInfo(
        index_name="mem_x",
        model_name="m",
        model_repo="openai",
        dimension=1,
        base_url="https://embedding.example/v1",
        api_key="sk-test",
        ssl_verify=True,
    )

    fake_client_instance = MagicMock(name="embedding_client_instance")
    fake_client_instance.get_embeddings.side_effect = RuntimeError("upstream timeout")

    fake_client_factory = MagicMock(name="embedding_client_factory")
    fake_client_factory.return_value = fake_client_instance
    monkeypatch.setattr(memory_record_service, "get_embedding_client", fake_client_factory)

    assert (
        memory_record_service._compute_content_embedding("hello", fake_model_info)
        is None
    )


def test_compute_content_embedding_success(monkeypatch):
    fake_model_info = _FakeEmbeddingModelInfo(
        index_name="mem_x",
        model_name="m",
        model_repo="openai",
        dimension=3,
        base_url="https://embedding.example/v1",
        api_key="sk-test",
        ssl_verify=True,
    )

    # ``get_embedding_client`` is replaced with a callable that returns a
    # mock whose ``get_embeddings`` returns the configured embeddings.
    fake_client_instance = MagicMock(name="embedding_client_instance")
    fake_client_instance.get_embeddings.return_value = [[1, 2.5, 3]]

    fake_client_factory = MagicMock(name="embedding_client_factory")
    fake_client_factory.return_value = fake_client_instance
    monkeypatch.setattr(memory_record_service, "get_embedding_client", fake_client_factory)

    result = memory_record_service._compute_content_embedding(
        "hello", fake_model_info
    )
    assert result == [1.0, 2.5, 3.0]


def test_validate_layer_name_normalises_and_validates():
    assert memory_record_service._validate_layer_name("  AGENT ") == "agent"
    assert memory_record_service._validate_layer_name("user") == "user"
    assert memory_record_service._validate_layer_name("tenant") == "tenant"


def test_validate_layer_name_rejects_none():
    with pytest.raises(memory_record_service.MemoryRecordError):
        memory_record_service._validate_layer_name(None)


def test_validate_layer_name_rejects_unsupported():
    with pytest.raises(memory_record_service.MemoryRecordError):
        memory_record_service._validate_layer_name("nope")


def test_resolve_memory_type_default_per_layer():
    # Agent layer -> short_term; tenant/user -> long_term when caller omits type.
    assert (
        memory_record_service._resolve_memory_type("agent", None) == "short_term"
    )
    assert (
        memory_record_service._resolve_memory_type("user", None) == "long_term"
    )
    assert (
        memory_record_service._resolve_memory_type("tenant", None) == "long_term"
    )
    # Caller-provided type wins regardless of layer.
    assert (
        memory_record_service._resolve_memory_type("agent", "long_term")
        == "long_term"
    )


def test_validate_layer_policy_dreaming_allowed():
    # Dreaming writes are scoped to (user, long_term) by the stub policy.
    memory_record_service._validate_layer_policy("user", "long_term", "dreaming")


def test_validate_layer_policy_dreaming_rejected():
    with pytest.raises(memory_record_service.MemoryRecordError):
        memory_record_service._validate_layer_policy(
            "agent", "short_term", "dreaming"
        )


def test_validate_layer_policy_unknown_actor():
    with pytest.raises(memory_record_service.MemoryRecordError):
        memory_record_service._validate_layer_policy(
            "user", "long_term", "mystery-actor"
        )


def test_create_memory_insert_failure_raises(service, fake_db):
    # ``memory_record_db.insert_memory_record`` returning ``None`` should
    # surface as a ``MemoryRecordError``.
    fake_db.find_by_idempotency.return_value = None
    fake_db.insert_memory_record.return_value = None

    with pytest.raises(memory_record_service.MemoryRecordError):
        service.create_memory(
            tenant_id="t1",
            user_id="u1",
            content="x",
            layer="user",
            memory_type="long_term",
            idempotency_key="k",
            actor="system",
        )
    service.index_service.index_record.assert_not_called()


def test_create_memory_update_path_indexes_when_index_available(service, fake_db):
    # UPDATE branch with an agent-layer record that has an ES index.
    fake_db.find_by_idempotency.return_value = {
        "memory_id": 5,
        "tenant_id": "t1",
        "user_id": "u1",
        "content": "old",
        "memory_type": "short_term",
        "layer": "agent",
        "es_index_name": "mem_current",
    }
    fake_db.upsert_memory_record_by_idempotency.return_value = 5

    fake_index_info = _FakeEmbeddingModelInfo(index_name="mem_current")

    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="new content",
        layer="agent",
        memory_type="short_term",
        agent_id="a1",
        idempotency_key="k1",
        embedding=[0.5, 0.6],
        embedding_model_info=fake_index_info,
    )
    assert result["event"] == "UPDATE"
    assert result["memory_id"] == 5
    # Indexer is called because an index name is available.
    service.index_service.index_record.assert_called_once()


def test_create_memory_strips_es_index_name_for_non_agent_layers(service, fake_db):
    # When the layer is not agent, the es_index_name must be dropped from
    # the persisted record before insert.
    fake_db.find_by_idempotency.return_value = None

    service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="x",
        layer="user",
        memory_type="long_term",
        idempotency_key="k",
        actor="system",
    )

    record_passed = fake_db.insert_memory_record.call_args.args[0]
    assert "es_index_name" not in record_passed


def test_create_memory_generates_idempotency_key_when_missing(service, fake_db):
    # The auto-generated UUID path should still result in a deterministic
    # ADD response with the generated key carried into the insert payload.
    fake_db.find_by_idempotency.return_value = None

    result = service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="x",
        layer="user",
        memory_type="long_term",
        actor="system",
    )
    assert result["event"] == "ADD"
    record_passed = fake_db.insert_memory_record.call_args.args[0]
    assert isinstance(record_passed["idempotency_key"], str)
    assert len(record_passed["idempotency_key"]) == 36  # uuid4 hex+hyphens


def test_create_memory_admin_actor_allowed(service, fake_db):
    fake_db.find_by_idempotency.return_value = None
    # Admin can write to any layer.
    service.create_memory(
        tenant_id="t1",
        user_id="u1",
        content="x",
        layer="user",
        memory_type="long_term",
        actor="admin",
    )
    fake_db.insert_memory_record.assert_called_once()


def test_update_memory_layer_change_validates_policy(service, fake_db, monkeypatch):
    # When ``layer`` and ``memory_type`` are supplied, the policy check runs.
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "layer": "user",
    }
    fake_db.update_memory_record.return_value = True

    with pytest.raises(memory_record_service.MemoryRecordError):
        # ``agent`` cannot write ``long_term`` per the stub policy.
        service.update_memory(
            1,
            "t1",
            {"layer": "agent", "memory_type": "long_term"},
            actor="agent",
        )


def test_update_memory_missing_record_returns_false(service, fake_db):
    fake_db.get_memory_record.return_value = None
    ok = service.update_memory(1, "t1", {"content": "new"}, actor="system")
    assert ok is False
    fake_db.update_memory_record.assert_not_called()


def test_update_memory_db_update_failure_returns_false(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "layer": "user",
        "memory_type": "long_term",
    }
    fake_db.update_memory_record.return_value = False
    ok = service.update_memory(1, "t1", {"content": "new"}, actor="system")
    assert ok is False
    service.index_service.index_record.assert_not_called()


def test_update_memory_content_change_on_agent_reindexes(service, fake_db, monkeypatch):
    # When the layer is agent and content changes, the index service is
    # invoked with a freshly-computed embedding.
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "user_id": "u1",
        "agent_id": "a1",
        "conversation_id": "c1",
        "layer": "agent",
        "memory_type": "short_term",
        "status": "active",
        "content": "old",
        "idempotency_key": "k",
        "created_by": "u1",
    }
    fake_db.update_memory_record.return_value = True

    fake_info = _FakeEmbeddingModelInfo(index_name="mem_current")

    def _resolve(_tenant_id):
        return fake_info

    monkeypatch.setattr(
        memory_record_service, "_resolve_tenant_embedding_model_info", _resolve
    )

    fake_compute = MagicMock(return_value=[0.9, 0.8])
    monkeypatch.setattr(memory_record_service, "_compute_content_embedding", fake_compute)

    ok = service.update_memory(
        1, "t1", {"content": "new"}, actor="system"
    )
    assert ok is True
    fake_compute.assert_called_once()
    service.index_service.index_record.assert_called_once()
    call_kwargs = service.index_service.index_record.call_args.kwargs
    assert call_kwargs["embedding"] == [0.9, 0.8]
    assert call_kwargs["embedding_model_info"] == fake_info


def test_update_memory_content_change_without_embedding_model(service, fake_db, monkeypatch):
    # If the tenant has no embedding configured, the reindex is attempted
    # with ``embedding=None``.
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "user_id": "u1",
        "agent_id": None,
        "conversation_id": None,
        "layer": "agent",
        "memory_type": "short_term",
        "status": "active",
        "content": "old",
        "idempotency_key": "k",
        "created_by": "u1",
    }
    fake_db.update_memory_record.return_value = True
    monkeypatch.setattr(
        memory_record_service,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: None,
    )

    ok = service.update_memory(
        1, "t1", {"content": "new"}, actor="system"
    )
    assert ok is True
    service.index_service.index_record.assert_called_once()
    assert service.index_service.index_record.call_args.kwargs["embedding"] is None


def test_update_memory_non_content_change_skips_index(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "layer": "agent",
        "memory_type": "short_term",
    }
    fake_db.update_memory_record.return_value = True

    ok = service.update_memory(1, "t1", {"status": "archived"}, actor="system")
    assert ok is True
    service.index_service.index_record.assert_not_called()


def test_update_memory_user_layer_content_change_skips_index(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "layer": "user",
        "memory_type": "long_term",
    }
    fake_db.update_memory_record.return_value = True

    ok = service.update_memory(1, "t1", {"content": "x"}, actor="system")
    assert ok is True
    service.index_service.index_record.assert_not_called()


def test_update_memory_uses_existing_layer_when_not_in_update(
    service, fake_db, monkeypatch
):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "layer": "agent",
        "memory_type": "short_term",
        "content": "old",
    }
    fake_db.update_memory_record.return_value = True
    monkeypatch.setattr(
        memory_record_service,
        "_resolve_tenant_embedding_model_info",
        lambda _tenant_id: None,
    )

    # Update omits ``layer``; service should still detect the existing
    # agent layer and reindex on content change.
    ok = service.update_memory(1, "t1", {"content": "new"}, actor="system")
    assert ok is True
    service.index_service.index_record.assert_called_once()


def test_soft_delete_memory_missing_record_returns_false(service, fake_db):
    fake_db.get_memory_record.return_value = None
    ok = service.soft_delete_memory(1, "t1")
    assert ok is False
    fake_db.soft_delete_memory_record.assert_not_called()


def test_soft_delete_memory_skips_index_when_no_index_name(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "es_index_name": None,
    }
    ok = service.soft_delete_memory(1, "t1")
    assert ok is True
    service.index_service.delete_record.assert_not_called()


def test_soft_delete_memory_cascade_disabled(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "es_index_name": "mem_idx",
    }
    ok = service.soft_delete_memory(1, "t1", cascade_index=False)
    assert ok is True
    service.index_service.delete_record.assert_not_called()


def test_get_memory_passes_through(service, fake_db):
    fake_db.get_memory_record.return_value = {"memory_id": 7}
    assert service.get_memory(7, "t1") == {"memory_id": 7}
    fake_db.get_memory_record.assert_called_once_with(7, "t1")


def test_get_memory_for_user_tenant_layer_visible(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "user_id": "other-user",
        "layer": "tenant",
    }
    record = service.get_memory_for_user(1, "t1", user_id="u1")
    assert record is not None
    assert record["layer"] == "tenant"


def test_get_memory_for_user_owner_match(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "user_id": "u1",
        "layer": "user",
    }
    record = service.get_memory_for_user(1, "t1", user_id="u1")
    assert record is not None


def test_get_memory_for_user_cross_user_blocked(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "user_id": "u1",
        "layer": "user",
    }
    record = service.get_memory_for_user(1, "t1", user_id="u-other")
    assert record is None


def test_get_memory_for_user_missing(service, fake_db):
    fake_db.get_memory_record.return_value = None
    record = service.get_memory_for_user(1, "t1", user_id="u1")
    assert record is None


def test_get_memory_for_user_user_layer_owner_match(service, fake_db):
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "user_id": "u1",
        "layer": "user",
    }
    record = service.get_memory_for_user(1, "t1", user_id="u1")
    assert record is not None


def test_get_memory_for_user_no_user_id_record(service, fake_db):
    # Records without a user_id are visible to any caller.
    fake_db.get_memory_record.return_value = {
        "memory_id": 1,
        "tenant_id": "t1",
        "user_id": None,
        "layer": "user",
    }
    record = service.get_memory_for_user(1, "t1", user_id="u-other")
    assert record is not None


def test_list_full_context_memories_default_layers(service, fake_db, monkeypatch):
    fake_db.list_memory_records.side_effect = [
        [{"memory_id": 1, "layer": "tenant"}],
        [{"memory_id": 2, "layer": "user"}],
    ]
    monkeypatch.setattr(
        memory_record_service,
        "get_tenant_memory_index_name",
        lambda _tenant_id: None,
    )
    rows = service.list_full_context_memories("t1", user_id="u1")
    assert len(rows) == 2
    # Called once for ``tenant`` and once for ``user``.
    assert fake_db.list_memory_records.call_count == 2


def test_list_full_context_memories_skips_non_full_context_layers(
    service, fake_db, monkeypatch
):
    # Agent layer is not a full-context layer per the stub policy and must
    # be skipped entirely.
    fake_db.list_memory_records.return_value = [
        {"memory_id": 1, "layer": "agent"},
    ]
    monkeypatch.setattr(
        memory_record_service,
        "get_tenant_memory_index_name",
        lambda _tenant_id: None,
    )
    rows = service.list_full_context_memories(
        "t1", user_id="u1", layers=["agent"]
    )
    assert rows == []
    fake_db.list_memory_records.assert_not_called()


def test_get_and_reset_memory_record_service():
    memory_record_service.reset_memory_record_service()
    svc1 = memory_record_service.get_memory_record_service()
    svc2 = memory_record_service.get_memory_record_service()
    # Subsequent calls return the cached singleton.
    assert svc1 is svc2
    memory_record_service.reset_memory_record_service()
    svc3 = memory_record_service.get_memory_record_service()
    assert svc3 is not svc1


def test_now_iso_returns_isoformat_string():
    # ``_now_iso`` is a small helper used for log timestamps.
    import re

    iso = memory_record_service._now_iso()
    assert isinstance(iso, str)
    # ISO-8601 timestamp shape ``YYYY-MM-DDTHH:MM:SS.ffffff``.
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", iso)
