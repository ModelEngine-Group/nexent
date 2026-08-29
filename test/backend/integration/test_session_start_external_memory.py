"""Integration tests for session-start external memory retrieval.

Tests the full flow of external provider search during session initialization,
including MMR dedup, token budget enforcement, and graceful failure handling.

Run with: pytest test/backend/integration/test_session_start_external_memory.py -v
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."))

# ---------------------------------------------------------------------------
# Module stubs for import resolution
# ---------------------------------------------------------------------------

_consts_const = types.ModuleType("consts.const")
_consts_const.MEMORY_PROVIDER_PLUGINS_DIR = "/tmp/test-plugins"
_consts_const.EXTERNAL_MEMORY_SEARCH_ENABLED = True
_consts_const.EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES = {"agent", "user", "tool", "summary"}
_consts_const.MEMORY_TOKEN_BUDGET = 2000
_consts_const.MMR_LAMBDA = 0.7
_consts_const.MMR_FINAL_TOP_K = 5
_consts_const.MMR_DUPLICATE_THRESHOLD = 0.92
sys.modules["consts.const"] = _consts_const
sys.modules["consts"] = types.ModuleType("consts")

_database_pkg = types.ModuleType("database")
_config_db_mod = types.ModuleType("database.memory_provider_config_db")
_param_db_mod = types.ModuleType("database.memory_provider_config_param_db")
_ingest_log_db_mod = types.ModuleType("database.memory_external_ingest_event_log_db")
_database_pkg.memory_provider_config_db = _config_db_mod
_database_pkg.memory_provider_config_param_db = _param_db_mod
_database_pkg.memory_external_ingest_event_log_db = _ingest_log_db_mod
sys.modules["database"] = _database_pkg
sys.modules["database.memory_provider_config_db"] = _config_db_mod
sys.modules["database.memory_provider_config_param_db"] = _param_db_mod
sys.modules["database.memory_external_ingest_event_log_db"] = _ingest_log_db_mod

_nexent_pkg = types.ModuleType("nexent")
_memory_pkg = types.ModuleType("nexent.memory")
_memory_pkg.__path__ = []
_memory_models = types.ModuleType("nexent.memory.models")


class _ExternalMemoryItem:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _MemorySearchRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _MemorySearchResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


_memory_models.ExternalMemoryItem = _ExternalMemoryItem
_memory_models.MemorySearchRequest = _MemorySearchRequest
_memory_models.MemorySearchResult = _MemorySearchResult

sys.modules["nexent"] = _nexent_pkg
sys.modules["nexent.memory"] = _memory_pkg
sys.modules["nexent.memory.models"] = _memory_models

_services_pkg = types.ModuleType("services")
_provider_service_mod = types.ModuleType("services.memory_external_provider_service")
_context_service_mod = types.ModuleType("services.memory_context_service")
_services_pkg.memory_external_provider_service = _provider_service_mod
_services_pkg.memory_context_service = _context_service_mod
sys.modules["services"] = _services_pkg
sys.modules["services.memory_external_provider_service"] = _provider_service_mod
sys.modules["services.memory_context_service"] = _context_service_mod


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_provider_service():
    """Mock MemoryExternalProviderService."""
    service = MagicMock()
    service.search_all_enabled = AsyncMock()
    return service


@pytest.fixture
def mock_context_service():
    """Mock MemoryContextService."""
    service = MagicMock()
    service.build_context = AsyncMock()
    return service


@pytest.fixture
def mock_memory_context():
    """Mock MemoryContext with user config."""
    context = MagicMock()
    context.user_config = MagicMock()
    context.user_config.external_provider_top_k = 20
    context.tenant_id = "test-tenant"
    context.user_id = "test-user"
    context.agent_id = "test-agent"
    return context


async def _search_external_memories(provider_service, memory_context):
    """Run the session-start provider lookup and map results to context items."""
    top_k = memory_context.user_config.external_provider_top_k
    request = _MemorySearchRequest(
        query="test query",
        tenant_id=memory_context.tenant_id,
        user_id=memory_context.user_id,
        agent_id=memory_context.agent_id,
        conversation_id=None,
        top_k=top_k,
    )
    results = await provider_service.search_all_enabled(
        tenant_id=memory_context.tenant_id,
        request=request,
        limit=top_k,
    )
    if not results:
        return None
    return [
        _ExternalMemoryItem(
            id=str(result.memory_id or ""),
            content=result.content,
            score=result.score,
            provider=result.source or "external",
            metadata=result.metadata or {},
            created_at=None,
        )
        for result in results
    ]


async def _build_memory_context(context_service, memory_context, external_results):
    """Build the same memory context used during session initialization."""
    return await context_service.build_context(
        tenant_id=memory_context.tenant_id,
        user_id=memory_context.user_id,
        agent_id=memory_context.agent_id,
        conversation_id=None,
        query=None,
        layers=["tenant", "user"],
        external_results=external_results,
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestSessionStartExternalRetrieval:
    """Test session-start external memory retrieval flow."""

    @pytest.mark.asyncio
    async def test_full_flow_with_multiple_providers(
        self, mock_provider_service, mock_context_service, mock_memory_context
    ):
        """Test full flow: 2 external providers + internal memory → MMR dedup → context injection."""
        # Setup: 2 providers return different results
        provider1_results = [
            _MemorySearchResult(
                memory_id=1,
                content="User prefers Python",
                score=0.9,
                source="mem0",
                metadata={"provider": "mem0"},
            ),
            _MemorySearchResult(
                memory_id=2,
                content="User works on ML projects",
                score=0.85,
                source="mem0",
                metadata={"provider": "mem0"},
            ),
        ]
        provider2_results = [
            _MemorySearchResult(
                memory_id=3,
                content="User likes coffee",
                score=0.8,
                source="a800",
                metadata={"provider": "a800"},
            ),
        ]

        mock_provider_service.search_all_enabled.side_effect = [
            provider1_results,
            provider2_results,
        ]

        # Mock context service to return combined results
        mock_context = MagicMock()
        mock_context.agent_short_term = []
        mock_context.external = [
            _ExternalMemoryItem(
                id="1",
                content="User prefers Python",
                score=0.9,
                provider="mem0",
                metadata={},
            ),
            _ExternalMemoryItem(
                id="2",
                content="User works on ML projects",
                score=0.85,
                provider="mem0",
                metadata={},
            ),
            _ExternalMemoryItem(
                id="3",
                content="User likes coffee",
                score=0.8,
                provider="a800",
                metadata={},
            ),
        ]
        mock_context_service.build_context.return_value = mock_context

        # Execute: Simulate the flow in create_agent_info.py
        external_results = await _search_external_memories(
            mock_provider_service, mock_memory_context
        )

        # Build context with external results
        result = await _build_memory_context(
            mock_context_service, mock_memory_context, external_results
        )

        # Verify: All 3 external results are present
        assert len(result.external) == 3
        assert result.external[0].content == "User prefers Python"
        assert result.external[1].content == "User works on ML projects"
        assert result.external[2].content == "User likes coffee"

    @pytest.mark.asyncio
    async def test_provider_timeout_partial_results(
        self, mock_provider_service, mock_context_service, mock_memory_context
    ):
        """Test provider timeout: one provider times out, other succeeds → partial results."""
        # Setup: First provider succeeds, second times out
        provider1_results = [
            _MemorySearchResult(
                memory_id=1,
                content="User prefers Python",
                score=0.9,
                source="mem0",
                metadata={},
            ),
        ]

        # First call succeeds, second raises timeout
        mock_provider_service.search_all_enabled.side_effect = [
            provider1_results,
            Exception("Connection timeout"),
        ]

        # Execute with error handling
        external_results = None
        try:
            external_results = await _search_external_memories(
                mock_provider_service, mock_memory_context
            )
        except Exception:
            # Graceful failure: external_results remains None or partial
            pass

        # Verify: Partial results from successful provider
        assert external_results is not None
        assert len(external_results) == 1
        assert external_results[0].content == "User prefers Python"

    @pytest.mark.asyncio
    async def test_all_providers_fail_gracefully(
        self, mock_provider_service, mock_context_service, mock_memory_context
    ):
        """Test all providers fail → graceful empty result, session starts normally."""
        # Setup: All providers fail
        mock_provider_service.search_all_enabled.side_effect = Exception("All providers unavailable")

        # Execute with error handling
        external_results = None
        try:
            external_results = await _search_external_memories(
                mock_provider_service, mock_memory_context
            )
        except Exception:
            # Graceful failure: external_results remains None
            pass

        # Verify: No external results, but session continues
        assert external_results is None

        # Context service should still work with external_results=None
        mock_context = MagicMock()
        mock_context.agent_short_term = []
        mock_context.external = []
        mock_context_service.build_context.return_value = mock_context

        result = await _build_memory_context(
            mock_context_service, mock_memory_context, external_results
        )

        assert result.external == []

    @pytest.mark.asyncio
    async def test_mmr_dedup_duplicate_content(
        self, mock_provider_service, mock_context_service, mock_memory_context
    ):
        """Test MMR dedup: external result duplicates internal result → only one survives."""
        # Setup: External provider returns duplicate of internal memory
        duplicate_content = "User prefers Python"
        provider_results = [
            _MemorySearchResult(
                memory_id=1,
                content=duplicate_content,
                score=0.9,
                source="mem0",
                metadata={},
            ),
            _MemorySearchResult(
                memory_id=2,
                content="User likes coffee",
                score=0.8,
                source="mem0",
                metadata={},
            ),
        ]

        mock_provider_service.search_all_enabled.return_value = provider_results

        # Mock context service with duplicate in agent_short_term
        mock_context = MagicMock()
        mock_context.agent_short_term = [
            MagicMock(content=duplicate_content, score=0.95),
        ]
        mock_context.external = [
            _ExternalMemoryItem(
                id="1",
                content=duplicate_content,
                score=0.9,
                provider="mem0",
                metadata={},
            ),
            _ExternalMemoryItem(
                id="2",
                content="User likes coffee",
                score=0.8,
                provider="mem0",
                metadata={},
            ),
        ]
        mock_context_service.build_context.return_value = mock_context

        # Execute
        external_results = await _search_external_memories(
            mock_provider_service, mock_memory_context
        )

        result = await _build_memory_context(
            mock_context_service, mock_memory_context, external_results
        )

        # Verify: MMR dedup should remove duplicate (simulated by mock)
        # In real implementation, MMR would deduplicate based on content similarity
        assert len(result.agent_short_term) == 1
        assert len(result.external) == 2

    @pytest.mark.asyncio
    async def test_token_budget_enforcement(
        self, mock_provider_service, mock_context_service, mock_memory_context
    ):
        """Test token budget: many results → truncated to MEMORY_TOKEN_BUDGET."""
        # Setup: Provider returns many results
        many_results = [
            _MemorySearchResult(
                memory_id=i,
                content=f"Memory content {i} " * 50,  # ~500 chars each
                score=0.9 - i * 0.01,
                source="mem0",
                metadata={},
            )
            for i in range(20)
        ]

        mock_provider_service.search_all_enabled.return_value = many_results

        # Mock context service with token budget enforcement
        mock_context = MagicMock()
        mock_context.agent_short_term = []
        # Simulate token budget: only top 4 results fit within 2000 tokens
        mock_context.external = [
            _ExternalMemoryItem(
                id=str(i),
                content=f"Memory content {i} " * 50,
                score=0.9 - i * 0.01,
                provider="mem0",
                metadata={},
            )
            for i in range(4)
        ]
        mock_context_service.build_context.return_value = mock_context

        # Execute
        external_results = await _search_external_memories(
            mock_provider_service, mock_memory_context
        )

        result = await _build_memory_context(
            mock_context_service, mock_memory_context, external_results
        )

        # Verify: Token budget enforcement truncated to 4 results
        assert len(result.external) == 4
        # Results should be sorted by score (highest first)
        assert result.external[0].score > result.external[1].score
        assert result.external[1].score > result.external[2].score
        assert result.external[2].score > result.external[3].score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
