import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

consts_const = types.ModuleType("consts.const")
consts_const.EXTERNAL_MEMORY_SEARCH_ENABLED = True
consts_const.AGENT_SHORT_TERM_HALF_LIFE_DAYS = 7.0
consts_const.MMR_CANDIDATE_TOP_K = 10
consts_const.MMR_DUPLICATE_THRESHOLD = 0.92
consts_const.MMR_FINAL_TOP_K = 5
consts_const.MMR_LAMBDA = 0.7
consts_const.MEMORY_TOKEN_BUDGET = 2000
consts_const.W_AGENT_SHORT_TERM = 0.6
consts_const.W_EXTERNAL = 0.4
consts_const.VectorDatabaseType = MagicMock()
sys.modules["consts.const"] = consts_const
sys.modules["consts"] = types.ModuleType("consts")

nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")
memory_pkg.__path__ = []

vector_db_pkg = types.ModuleType("nexent.vector_database")
vector_db_pkg.__path__ = []
vector_db_base = types.ModuleType("nexent.vector_database.base")
vector_db_base.VectorDatabaseCore = MagicMock
vector_db_pkg.base = vector_db_base
nexent_pkg.vector_database = vector_db_pkg
sys.modules["nexent.vector_database"] = vector_db_pkg
sys.modules["nexent.vector_database.base"] = vector_db_base

embedding_model_mod = types.ModuleType("nexent.memory.embedding_model")
embedding_model_mod.EmbeddingModelInfo = MagicMock
embedding_model_mod.get_embedding_client = MagicMock(return_value=None)
embedding_model_mod.resolve_embedding_model_info = MagicMock(return_value=None)
sys.modules["nexent.memory.embedding_model"] = embedding_model_mod

memory_models = types.ModuleType("nexent.memory.models")


class MemoryLayer:
    def __init__(self, value=None):
        self.value = value or "agent"

    def __eq__(self, other):
        if isinstance(other, str):
            return self.value == other
        return getattr(other, "value", None) == self.value

    def __hash__(self):
        return hash(self.value)


MemoryLayer.TENANT = MemoryLayer("tenant")
MemoryLayer.USER = MemoryLayer("user")
MemoryLayer.AGENT = MemoryLayer("agent")


class MemorySearchRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemorySearchResult:
    def __init__(self, **kwargs):
        self.memory_id = kwargs.get("memory_id")
        self.content = kwargs.get("content", "")
        self.score = kwargs.get("score", 0.0)
        self.layer = kwargs.get("layer", MemoryLayer("agent"))
        self.source = kwargs.get("source", "internal")
        self.is_external = kwargs.get("is_external", False)
        self.metadata = kwargs.get("metadata", {})
        self.external_id = kwargs.get("external_id")


class MemorySearchContext:
    def __init__(self):
        self.tenant_long_term = []
        self.user_long_term = []
        self.agent_short_term = []
        self.external = []


class ExternalMemoryItem:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class PipelineConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemoryIngestUnit:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemoryType:
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"

    def __init__(self, value=None):
        self.value = value or "short_term"


memory_models.MemoryLayer = MemoryLayer
memory_models.MemorySearchRequest = MemorySearchRequest
memory_models.MemorySearchResult = MemorySearchResult
memory_models.MemorySearchContext = MemorySearchContext
memory_models.ExternalMemoryItem = ExternalMemoryItem
memory_models.PipelineConfig = PipelineConfig
memory_models.MemoryIngestUnit = MemoryIngestUnit
memory_models.MemoryType = MemoryType
memory_pkg.models = memory_models
sys.modules["nexent.memory.models"] = memory_models

retrieval_pipeline_mod = types.ModuleType("nexent.memory.retrieval.pipeline")


class FakePipelineResult:
    def into_memory_search_context(self):
        ctx = MemorySearchContext()
        return ctx


class RetrievalPipeline:
    def __init__(self, cfg):
        self.cfg = cfg

    def run(self, **kwargs):
        return FakePipelineResult()


retrieval_pipeline_mod.RetrievalPipeline = RetrievalPipeline
retrieval_pkg = types.ModuleType("nexent.memory.retrieval")
retrieval_pkg.__path__ = []
retrieval_pkg.pipeline = retrieval_pipeline_mod
memory_pkg.retrieval = retrieval_pkg
sys.modules["nexent.memory.retrieval"] = retrieval_pkg
sys.modules["nexent.memory.retrieval.pipeline"] = retrieval_pipeline_mod

policy_mod = types.ModuleType("nexent.memory.policy")


class MemoryRetrievalPolicy:
    FULL_CONTEXT_LAYERS = {MemoryLayer("tenant"), MemoryLayer("user")}
    VECTOR_SEARCH_LAYERS = {MemoryLayer("agent")}


class MemoryAccessPolicy:
    pass


class MemoryStoragePolicy:
    pass


policy_mod.MemoryRetrievalPolicy = MemoryRetrievalPolicy
policy_mod.MemoryAccessPolicy = MemoryAccessPolicy
policy_mod.MemoryStoragePolicy = MemoryStoragePolicy
memory_pkg.policy = policy_mod
sys.modules["nexent.memory.policy"] = policy_mod

nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg

memory_service_mod = types.ModuleType("nexent.memory.service")
memory_service_mod.MemoryService = MagicMock
memory_pkg.service = memory_service_mod
sys.modules["nexent.memory.service"] = memory_service_mod

services_pkg = types.ModuleType("services")
record_svc_mod = types.ModuleType("services.memory_record_service")
record_svc_mod._compute_content_embedding = MagicMock(return_value=None)
record_svc_mod._resolve_tenant_embedding_model_info = MagicMock(return_value=None)
record_svc_mod.get_memory_record_service = MagicMock()
record_svc_mod.MemoryRecordError = type("MemoryRecordError", (Exception,), {})
record_svc_mod.MemoryRecordService = MagicMock
retrieval_svc_mod = types.ModuleType("services.memory_retrieval_service")
retrieval_svc_mod.MemoryRetrievalService = MagicMock
retrieval_svc_mod.get_memory_retrieval_service = MagicMock()
index_svc_mod = types.ModuleType("services.memory_index_service")
index_svc_mod.MemoryIndexService = MagicMock
index_svc_mod.get_memory_index_service = MagicMock()
index_svc_mod.reset_memory_index_service = MagicMock()
knowledge_base_service_mod = types.ModuleType("management.services.knowledge_base.service")
knowledge_base_service_mod.get_vector_db_core = MagicMock(return_value=MagicMock())
external_provider_svc_mod = types.ModuleType("services.memory_external_provider_service")
external_provider_svc_mod.get_memory_external_provider_service = MagicMock()
ingestion_event_svc_mod = types.ModuleType("services.memory_ingestion_event_service")
ingestion_event_svc_mod.MemoryIngestionEventService = MagicMock
sys.modules["services"] = services_pkg
sys.modules["services.memory_record_service"] = record_svc_mod
sys.modules["services.memory_retrieval_service"] = retrieval_svc_mod
sys.modules["services.memory_index_service"] = index_svc_mod
sys.modules["management.services.knowledge_base.service"] = knowledge_base_service_mod
sys.modules["services.memory_external_provider_service"] = external_provider_svc_mod
sys.modules["services.memory_ingestion_event_service"] = ingestion_event_svc_mod
sys.modules["backend.services.memory_external_provider_service"] = external_provider_svc_mod
sys.modules["backend.services.memory_ingestion_event_service"] = ingestion_event_svc_mod

database_pkg = types.ModuleType("database")
database_pkg.memory_record_db = MagicMock(name="memory_record_db")
database_pkg.memory_long_term_db = MagicMock(name="memory_long_term_db")
database_pkg.memory_retrieval_hit_db = MagicMock(name="memory_retrieval_hit_db")
sys.modules["database"] = database_pkg

from backend.services.memory_context_service import MemoryContextService
from backend.services import memory_backend_adapter


@pytest.fixture
def mock_retrieval():
    svc = MagicMock()
    svc.search = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def context_service(mock_retrieval):
    return MemoryContextService(
        retrieval_service=mock_retrieval,
        pipeline_enabled=False,
    )


@pytest.mark.asyncio
async def test_build_context_with_external_search_hook_called(mock_retrieval):
    hook = AsyncMock(return_value=[ExternalMemoryItem(id="ext1", content="ext", score=0.9)])
    svc = MemoryContextService(
        retrieval_service=mock_retrieval,
        pipeline_enabled=False,
        external_search_hook=hook,
    )

    with patch("backend.services.memory_context_service.EXTERNAL_MEMORY_SEARCH_ENABLED", True):
        await svc.build_context(tenant_id="t1", user_id="u1", query="hello")

    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_context_hook_not_called_when_external_results_provided(mock_retrieval):
    hook = AsyncMock(return_value=[])
    svc = MemoryContextService(
        retrieval_service=mock_retrieval,
        pipeline_enabled=False,
        external_search_hook=hook,
    )

    ext_items = [ExternalMemoryItem(id="ext1", content="ext", score=0.9)]

    with patch("backend.services.memory_context_service.EXTERNAL_MEMORY_SEARCH_ENABLED", True):
        await svc.build_context(
            tenant_id="t1", user_id="u1", query="hello",
            external_results=ext_items,
        )

    hook.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_context_hook_failure_doesnt_break(mock_retrieval):
    hook = AsyncMock(side_effect=RuntimeError("hook failed"))
    svc = MemoryContextService(
        retrieval_service=mock_retrieval,
        pipeline_enabled=False,
        external_search_hook=hook,
    )

    with patch("backend.services.memory_context_service.EXTERNAL_MEMORY_SEARCH_ENABLED", True):
        ctx = await svc.build_context(tenant_id="t1", user_id="u1", query="hello")

    assert ctx is not None


@pytest.mark.asyncio
async def test_build_context_no_hook_configured(mock_retrieval):
    svc = MemoryContextService(
        retrieval_service=mock_retrieval,
        pipeline_enabled=False,
        external_search_hook=None,
    )

    with patch("backend.services.memory_context_service.EXTERNAL_MEMORY_SEARCH_ENABLED", True):
        ctx = await svc.build_context(tenant_id="t1", user_id="u1", query="hello")

    assert ctx is not None


@pytest.mark.asyncio
async def test_build_context_search_disabled(mock_retrieval):
    hook = AsyncMock(return_value=[])
    svc = MemoryContextService(
        retrieval_service=mock_retrieval,
        pipeline_enabled=False,
        external_search_hook=hook,
    )

    with patch("backend.services.memory_context_service.EXTERNAL_MEMORY_SEARCH_ENABLED", False):
        await svc.build_context(tenant_id="t1", user_id="u1", query="hello")

    hook.assert_not_awaited()


@pytest.mark.asyncio
async def test_backend_store_hook_external_ingest_called():
    sys.modules["nexent.memory.models"].MemoryLayer = MemoryLayer
    sys.modules["nexent.memory.models"].MemoryIngestUnit = MemoryIngestUnit
    mock_record_service = MagicMock()
    mock_record_service.create_memory.return_value = {"memory_id": 1}

    with patch.object(memory_backend_adapter, "get_memory_record_service", return_value=mock_record_service), \
         patch.object(memory_backend_adapter, "_resolve_tenant_embedding_model_info", return_value=MagicMock()), \
         patch.object(memory_backend_adapter, "_fanout_external_ingest", new_callable=AsyncMock) as m_fanout:
        await memory_backend_adapter._backend_store_hook({
            "tenant_id": "t1", "user_id": "u1", "content": "test",
            "layer": "agent", "memory_type": "short_term",
        })
        m_fanout.assert_awaited_once()


@pytest.mark.asyncio
async def test_backend_store_hook_external_ingest_has_no_deployment_switch():
    sys.modules["nexent.memory.models"].MemoryLayer = MemoryLayer
    sys.modules["nexent.memory.models"].MemoryIngestUnit = MemoryIngestUnit
    mock_record_service = MagicMock()
    mock_record_service.create_memory.return_value = {"memory_id": 1}

    with patch.object(memory_backend_adapter, "get_memory_record_service", return_value=mock_record_service), \
         patch.object(memory_backend_adapter, "_resolve_tenant_embedding_model_info", return_value=MagicMock()), \
         patch.object(memory_backend_adapter, "_fanout_external_ingest", new_callable=AsyncMock) as m_fanout:
        await memory_backend_adapter._backend_store_hook({
            "tenant_id": "t1", "user_id": "u1", "content": "test",
            "layer": "agent", "memory_type": "short_term",
        })
        m_fanout.assert_awaited_once()


@pytest.mark.asyncio
async def test_backend_store_hook_ingest_failure_doesnt_break():
    sys.modules["nexent.memory.models"].MemoryLayer = MemoryLayer
    sys.modules["nexent.memory.models"].MemoryIngestUnit = MemoryIngestUnit
    mock_record_service = MagicMock()
    mock_record_service.create_memory.return_value = {"memory_id": 1}

    with patch.object(memory_backend_adapter, "get_memory_record_service", return_value=mock_record_service), \
         patch.object(memory_backend_adapter, "_resolve_tenant_embedding_model_info", return_value=MagicMock()), \
         patch.object(memory_backend_adapter, "_fanout_external_ingest", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
        result = await memory_backend_adapter._backend_store_hook({
            "tenant_id": "t1", "user_id": "u1", "content": "test",
            "layer": "agent", "memory_type": "short_term",
        })
        assert result == {"memory_id": 1}
