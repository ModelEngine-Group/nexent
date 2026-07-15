"""Tests for memory models."""

import pytest
from datetime import datetime

from nexent.memory.models import (
    MemoryLayer,
    MemoryType,
    MemoryStatus,
    MemoryRecord,
    ExternalMemoryItem,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryIngestUnit,
    MemoryIngestRequest,
    MemoryIngestResult,
    UnitIngestResult,
    UnitIngestStatus,
    ProviderError,
    ProviderErrorCode,
    ProviderErrorSeverity,
    MemoryConfig,
    MemorySearchContext,
    StoreMemoryResult,
)


class TestMemoryLayer:
    """Tests for MemoryLayer enum."""

    def test_all_layers_defined(self):
        assert MemoryLayer.TENANT.value == "tenant"
        assert MemoryLayer.USER.value == "user"
        assert MemoryLayer.AGENT.value == "agent"

    def test_layer_is_string_enum(self):
        assert isinstance(MemoryLayer.TENANT, str)


class TestMemoryType:
    """Tests for MemoryType enum."""

    def test_all_types_defined(self):
        assert MemoryType.SHORT_TERM.value == "short_term"
        assert MemoryType.LONG_TERM.value == "long_term"


class TestMemoryStatus:
    """Tests for MemoryStatus enum."""

    def test_all_statuses_defined(self):
        assert MemoryStatus.ACTIVE.value == "active"
        assert MemoryStatus.ARCHIVED.value == "archived"


class TestMemoryRecord:
    """Tests for MemoryRecord model."""

    def test_create_minimal_record(self):
        record = MemoryRecord(
            tenant_id="tenant-1",
            user_id="user-1",
            idempotency_key="key-1",
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
            content="Test content",
        )
        assert record.tenant_id == "tenant-1"
        assert record.memory_id is not None
        assert record.content == "Test content"
        assert record.status == MemoryStatus.ACTIVE
        assert record.deleted_flag == "N"

    def test_create_record_with_all_fields(self):
        record = MemoryRecord(
            memory_id="mem-123",
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
            conversation_id="conv-1",
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
            content="Full test content",
            concept_tags=["tag1", "tag2"],
            recall_count=5,
            idempotency_key="key-1",
        )
        assert record.memory_id == "mem-123"
        assert record.agent_id == "agent-1"
        assert record.conversation_id == "conv-1"
        assert len(record.concept_tags) == 2
        assert record.recall_count == 5

    def test_record_default_values(self):
        record = MemoryRecord(
            tenant_id="tenant-1",
            user_id="user-1",
            idempotency_key="key-1",
            layer=MemoryLayer.TENANT,
            memory_type=MemoryType.LONG_TERM,
            content="Test",
        )
        assert record.recall_count == 0
        assert record.daily_count == 0
        assert record.light_hits == 0
        assert record.rem_hits == 0
        assert record.deleted_flag == "N"

    def test_record_uuid_generated(self):
        record1 = MemoryRecord(
            tenant_id="tenant-1",
            user_id="user-1",
            idempotency_key="key-1",
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
            content="Test",
        )
        record2 = MemoryRecord(
            tenant_id="tenant-1",
            user_id="user-1",
            idempotency_key="key-2",
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
            content="Test2",
        )
        assert record1.memory_id != record2.memory_id

    def test_record_timestamps(self):
        record = MemoryRecord(
            tenant_id="tenant-1",
            user_id="user-1",
            idempotency_key="key-1",
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
            content="Test",
        )
        assert record.create_time is not None
        assert record.update_time is not None


class TestExternalMemoryItem:
    """Tests for ExternalMemoryItem model."""

    def test_create_external_item(self):
        item = ExternalMemoryItem(
            id="ext-1",
            content="External content",
            score=0.95,
            provider="mem0",
        )
        assert item.id == "ext-1"
        assert item.score == 0.95
        assert item.provider == "mem0"
        assert item.metadata == {}

    def test_external_item_with_metadata(self):
        item = ExternalMemoryItem(
            id="ext-2",
            content="With metadata",
            score=0.8,
            provider="a800",
            metadata={"key": "value"},
        )
        assert item.metadata["key"] == "value"


class TestMemorySearchRequest:
    """Tests for MemorySearchRequest model."""

    def test_create_search_request(self):
        request = MemorySearchRequest(
            query="test query",
            tenant_id="tenant-1",
            user_id="user-1",
        )
        assert request.query == "test query"
        assert request.limit == 5
        assert request.threshold == 0.65

    def test_search_request_custom_params(self):
        request = MemorySearchRequest(
            query="specific query",
            tenant_id="tenant-1",
            user_id="user-1",
            agent_id="agent-1",
            conversation_id="conv-1",
            layers=[MemoryLayer.AGENT],
            limit=10,
            threshold=0.7,
        )
        assert request.agent_id == "agent-1"
        assert len(request.layers) == 1
        assert request.limit == 10


class TestMemorySearchResult:
    """Tests for MemorySearchResult model."""

    def test_create_search_result(self):
        result = MemorySearchResult(
            memory_id="mem-1",
            content="Found content",
            score=0.9,
            layer=MemoryLayer.AGENT,
        )
        assert result.memory_id == "mem-1"
        assert result.score == 0.9
        assert result.source == "internal"
        assert result.is_external is False

    def test_external_search_result(self):
        result = MemorySearchResult(
            external_id="ext-1",
            content="External content",
            score=0.85,
            source="mem0",
            is_external=True,
        )
        assert result.external_id == "ext-1"
        assert result.is_external is True


class TestMemoryIngestUnit:
    """Tests for MemoryIngestUnit model."""

    def test_create_ingest_unit(self):
        unit = MemoryIngestUnit(
            event_id="evt-1",
            event_type="message",
            unit_type="model_output",
            unit_content="Agent response",
        )
        assert unit.event_id == "evt-1"
        assert unit.unit_type == "model_output"


class TestMemoryIngestRequest:
    """Tests for MemoryIngestRequest model."""

    def test_create_ingest_request(self):
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
        assert len(request.units) == 1
        assert request.idempotency_key == "idem-1"


class TestMemoryIngestResult:
    """Tests for MemoryIngestResult model."""

    def test_create_ingest_result(self):
        result = MemoryIngestResult(
            provider="mem0",
            status="ok",
            accepted_count=5,
            rejected_count=0,
        )
        assert result.provider == "mem0"
        assert result.status == "ok"
        assert result.accepted_count == 5


class TestUnitIngestResult:
    """Tests for UnitIngestResult model."""

    def test_create_unit_result(self):
        result = UnitIngestResult(
            unit_id="unit-1",
            status=UnitIngestStatus.ACCEPTED,
        )
        assert result.unit_id == "unit-1"
        assert result.status == UnitIngestStatus.ACCEPTED


class TestProviderError:
    """Tests for ProviderError model."""

    def test_create_provider_error(self):
        error = ProviderError(
            code=ProviderErrorCode.TIMEOUT,
            message="Request timed out",
            severity=ProviderErrorSeverity.RETRYABLE,
        )
        assert error.code == ProviderErrorCode.TIMEOUT
        assert error.severity == ProviderErrorSeverity.RETRYABLE

    def test_provider_error_with_retry_after(self):
        error = ProviderError(
            code=ProviderErrorCode.RATE_LIMITED,
            message="Rate limited",
            severity=ProviderErrorSeverity.RETRYABLE,
            retry_after_seconds=60,
        )
        assert error.retry_after_seconds == 60


class TestProviderErrorCodes:
    """Tests for ProviderErrorCode enum."""

    def test_all_error_codes_defined(self):
        codes = [
            ProviderErrorCode.TIMEOUT,
            ProviderErrorCode.RATE_LIMITED,
            ProviderErrorCode.PROVIDER_ERROR,
            ProviderErrorCode.UNAUTHORIZED,
            ProviderErrorCode.FORBIDDEN,
            ProviderErrorCode.UNSUPPORTED_UNIT_TYPE,
            ProviderErrorCode.INVALID_PAYLOAD,
            ProviderErrorCode.SCHEMA_MISMATCH,
            ProviderErrorCode.UNKNOWN,
        ]
        assert len(codes) == 9


class TestProviderErrorSeverity:
    """Tests for ProviderErrorSeverity enum."""

    def test_all_severities_defined(self):
        assert ProviderErrorSeverity.RETRYABLE.value == "retryable"
        assert ProviderErrorSeverity.DEGRADABLE.value == "degradable"
        assert ProviderErrorSeverity.NON_RETRYABLE.value == "non_retryable"


class TestMemoryConfig:
    """Tests for MemoryConfig model."""

    def test_create_config(self):
        config = MemoryConfig(
            embed_model_name="text-embedding-3-small",
            embed_model_base_url="https://api.openai.com/v1",
            embed_model_api_key="sk-test",
            embed_model_dimension=1536,
            es_host="localhost",
            es_port=9200,
        )
        assert config.embed_model_name == "text-embedding-3-small"
        assert config.embed_model_dimension == 1536
        assert config.es_port == 9200

    def test_get_index_name_with_repo(self):
        config = MemoryConfig(
            embed_model_name="text-embedding-3-small",
            embed_model_repo="openai",
            embed_model_base_url="https://api.openai.com/v1",
            embed_model_api_key="sk-test",
            embed_model_dimension=1536,
            es_host="localhost",
            es_port=9200,
        )
        index_name = config.get_index_name()
        assert "mem_" in index_name
        assert "text_embedding_3_small" in index_name
        assert "1536" in index_name

    def test_get_index_name_without_repo(self):
        config = MemoryConfig(
            embed_model_name="bge-m3",
            embed_model_base_url="https://example.com",
            embed_model_api_key="sk-test",
            embed_model_dimension=1024,
            es_host="localhost",
            es_port=9200,
        )
        index_name = config.get_index_name()
        assert index_name == "mem_bge_m3_1024"


class TestMemorySearchContext:
    """Tests for MemorySearchContext model."""

    def test_create_empty_context(self):
        ctx = MemorySearchContext()
        assert ctx.tenant_long_term == []
        assert ctx.user_long_term == []
        assert ctx.agent_short_term == []
        assert ctx.external == []

    def test_context_with_results(self):
        result = MemorySearchResult(
            memory_id="mem-1",
            content="Found",
            score=0.9,
            layer=MemoryLayer.AGENT,
        )
        ctx = MemorySearchContext(
            tenant_long_term=[],
            user_long_term=[],
            agent_short_term=[result],
        )
        assert len(ctx.agent_short_term) == 1

    def test_to_prompt_text_empty(self):
        ctx = MemorySearchContext()
        text = ctx.to_prompt_text()
        assert text == ""

    def test_to_prompt_text_with_content(self):
        result = MemorySearchResult(
            memory_id="mem-1",
            content="Important fact",
            score=0.9,
            layer=MemoryLayer.AGENT,
        )
        ctx = MemorySearchContext(agent_short_term=[result])
        text = ctx.to_prompt_text()
        assert "### Memory Context" in text
        assert "Agent Short-term Memory" in text
        assert "Important fact" in text


class TestStoreMemoryResult:
    """Tests for StoreMemoryResult model."""

    def test_create_store_result(self):
        result = StoreMemoryResult(
            memory_id="mem-1",
            event="ADD",
            content="Stored content",
            layer=MemoryLayer.AGENT,
            memory_type=MemoryType.SHORT_TERM,
        )
        assert result.memory_id == "mem-1"
        assert result.event == "ADD"
        assert result.layer == MemoryLayer.AGENT
