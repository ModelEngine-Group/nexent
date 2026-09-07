"""Unit tests for ``backend.services.memory_context_service``.

Covers:

- ``_prepare_search_embedding`` resolving the embedding model and computing the
  query embedding (and its edge cases: pre-supplied embedding, empty query,
  missing tenant model, embedding-computation failure).
- ``_build_pipeline_config`` reading the env-var driven constants.
- ``MemoryContextService.pipeline`` lazy property.
- ``MemoryContextService.build_context`` for the pipeline-enabled and
  pipeline-disabled branches, including:
    * default vs explicit ``layers`` (with mixed valid / unknown entries),
    * pre-supplied ``embedding`` and ``embedding_model_info``,
    * ``write_hits`` toggling based on whether ``query`` is provided,
    * results bucketed into ``tenant_long_term`` / ``user_long_term`` /
      ``agent_short_term`` / ``external`` when the pipeline is disabled,
    * external results forwarded into the pipeline.
- The module-level ``get_memory_context_service`` / ``reset_memory_context_service``
  cache/reset behaviour.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# Path + module stubs (mirror the pattern in test_memory_retrieval_service.py)
# ---------------------------------------------------------------------------


# Ensure the project root is importable so ``backend.services`` resolves.
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# Stub ``database`` so transitive imports succeed without a real DB.
database_pkg = types.ModuleType("database")
database_pkg.memory_long_term_db = MagicMock(name="memory_long_term_db")
database_pkg.memory_dreaming_db = MagicMock(name="memory_dreaming_db")
database_pkg.memory_dreaming_db.get_active_version.return_value = None
database_pkg.memory_record_db = MagicMock(name="memory_record_db")
database_pkg.memory_retrieval_hit_db = MagicMock(name="memory_retrieval_hit_db")
sys.modules["database"] = database_pkg
sys.modules["backend.database"] = database_pkg


# Stub ``nexent`` package + sub-modules.
nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")
memory_pkg.__path__ = []

embedding_model_pkg = types.ModuleType("nexent.memory.embedding_model")
embedding_model_pkg.EmbeddingModelInfo = MagicMock(name="EmbeddingModelInfo")
embedding_model_pkg.get_embedding_client = MagicMock(name="get_embedding_client")
memory_pkg.embedding_model = embedding_model_pkg
sys.modules["nexent.memory.embedding_model"] = embedding_model_pkg

memory_models = types.ModuleType("nexent.memory.models")


class _Singleton:
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __repr__(self):
        return f"MemoryLayer.{self.name.upper()}"


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


class ExternalMemoryItem:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


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


class MemorySearchContext:
    def __init__(self, **kwargs):
        self.tenant_long_term: list = kwargs.get("tenant_long_term", [])
        self.user_long_term: list = kwargs.get("user_long_term", [])
        self.agent_short_term: list = kwargs.get("agent_short_term", [])
        self.external: list = kwargs.get("external", [])


class PipelineConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class PipelineResult:
    """Stand-in that mimics ``RetrievalPipeline.run``'s return value."""

    def __init__(self, tenant=(), user=(), agent=(), external=()):
        self.tenant_long_term = list(tenant)
        self.user_long_term = list(user)
        self.agent_short_term = list(agent)
        self._external = list(external)

    def into_memory_search_context(self):
        ctx = MemorySearchContext()
        ctx.tenant_long_term = self.tenant_long_term
        ctx.user_long_term = self.user_long_term
        ctx.agent_short_term = self.agent_short_term
        ctx.external = self._external
        return ctx


memory_models.MemoryLayer = MemoryLayer
memory_models.ExternalMemoryItem = ExternalMemoryItem
memory_models.MemorySearchRequest = MemorySearchRequest
memory_models.MemorySearchResult = MemorySearchResult
memory_models.MemorySearchContext = MemorySearchContext
memory_models.PipelineConfig = PipelineConfig


# Provide a minimal ``MemoryType`` so ``memory_record_service`` can import it.
class MemoryType:
    short_term = _Singleton("short_term", "short_term")
    long_term = _Singleton("long_term", "long_term")
    SHORT_TERM = short_term
    LONG_TERM = long_term

    def __new__(cls, value):
        if value == "short_term":
            return cls.short_term
        if value == "long_term":
            return cls.long_term
        raise ValueError(value)


memory_models.MemoryType = MemoryType
memory_pkg.models = memory_models
sys.modules["nexent.memory.models"] = memory_models


# Stub ``nexent.memory.retrieval.pipeline`` -- the module under test imports
# ``RetrievalPipeline`` from this path. We provide a MagicMock class so
# ``RetrievalPipeline(cfg)`` returns a fake that the service can configure.
retrieval_pkg = types.ModuleType("nexent.memory.retrieval")
retrieval_pkg.__path__ = []
pipeline_mod = types.ModuleType("nexent.memory.retrieval.pipeline")


class _RetrievalPipeline:
    """Captures the ``run`` kwargs and returns a configurable ``PipelineResult``."""

    instances: list = []  # noqa: RUF012

    def __init__(self, cfg):
        self.cfg = cfg
        self.run_result: PipelineResult = PipelineResult()
        self.run_calls: list = []
        type(self).instances.append(self)

    def run(self, **kwargs):
        self.run_calls.append(kwargs)
        return self.run_result


pipeline_mod.RetrievalPipeline = _RetrievalPipeline
pipeline_mod.PipelineResult = PipelineResult
retrieval_pkg.pipeline = pipeline_mod
sys.modules["nexent.memory.retrieval"] = retrieval_pkg
sys.modules["nexent.memory.retrieval.pipeline"] = pipeline_mod

memory_pkg.retrieval = retrieval_pkg
sys.modules["nexent.memory"] = memory_pkg


# Stub ``nexent.memory.policy`` with the constants the unit under test reads.
memory_policy = types.ModuleType("nexent.memory.policy")


class MemoryRetrievalPolicy:
    FULL_CONTEXT_LAYERS = {MemoryLayer.TENANT, MemoryLayer.USER}
    VECTOR_SEARCH_LAYERS = {MemoryLayer.AGENT}


memory_policy.MemoryRetrievalPolicy = MemoryRetrievalPolicy


class MemoryAccessPolicy:
    @staticmethod
    def can_agent_write(layer, memory_type):
        return True

    @staticmethod
    def can_dreaming_write(layer, memory_type):
        return True


class MemoryStoragePolicy:
    @staticmethod
    def uses_full_context_for_layer(layer):
        try:
            layer_enum = layer if isinstance(layer, MemoryLayer) else MemoryLayer(layer)
        except ValueError:
            return False
        return layer_enum in MemoryRetrievalPolicy.FULL_CONTEXT_LAYERS


memory_policy.MemoryAccessPolicy = MemoryAccessPolicy
memory_policy.MemoryStoragePolicy = MemoryStoragePolicy
memory_pkg.policy = memory_policy
sys.modules["nexent.memory.policy"] = memory_policy


nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg


# Stub ``nexent.vector_database`` + ``nexent.vector_database.base`` so the
# transitive ``memory_index_service`` import in ``memory_record_service`` can
# succeed.
vector_db_pkg = types.ModuleType("nexent.vector_database")
vector_db_pkg.__path__ = []
vector_db_base_pkg = types.ModuleType("nexent.vector_database.base")
vector_db_base_pkg.VectorDatabaseCore = MagicMock(name="VectorDatabaseCore")
vector_db_pkg.base = vector_db_base_pkg
sys.modules["nexent.vector_database"] = vector_db_pkg
sys.modules["nexent.vector_database.base"] = vector_db_base_pkg


# Stub ``services`` package so relative imports succeed.
services_pkg = types.ModuleType("services")
services_pkg.__path__ = []  # mark as package so submodule imports work
sys.modules["services"] = services_pkg


# Stub ``management.services.knowledge_base.service`` — transitively imported by
# ``memory_index_service`` during module import.
vectordb_service_mod = types.ModuleType("management.services.knowledge_base.service")
vectordb_service_mod.get_vector_db_core = MagicMock(name="get_vector_db_core")
sys.modules["management.services.knowledge_base.service"] = vectordb_service_mod


# Stub ``services.memory_index_service`` (transitive only).
memory_index_service_mod = types.ModuleType("services.memory_index_service")
memory_index_service_mod.MemoryIndexService = MagicMock(name="MemoryIndexService")
memory_index_service_mod.get_memory_index_service = MagicMock(name="get_memory_index_service")
sys.modules["services.memory_index_service"] = memory_index_service_mod


# Stub ``services.memory_record_service`` — the unit under test imports
# ``_compute_content_embedding`` and ``_resolve_tenant_embedding_model_info``
# directly from this module.
memory_record_service_mod = types.ModuleType("services.memory_record_service")
memory_record_service_mod.MemoryRecordService = MagicMock(name="MemoryRecordService")
memory_record_service_mod._compute_content_embedding = MagicMock(
    name="_compute_content_embedding", return_value=None
)
memory_record_service_mod._resolve_tenant_embedding_model_info = MagicMock(
    name="_resolve_tenant_embedding_model_info", return_value=None
)
memory_record_service_mod.get_memory_record_service = MagicMock(name="get_memory_record_service")
sys.modules["services.memory_record_service"] = memory_record_service_mod


# Stub ``services.memory_retrieval_service``.
memory_retrieval_service_mod = types.ModuleType("services.memory_retrieval_service")
memory_retrieval_service_mod.MemoryRetrievalService = MagicMock(name="MemoryRetrievalService")
memory_retrieval_service_mod.get_memory_retrieval_service = MagicMock(
    name="get_memory_retrieval_service"
)
memory_retrieval_service_mod.reset_memory_retrieval_service = MagicMock(
    name="reset_memory_retrieval_service"
)
sys.modules["services.memory_retrieval_service"] = memory_retrieval_service_mod
sys.modules["backend.services.memory_retrieval_service"] = memory_retrieval_service_mod


# Stub ``consts.const`` with the constants the unit under test imports.
consts_pkg = types.ModuleType("consts")
consts_mod = types.ModuleType("consts.const")
consts_mod.AGENT_SHORT_TERM_HALF_LIFE_DAYS = 14
consts_mod.MMR_CANDIDATE_TOP_K = 10
consts_mod.MMR_DUPLICATE_THRESHOLD = 0.92
consts_mod.MMR_FINAL_TOP_K = 5
consts_mod.MMR_LAMBDA = 0.7
consts_mod.MEMORY_TOKEN_BUDGET = 2000
consts_mod.W_AGENT_SHORT_TERM = 1.0
consts_mod.W_EXTERNAL = 0.8
consts_mod.EXTERNAL_MEMORY_SEARCH_ENABLED = True
consts_mod.ES_API_KEY = ""
consts_mod.ES_HOST = ""


class _VectorDatabaseType:
    elasticsearch = "elasticsearch"


consts_mod.VectorDatabaseType = _VectorDatabaseType
sys.modules["consts"] = consts_pkg
sys.modules["consts.const"] = consts_mod


# ---------------------------------------------------------------------------
# Import the unit under test (after the stubs above are in place)
# ---------------------------------------------------------------------------


from backend.services import memory_context_service  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pipeline_instances():
    """Reset the ``_RetrievalPipeline.instances`` cache and module service."""
    _RetrievalPipeline.instances.clear()
    memory_context_service.reset_memory_context_service()
    yield
    _RetrievalPipeline.instances.clear()
    memory_context_service.reset_memory_context_service()


@pytest.fixture
def fake_retrieval_service():
    """Return a mock ``MemoryRetrievalService`` with a configurable ``search``."""

    svc = MagicMock(name="MemoryRetrievalService")
    svc.search = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def service(fake_retrieval_service):
    return memory_context_service.MemoryContextService(
        retrieval_service=fake_retrieval_service, pipeline_enabled=True
    )


@pytest.fixture
def service_no_pipeline(fake_retrieval_service):
    return memory_context_service.MemoryContextService(
        retrieval_service=fake_retrieval_service, pipeline_enabled=False
    )


# ---------------------------------------------------------------------------
# _prepare_search_embedding
# ---------------------------------------------------------------------------


class TestPrepareSearchEmbedding:
    def test_returns_supplied_embedding_unchanged(self, monkeypatch):
        info = MagicMock(name="EmbeddingModelInfo")
        emb = [0.5, 0.6]
        resolved_info, resolved_emb = memory_context_service._prepare_search_embedding(
            query="ignored",
            embedding=emb,
            embedding_model_info=info,
            tenant_id="tn",
        )
        assert resolved_info is info
        assert resolved_emb is emb
        # The internal helpers must not be touched when the embedding is given.
        monkeypatch.setattr(
            memory_context_service,
            "_resolve_tenant_embedding_model_info",
            MagicMock(return_value="should not be called"),
        )

    def test_returns_none_none_when_query_is_empty(self, monkeypatch):
        resolve = MagicMock(return_value="should not be called")
        compute = MagicMock(return_value="should not be called")
        monkeypatch.setattr(
            memory_context_service, "_resolve_tenant_embedding_model_info", resolve
        )
        monkeypatch.setattr(
            memory_context_service, "_compute_content_embedding", compute
        )

        resolved_info, resolved_emb = memory_context_service._prepare_search_embedding(
            query="",
            embedding=None,
            embedding_model_info=None,
            tenant_id="tn",
        )
        assert resolved_info is None
        assert resolved_emb is None
        resolve.assert_not_called()
        compute.assert_not_called()

    def test_resolves_tenant_model_when_info_missing(self, monkeypatch):
        info = MagicMock(name="EmbeddingModelInfo")
        monkeypatch.setattr(
            memory_context_service,
            "_resolve_tenant_embedding_model_info",
            MagicMock(return_value=info),
        )
        monkeypatch.setattr(
            memory_context_service,
            "_compute_content_embedding",
            MagicMock(return_value=[0.1, 0.2, 0.3]),
        )

        resolved_info, resolved_emb = memory_context_service._prepare_search_embedding(
            query="hello",
            embedding=None,
            embedding_model_info=None,
            tenant_id="tn",
        )
        assert resolved_info is info
        assert resolved_emb == [0.1, 0.2, 0.3]

    def test_returns_none_none_when_tenant_model_unresolved(self, monkeypatch):
        monkeypatch.setattr(
            memory_context_service,
            "_resolve_tenant_embedding_model_info",
            MagicMock(return_value=None),
        )
        compute = MagicMock(return_value="should not be called")
        monkeypatch.setattr(memory_context_service, "_compute_content_embedding", compute)

        resolved_info, resolved_emb = memory_context_service._prepare_search_embedding(
            query="hi",
            embedding=None,
            embedding_model_info=None,
            tenant_id="tn",
        )
        assert resolved_info is None
        assert resolved_emb is None
        compute.assert_not_called()

    def test_uses_supplied_model_info_when_no_tenant_lookup(self, monkeypatch):
        info = MagicMock(name="EmbeddingModelInfo")
        resolve = MagicMock(return_value="should not be called")
        compute = MagicMock(return_value=[0.4])
        monkeypatch.setattr(
            memory_context_service, "_resolve_tenant_embedding_model_info", resolve
        )
        monkeypatch.setattr(memory_context_service, "_compute_content_embedding", compute)

        resolved_info, resolved_emb = memory_context_service._prepare_search_embedding(
            query="hi",
            embedding=None,
            embedding_model_info=info,
            tenant_id="tn",
        )
        assert resolved_info is info
        assert resolved_emb == [0.4]
        resolve.assert_not_called()
        compute.assert_called_once_with("hi", info)

    def test_logs_warning_when_embedding_computation_fails(self, monkeypatch):
        info = MagicMock(name="EmbeddingModelInfo")
        monkeypatch.setattr(
            memory_context_service,
            "_resolve_tenant_embedding_model_info",
            MagicMock(return_value=info),
        )
        monkeypatch.setattr(
            memory_context_service,
            "_compute_content_embedding",
            MagicMock(return_value=None),
        )

        resolved_info, resolved_emb = memory_context_service._prepare_search_embedding(
            query="hi",
            embedding=None,
            embedding_model_info=None,
            tenant_id="tn",
        )
        assert resolved_info is info
        # ``computed`` was None, so ``resolved_emb`` is also None.
        assert resolved_emb is None


# ---------------------------------------------------------------------------
# _build_pipeline_config
# ---------------------------------------------------------------------------


class TestBuildPipelineConfig:
    def test_reads_constants_from_consts(self, monkeypatch):
        # The module imports each constant via ``from consts.const import X``,
        # so the local binding in ``memory_context_service`` is what the
        # builder reads. Update the local bindings, not the source module.
        monkeypatch.setattr(
            memory_context_service, "AGENT_SHORT_TERM_HALF_LIFE_DAYS", 21
        )
        monkeypatch.setattr(memory_context_service, "MMR_CANDIDATE_TOP_K", 11)
        monkeypatch.setattr(memory_context_service, "MMR_DUPLICATE_THRESHOLD", 0.5)
        monkeypatch.setattr(memory_context_service, "MMR_FINAL_TOP_K", 6)
        monkeypatch.setattr(memory_context_service, "MMR_LAMBDA", 0.3)
        monkeypatch.setattr(memory_context_service, "MEMORY_TOKEN_BUDGET", 4096)
        monkeypatch.setattr(memory_context_service, "W_AGENT_SHORT_TERM", 0.4)
        monkeypatch.setattr(memory_context_service, "W_EXTERNAL", 0.6)

        cfg = memory_context_service._build_pipeline_config()

        assert cfg.mmr_lambda == 0.3
        assert cfg.mmr_candidate_top_k == 11
        assert cfg.mmr_final_top_k == 6
        assert cfg.mmr_duplicate_threshold == 0.5
        assert cfg.half_life_days == 21
        assert cfg.w_agent_short_term == 0.4
        assert cfg.w_external == 0.6
        assert cfg.token_budget == 4096


# ---------------------------------------------------------------------------
# MemoryContextService: __init__ / pipeline property
# ---------------------------------------------------------------------------


class TestServiceInit:
    def test_default_construction_uses_module_default(self, fake_retrieval_service, monkeypatch):
        monkeypatch.setattr(
            memory_context_service,
            "get_memory_retrieval_service",
            MagicMock(return_value=fake_retrieval_service),
        )
        svc = memory_context_service.MemoryContextService()
        assert svc.retrieval_service is fake_retrieval_service
        assert svc.pipeline_enabled is True
        assert svc._pipeline is None

    def test_pipeline_is_built_lazily_with_config(self, service):
        # Not built until first access.
        assert service._pipeline is None
        pipeline = service.pipeline
        assert isinstance(pipeline, _RetrievalPipeline)
        # The config is propagated to the pipeline.
        assert pipeline.cfg.mmr_lambda == 0.7
        assert pipeline.cfg.token_budget == 2000
        # Subsequent accesses return the same instance.
        assert service.pipeline is pipeline


# ---------------------------------------------------------------------------
# MemoryContextService.build_context: layer resolution
# ---------------------------------------------------------------------------


class TestBuildContextLayers:
    @pytest.mark.asyncio
    async def test_defaults_to_all_layers_when_layers_is_none(
        self, service, fake_retrieval_service
    ):
        await service.build_context(
            tenant_id="tn", user_id="u", query="hello", embedding_model_info=None
        )
        request = fake_retrieval_service.search.call_args.args[0]
        layer_values = {layer.value for layer in request.layers}
        assert layer_values == {"tenant", "user", "agent"}

    @pytest.mark.asyncio
    async def test_explicit_layers_passed_through(
        self, service, fake_retrieval_service
    ):
        await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="hello",
            layers=["tenant", "agent"],
            embedding_model_info=None,
        )
        request = fake_retrieval_service.search.call_args.args[0]
        layer_values = [layer.value for layer in request.layers]
        assert layer_values == ["tenant", "agent"]

    @pytest.mark.asyncio
    async def test_unknown_layer_entries_are_dropped(
        self, service, fake_retrieval_service
    ):
        await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="hello",
            layers=["tenant", "bogus", "user"],
            embedding_model_info=None,
        )
        request = fake_retrieval_service.search.call_args.args[0]
        layer_values = [layer.value for layer in request.layers]
        assert layer_values == ["tenant", "user"]

    @pytest.mark.asyncio
    async def test_layers_are_normalised_lowercased_and_stripped(
        self, service, fake_retrieval_service
    ):
        await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="hello",
            layers=["  AGENT ", "Tenant"],
            embedding_model_info=None,
        )
        request = fake_retrieval_service.search.call_args.args[0]
        layer_values = [layer.value for layer in request.layers]
        assert layer_values == ["agent", "tenant"]

    @pytest.mark.asyncio
    async def test_all_unknown_layers_falls_back_to_default(
        self, service, fake_retrieval_service
    ):
        await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="hello",
            layers=["bogus", "also-bad"],
            embedding_model_info=None,
        )
        request = fake_retrieval_service.search.call_args.args[0]
        layer_values = {layer.value for layer in request.layers}
        assert layer_values == {"tenant", "user", "agent"}


# ---------------------------------------------------------------------------
# MemoryContextService.build_context: embedding + write_hits
# ---------------------------------------------------------------------------


class TestBuildContextEmbedding:
    @pytest.mark.asyncio
    async def test_supplied_embedding_is_forwarded(self, service, fake_retrieval_service):
        info = MagicMock(name="EmbeddingModelInfo")
        emb = [0.11, 0.22]
        await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="hello",
            embedding=emb,
            embedding_model_info=info,
        )
        request = fake_retrieval_service.search.call_args.args[0]
        assert request.embedding is emb
        # ``write_hits`` is True because ``query`` was supplied.
        assert fake_retrieval_service.search.call_args.kwargs["write_hits"] is True

    @pytest.mark.asyncio
    async def test_write_hits_is_false_when_query_is_empty(
        self, service, fake_retrieval_service
    ):
        info = MagicMock(name="EmbeddingModelInfo")
        await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="",
            embedding_model_info=info,
        )
        assert fake_retrieval_service.search.call_args.kwargs["write_hits"] is False

    @pytest.mark.asyncio
    async def test_query_embedding_computed_when_missing(
        self, service, fake_retrieval_service, monkeypatch
    ):
        info = MagicMock(name="EmbeddingModelInfo")
        monkeypatch.setattr(
            memory_context_service,
            "_resolve_tenant_embedding_model_info",
            MagicMock(return_value=info),
        )
        monkeypatch.setattr(
            memory_context_service,
            "_compute_content_embedding",
            MagicMock(return_value=[0.7, 0.8, 0.9]),
        )
        await service.build_context(
            tenant_id="tn", user_id="u", query="hi", embedding=None
        )
        request = fake_retrieval_service.search.call_args.args[0]
        assert request.embedding == [0.7, 0.8, 0.9]
        # ``resolved_model_info`` is forwarded to ``search`` so the retrieval
        # service can build a client for the agent layer.
        assert fake_retrieval_service.search.call_args.kwargs[
            "embedding_model_info"
        ] is info

    @pytest.mark.asyncio
    async def test_top_k_and_threshold_propagated(
        self, service, fake_retrieval_service
    ):
        await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="hi",
            top_k=8,
            threshold=0.42,
            embedding_model_info=MagicMock(),
        )
        request = fake_retrieval_service.search.call_args.args[0]
        assert request.top_k == 8
        assert request.threshold == 0.42


# ---------------------------------------------------------------------------
# MemoryContextService.build_context: pipeline-enabled branch
# ---------------------------------------------------------------------------


class TestBuildContextPipelineEnabled:
    @pytest.mark.asyncio
    async def test_uses_pipeline_when_results_present(
        self, service, fake_retrieval_service
    ):
        # Pretend retrieval produced a few rows; the service should route them
        # through the pipeline and return the pipeline's context.
        tenant_result = MemorySearchResult(memory_id=1, layer=MemoryLayer.TENANT)
        user_result = MemorySearchResult(memory_id=2, layer=MemoryLayer.USER)
        agent_result = MemorySearchResult(memory_id=3, layer=MemoryLayer.AGENT)
        fake_retrieval_service.search.return_value = [tenant_result, user_result, agent_result]

        pipeline = service.pipeline
        pipeline.run_result = PipelineResult(
            tenant=[tenant_result],
            user=[user_result],
            agent=[agent_result],
            external=[],
        )

        external_item = ExternalMemoryItem(id="ext-1", content="ext", score=0.5, provider="p")
        context = await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="hello",
            embedding_model_info=MagicMock(),
            external_results=[external_item],
            created_at_for_id={1: "2024-01-01"},
        )

        # Pipeline received the retrieval results + external items + the
        # ``created_at_for_id`` mapping and the (possibly empty) ``query``.
        run_kwargs = pipeline.run_calls[0]
        assert run_kwargs["internal_results"] == [tenant_result, user_result, agent_result]
        assert run_kwargs["external_results"] == [external_item]
        assert run_kwargs["created_at_for_id"] == {1: "2024-01-01"}
        assert run_kwargs["query"] == "hello"

        # The context returned to the caller is the pipeline's converted
        # context.
        assert context.tenant_long_term == [tenant_result]
        assert context.user_long_term == [user_result]
        assert context.agent_short_term == [agent_result]
        assert context.external == []

    @pytest.mark.asyncio
    async def test_pipeline_skipped_when_no_results_and_uses_bucketing(
        self, service, fake_retrieval_service
    ):
        tenant_result = MemorySearchResult(memory_id=1, layer=MemoryLayer.TENANT)
        user_result = MemorySearchResult(memory_id=2, layer=MemoryLayer.USER)
        agent_result = MemorySearchResult(memory_id=3, layer=MemoryLayer.AGENT)
        fake_retrieval_service.search.return_value = [tenant_result, user_result, agent_result]

        # Make the pipeline instance fail if it is invoked.
        pipeline = service.pipeline
        pipeline.run = MagicMock(side_effect=AssertionError("pipeline should not run"))

        # Empty results short-circuits the pipeline path. Provide a query so
        # ``write_hits`` evaluates truthfully (no effect on the result though).
        fake_retrieval_service.search.return_value = []
        context = await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="hello",
            embedding_model_info=MagicMock(),
        )

        assert context.tenant_long_term == []
        assert context.user_long_term == []
        assert context.agent_short_term == []
        assert context.external == []
        pipeline.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_ac_p3_18_pipeline_preserves_external_when_internal_empty(
        self, service, fake_retrieval_service
    ):
        """AC-P3-18: external-only hits still traverse the retrieval pipeline."""
        fake_retrieval_service.search.return_value = []
        external_item = ExternalMemoryItem(
            id="mem0-1", content="Sister Jules has an interview", score=0.9, provider="mem0"
        )
        pipeline = service.pipeline
        pipeline.run_result = PipelineResult(external=[external_item])

        context = await service.build_context(
            tenant_id="tn",
            user_id="u",
            query="sister Jules",
            embedding_model_info=MagicMock(),
            external_results=[external_item],
        )

        assert pipeline.run_calls[0]["internal_results"] == []
        assert pipeline.run_calls[0]["external_results"] == [external_item]
        assert context.external == [external_item]


# ---------------------------------------------------------------------------
# MemoryContextService.build_context: pipeline-disabled branch
# ---------------------------------------------------------------------------


class TestBuildContextPipelineDisabled:
    @pytest.mark.asyncio
    async def test_ac_p3_18_non_pipeline_preserves_external_when_internal_empty(
        self, service_no_pipeline
    ):
        """AC-P3-18: fallback bucketing must retain external-only hits."""
        service_no_pipeline.retrieval_service.search = AsyncMock(return_value=[])
        external_item = ExternalMemoryItem(
            id="mem0-1", content="Sister Jules has an interview", score=0.9, provider="mem0"
        )

        context = await service_no_pipeline.build_context(
            tenant_id="tn",
            user_id="u",
            query="sister Jules",
            embedding_model_info=MagicMock(),
            external_results=[external_item],
        )

        assert context.external == [external_item]

    @pytest.mark.asyncio
    async def test_pipeline_disabled_buckets_results_into_context(self, service_no_pipeline):
        tenant = MemorySearchResult(memory_id=10, layer=MemoryLayer.TENANT)
        user = MemorySearchResult(memory_id=20, layer=MemoryLayer.USER)
        agent = MemorySearchResult(memory_id=30, layer=MemoryLayer.AGENT)
        # The fallback also has an ``else`` branch for unknown layers which
        # gets bucketed as ``external``.
        unknown = MemorySearchResult(
            memory_id=40, layer=_Singleton("alien", "alien")
        )
        service_no_pipeline.retrieval_service.search = AsyncMock(
            return_value=[tenant, user, agent, unknown]
        )

        context = await service_no_pipeline.build_context(
            tenant_id="tn", user_id="u", query="hi", embedding_model_info=MagicMock()
        )

        assert context.tenant_long_term == [tenant]
        assert context.user_long_term == [user]
        assert context.agent_short_term == [agent]
        assert context.external == [unknown]

    @pytest.mark.asyncio
    async def test_pipeline_disabled_with_empty_results(self, service_no_pipeline):
        service_no_pipeline.retrieval_service.search = AsyncMock(return_value=[])
        context = await service_no_pipeline.build_context(
            tenant_id="tn", user_id="u", query="hi", embedding_model_info=MagicMock()
        )
        assert context.tenant_long_term == []
        assert context.user_long_term == []
        assert context.agent_short_term == []
        assert context.external == []


# ---------------------------------------------------------------------------
# Module-level service accessors
# ---------------------------------------------------------------------------


class TestModuleAccessors:
    def test_get_memory_context_service_creates_default_singleton(self, monkeypatch):
        fake_svc = MagicMock(name="default-service")
        constructor = MagicMock(return_value=fake_svc)
        monkeypatch.setattr(memory_context_service, "MemoryContextService", constructor)

        # Reset to a known starting point.
        memory_context_service.reset_memory_context_service()
        assert memory_context_service.get_memory_context_service() is fake_svc
        # A second call returns the cached instance.
        assert memory_context_service.get_memory_context_service() is fake_svc
        constructor.assert_called_once_with()

    def test_reset_memory_context_service_clears_cache(self, monkeypatch):
        first = object()
        second = object()
        constructor = MagicMock(side_effect=[first, second])
        monkeypatch.setattr(memory_context_service, "MemoryContextService", constructor)

        memory_context_service.reset_memory_context_service()
        assert memory_context_service.get_memory_context_service() is first
        memory_context_service.reset_memory_context_service()
        assert memory_context_service.get_memory_context_service() is second
        assert constructor.call_count == 2
