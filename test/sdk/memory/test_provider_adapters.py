"""Tests for the vendor-neutral memory provider adapter."""

from nexent.memory.models import MemoryIngestRequest, MemoryIngestUnit, MemorySearchRequest
from nexent.memory.providers.adapters.base import BaseMemoryAdapter


class TestBaseMemoryAdapter:
    """Tests for BaseMemoryAdapter."""

    def test_provider_name(self):
        adapter = BaseMemoryAdapter()
        assert adapter.provider_name == "base"

    def test_normalize_search_result(self):
        adapter = BaseMemoryAdapter()
        raw = {
            "id": "test-id",
            "content": "test content",
            "score": 0.95,
            "metadata": {"key": "value"},
        }
        result = adapter.normalize_search_result(raw)
        assert result.external_id == "test-id"
        assert result.content == "test content"
        assert result.score == 0.95
        assert result.is_external is True

    def test_normalize_search_result_with_text_field(self):
        adapter = BaseMemoryAdapter()
        raw = {"id": "test-id", "text": "text field content"}
        result = adapter.normalize_search_result(raw)
        assert result.content == "text field content"

    def test_normalize_search_results(self):
        adapter = BaseMemoryAdapter()
        raw_results = [
            {"id": "1", "content": "first"},
            {"id": "2", "content": "second"},
        ]
        results = adapter.normalize_search_results(raw_results)
        assert len(results) == 2
        assert results[0].external_id == "1"
        assert results[1].external_id == "2"

    def test_adapt_search_request(self):
        adapter = BaseMemoryAdapter()
        request = MemorySearchRequest(
            query="test query",
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
            limit=5,
        )
        adapted = adapter.adapt_search_request(request)
        assert adapted["query"] == "test query"
        assert adapted["limit"] == 5
        assert adapted["filters"]["tenant_id"] == "tenant-1"

    def test_adapt_ingest_request(self):
        adapter = BaseMemoryAdapter()
        unit = MemoryIngestUnit(
            event_id="evt-1",
            event_type="message",
            unit_type="model_output",
            unit_content="Test content",
        )
        request = MemoryIngestRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            units=[unit],
            idempotency_key="idem-1",
        )
        adapted = adapter.adapt_ingest_request(request)
        assert adapted["tenant_id"] == "tenant-1"
        assert adapted["user_id"] == "user-1"
        assert len(adapted["events"]) == 1
