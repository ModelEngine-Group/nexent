"""Tests for memory provider adapters."""

import pytest

from nexent.memory.providers.adapters.base import BaseMemoryAdapter
from nexent.memory.providers.adapters.a800_adapter import A800Adapter
from nexent.memory.providers.adapters.mem0_adapter import Mem0Adapter
from nexent.memory.models import (
    MemorySearchRequest,
    MemoryIngestRequest,
    MemoryIngestUnit,
)


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


class TestA800Adapter:
    """Tests for A800Adapter."""

    def test_provider_name(self):
        adapter = A800Adapter()
        assert adapter.provider_name == "a800"

    def test_adapt_search_request(self):
        adapter = A800Adapter()
        request = MemorySearchRequest(
            query="test query",
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
            limit=10,
            threshold=0.7,
        )
        adapted = adapter.adapt_search_request(request)
        assert adapted["query"] == "test query"
        assert adapted["tenant_id"] == "tenant-1"
        assert adapted["agent_id"] == "agent-1"
        assert adapted["top_k"] == 10
        assert adapted["threshold"] == 0.7

    def test_adapt_ingest_request(self):
        adapter = A800Adapter()
        unit = MemoryIngestUnit(
            event_id="evt-1",
            event_type="message",
            unit_type="model_output",
            unit_content="Test content",
        )
        request = MemoryIngestRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
            conversation_id="conv-1",
            units=[unit],
            idempotency_key="idem-1",
        )
        adapted = adapter.adapt_ingest_request(request)
        assert adapted["tenant_id"] == "tenant-1"
        assert adapted["user_id"] == "user-1"
        assert adapted["agent_id"] == "agent-1"
        assert adapted["conversation_id"] == "conv-1"
        assert adapted["idempotency_key"] == "idem-1"


class TestMem0Adapter:
    """Tests for Mem0Adapter."""

    def test_provider_name(self):
        adapter = Mem0Adapter()
        assert adapter.provider_name == "mem0"

    def test_normalize_search_result(self):
        adapter = Mem0Adapter()
        raw = {
            "id": "mem0-id",
            "text": "Mem0 content",
            "score": 0.88,
        }
        result = adapter.normalize_search_result(raw)
        assert result.external_id == "mem0-id"
        assert result.content == "Mem0 content"
        assert result.score == 0.88
        assert result.is_external is True

    def test_adapt_search_request(self):
        adapter = Mem0Adapter()
        request = MemorySearchRequest(
            query="test query",
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
            limit=10,
        )
        adapted = adapter.adapt_search_request(request)
        assert adapted["query"] == "test query"
        assert adapted["user_id"] == "user-1"
        assert adapted["top_k"] == 10
        # Mem0 includes both tenant_id and agent_id in the filter
        assert adapted["filter"]["tenant_id"] == "tenant-1"
        assert adapted["filter"]["agent_id"] == "agent-1"

    def test_adapt_search_request_with_tenant(self):
        adapter = Mem0Adapter()
        request = MemorySearchRequest(
            query="test query",
            tenant_id="tenant-1",
            user_id="user-1",
            limit=5,
        )
        adapted = adapter.adapt_search_request(request)
        assert adapted["filter"]["tenant_id"] == "tenant-1"

    def test_adapt_ingest_request(self):
        adapter = Mem0Adapter()
        unit = MemoryIngestUnit(
            event_id="evt-1",
            event_type="message",
            unit_type="model_output",
            unit_content="Test content",
        )
        request = MemoryIngestRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
            conversation_id="conv-1",
            units=[unit],
            idempotency_key="idem-1",
        )
        adapted = adapter.adapt_ingest_request(request)
        assert adapted["user_id"] == "user-1"
        assert adapted["agent_id"] == "agent-1"
        assert adapted["idempotency_key"] == "idem-1"
        assert len(adapted["memory"]) == 1
        assert adapted["memory"][0]["content"] == "Test content"

    def test_adapt_ingest_response(self):
        adapter = Mem0Adapter()
        unit = MemoryIngestUnit(
            event_id="evt-1",
            event_type="message",
            unit_type="model_output",
            unit_content="Test",
        )
        request = MemoryIngestRequest(
            tenant_id="tenant-1",
            user_id="user-1",
            units=[unit],
            idempotency_key="idem-1",
        )
        response = {
            "status": "success",
            "memory_ids": ["mem-id-1"],
            "failed_count": 0,
        }
        result = adapter.adapt_ingest_response(response, request)
        assert result.status == "success"
        assert result.accepted_count == 1
        assert result.rejected_count == 0
        assert len(result.unit_results) == 1
