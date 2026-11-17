# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit tests for ``management.services.memory.extraction``.

TDD tests written BEFORE the implementation exists.  Covers:

- ``_parse_items`` static parser (AC-004, AC-005, AC-006)
- ``_load_prompt`` YAML loading
- ``_build_messages`` message construction
- ``_store_items`` per-item storage with partial-failure resilience (AC-008)
- ``extract_and_store`` full pipeline (AC-003, AC-007, AC-012)
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from management.services.memory.extraction import (
    ExtractionResult,
    FaMemoryExtractor,
)
from nexent.memory.models import MemoryLayer, MemoryType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = "tenant-1"
USER_ID = "user-1"
AGENT_ID = "agent-1"
CONVERSATION_ID = "conversation-1"


def _make_extractor(
    *,
    memory_service: MagicMock | None = None,
    model_client: MagicMock | None = None,
    language: str = "en",
) -> FaMemoryExtractor:
    """Build a FaMemoryExtractor with sensible defaults for testing."""
    return FaMemoryExtractor(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        agent_id=AGENT_ID,
        conversation_id=CONVERSATION_ID,
        language=language,
        memory_service=memory_service,
        model_client=model_client,
    )


def _mock_memory_service() -> MagicMock:
    """Return a MagicMock pre-configured as an async MemoryService."""
    service = MagicMock()
    service.store_memory = AsyncMock(
        return_value=MagicMock(memory_id="mem-1", event="ADD"),
    )
    return service


def _mock_model_client(response_text: str) -> MagicMock:
    """Return a MagicMock whose async ``chat`` method returns *response_text*."""
    client = MagicMock()
    client.chat = AsyncMock(return_value=response_text)
    return client


# ===================================================================
# Parser tests  (AC-004, AC-005, AC-006)
# ===================================================================


def _grounded(evidence, category="user_fact", source="user", scope="durable"):
    return json.dumps({"items": [{"category": category, "source": source,
                                 "scope": scope, "evidence": evidence}]})


class TestParseItems:
    """The internal extractor protocol requires source and scope evidence."""

    def test_grounded_preference(self):
        query = "I always prefer Python."
        assert FaMemoryExtractor._parse_items(
            _grounded(query, "user_preference"), query, "Python is suitable."
        ) == [query]

    @pytest.mark.parametrize("raw", ["", "not JSON", "<no-memory/>",
                                    "<memory-item>User prefers Python</memory-item>",
                                    "[]", '{"items": []}', '{"items": "invalid"}'])
    def test_untyped_or_empty_output_cannot_write(self, raw):
        assert FaMemoryExtractor._parse_items(raw, "I prefer Python.", "Answer") == []

    def test_missing_source_does_not_invent_preference(self):
        assert FaMemoryExtractor._parse_items(
            _grounded("I prefer Python.", "user_preference"), "", "I prefer Python."
        ) == []


# ===================================================================
# Prompt loading tests
# ===================================================================


class TestPromptLoading:
    """Tests for ``_load_prompt`` and ``_build_messages``."""

    def test_load_prompt_returns_dict(self):
        extractor = _make_extractor()
        prompt = extractor._load_prompt()
        assert isinstance(prompt, dict)
        assert "system" in prompt
        assert "user" in prompt

    def test_load_prompt_system_contains_extraction_rules(self):
        extractor = _make_extractor()
        prompt = extractor._load_prompt()
        assert "memory" in prompt["system"].lower()

    def test_build_messages_structure(self):
        extractor = _make_extractor()
        messages = extractor._build_messages(
            final_answer="The answer is 42.",
            user_query="What is the meaning of life?",
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert isinstance(messages[0]["content"], str)
        assert len(messages[0]["content"]) > 0
        assert messages[1]["role"] == "user"
        assert "The answer is 42." in messages[1]["content"]
        assert "What is the meaning of life?" in messages[1]["content"]

    def test_build_messages_user_query_defaults_empty(self):
        extractor = _make_extractor()
        messages = extractor._build_messages(final_answer="Some answer.")
        assert messages[1]["role"] == "user"
        assert "Some answer." in messages[1]["content"]


# ===================================================================
# Store items tests  (AC-008)
# ===================================================================


class TestStoreItems:
    """Tests for ``_store_items`` async storage with per-item error handling."""

    @pytest.mark.asyncio
    async def test_store_items_success(self):
        service = _mock_memory_service()
        service.store_memory.side_effect = [
            MagicMock(memory_id="mem-1", event="ADD"),
            MagicMock(memory_id="mem-2", event="ADD"),
        ]
        extractor = _make_extractor(memory_service=service)

        results = await extractor._store_items(["Item A", "Item B"])

        assert len(results) == 2
        assert results[0]["content"] == "Item A"
        assert results[0]["memory_id"] == "mem-1"
        assert results[1]["content"] == "Item B"
        assert results[1]["memory_id"] == "mem-2"

        assert service.store_memory.call_count == 2
        for call in service.store_memory.call_args_list:
            kwargs = call.kwargs
            assert kwargs["tenant_id"] == TENANT_ID
            assert kwargs["user_id"] == USER_ID
            assert kwargs["agent_id"] == AGENT_ID
            assert kwargs["conversation_id"] == CONVERSATION_ID
            assert kwargs["layer"] == MemoryLayer.AGENT
            assert kwargs["memory_type"] == MemoryType.SHORT_TERM

    @pytest.mark.asyncio
    async def test_store_items_partial_failure(self, caplog):
        caplog.set_level(logging.WARNING)
        service = _mock_memory_service()
        service.store_memory.side_effect = [
            MagicMock(memory_id="mem-1", event="ADD"),
            RuntimeError("backend unavailable"),
            MagicMock(memory_id="mem-3", event="ADD"),
        ]
        extractor = _make_extractor(memory_service=service)

        results = await extractor._store_items(["Item A", "Item B", "Item C"])

        assert len(results) == 2
        assert results[0]["content"] == "Item A"
        assert results[1]["content"] == "Item C"
        assert service.store_memory.call_count == 3

    @pytest.mark.asyncio
    async def test_store_items_all_fail(self, caplog):
        caplog.set_level(logging.WARNING)
        service = _mock_memory_service()
        service.store_memory.side_effect = RuntimeError("total failure")
        extractor = _make_extractor(memory_service=service)

        results = await extractor._store_items(["Item A", "Item B"])

        assert results == []
        assert service.store_memory.call_count == 2


# ===================================================================
# Full pipeline tests  (AC-003, AC-007, AC-012)
# ===================================================================


class TestExtractAndStore:
    """Tests for ``extract_and_store`` end-to-end pipeline."""

    @pytest.mark.asyncio
    async def test_extract_and_store_happy_path(self):
        llm_response = json.dumps({"items": [
            {"category": "user_preference", "source": "user", "scope": "durable",
             "evidence": "I prefer Python."},
            {"category": "user_fact", "source": "user", "scope": "durable",
             "evidence": "I use VS Code."},
        ]})
        model_client = _mock_model_client(llm_response)
        service = _mock_memory_service()
        service.store_memory.side_effect = [
            MagicMock(memory_id="mem-1", event="ADD"),
            MagicMock(memory_id="mem-2", event="ADD"),
        ]
        extractor = _make_extractor(
            memory_service=service,
            model_client=model_client,
        )

        result = await extractor.extract_and_store(
            "Python is great for backend development and VS Code is a solid IDE.",
            user_query="I prefer Python. I use VS Code."
        )

        assert isinstance(result, ExtractionResult)
        assert result.reason == "ok"
        assert len(result.items) == 2
        assert result.items[0]["content"] == "I prefer Python."
        assert result.items[1]["content"] == "I use VS Code."
        model_client.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_and_store_includes_user_query_in_prompt(self):
        model_client = _mock_model_client("<no-memory/>")
        extractor = _make_extractor(
            memory_service=_mock_memory_service(),
            model_client=model_client,
        )

        await extractor.extract_and_store(
            "Use the develop branch.",
            user_query="Which branch should this change target?",
        )

        messages = model_client.chat.await_args.args[0]
        assert "Which branch should this change target?" in messages[1]["content"]

    @pytest.mark.asyncio
    async def test_extract_and_store_empty_answer(self):
        extractor = _make_extractor(
            memory_service=_mock_memory_service(),
            model_client=_mock_model_client("should not be called"),
        )

        result = await extractor.extract_and_store("")

        assert result.reason == "empty_final_answer"
        assert result.items == []

    @pytest.mark.asyncio
    async def test_extract_and_store_whitespace_only_answer(self):
        extractor = _make_extractor(
            memory_service=_mock_memory_service(),
            model_client=_mock_model_client("should not be called"),
        )

        result = await extractor.extract_and_store("   \n\t  ")

        assert result.reason == "empty_final_answer"
        assert result.items == []

    @pytest.mark.asyncio
    async def test_extract_and_store_no_llm_configured(self):
        extractor = _make_extractor(
            memory_service=_mock_memory_service(),
            model_client=None,
        )

        result = await extractor.extract_and_store("Some valid answer.")

        assert result.reason == "no_llm_configured"
        assert result.items == []

    @pytest.mark.asyncio
    async def test_extract_and_store_llm_timeout(self, caplog):
        caplog.set_level(logging.ERROR)
        client = MagicMock()
        client.chat = AsyncMock(side_effect=TimeoutError("LLM timed out"))
        extractor = _make_extractor(
            memory_service=_mock_memory_service(),
            model_client=client,
        )

        result = await extractor.extract_and_store("Some answer text.")

        assert result.reason == "llm_error"
        assert result.items == []

    @pytest.mark.asyncio
    async def test_extract_and_store_llm_generic_error(self, caplog):
        caplog.set_level(logging.ERROR)
        client = MagicMock()
        client.chat = AsyncMock(side_effect=RuntimeError("model exploded"))
        extractor = _make_extractor(
            memory_service=_mock_memory_service(),
            model_client=client,
        )

        result = await extractor.extract_and_store("Some answer text.")

        assert result.reason == "llm_error"
        assert result.items == []

    @pytest.mark.asyncio
    async def test_extract_and_store_no_items(self):
        model_client = _mock_model_client("<no-memory/>")
        service = _mock_memory_service()
        extractor = _make_extractor(
            memory_service=service,
            model_client=model_client,
        )

        result = await extractor.extract_and_store(
            "Hello! How can I help you today?"
        )

        assert result.reason == "no_items"
        assert result.items == []
        service.store_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_and_store_truncation(self):
        long_answer = "A" * (FaMemoryExtractor.MAX_INPUT_CHARS + 5000)
        captured_args = {}

        async def capture_chat(messages, **kwargs):
            captured_args["messages"] = messages
            return "<no-memory/>"

        client = MagicMock()
        client.chat = AsyncMock(side_effect=capture_chat)
        extractor = _make_extractor(
            memory_service=_mock_memory_service(),
            model_client=client,
        )

        result = await extractor.extract_and_store(long_answer)

        user_msg = captured_args["messages"][1]["content"]
        assert len(user_msg) < len(long_answer)
        assert result.reason == "no_items"

    @pytest.mark.asyncio
    async def test_extract_and_store_truncation_respects_max_chars(self):
        """Verify the final_answer portion does not exceed MAX_INPUT_CHARS."""
        long_answer = "X" * (FaMemoryExtractor.MAX_INPUT_CHARS * 2)
        captured_args = {}

        async def capture_chat(messages, **kwargs):
            captured_args["messages"] = messages
            return "<no-memory/>"

        client = MagicMock()
        client.chat = AsyncMock(side_effect=capture_chat)
        extractor = _make_extractor(
            memory_service=_mock_memory_service(),
            model_client=client,
        )

        await extractor.extract_and_store(long_answer)

        user_msg = captured_args["messages"][1]["content"]
        assert len(user_msg) < len(long_answer)

    @pytest.mark.asyncio
    async def test_extract_and_store_passes_conversation_id(self):
        """Ensure conversation_id flows through to store_memory calls."""
        llm_response = _grounded("I use PostgreSQL.")
        model_client = _mock_model_client(llm_response)
        service = _mock_memory_service()
        service.store_memory.return_value = MagicMock(
            memory_id="mem-1", event="ADD"
        )
        extractor = _make_extractor(
            memory_service=service,
            model_client=model_client,
        )

        await extractor.extract_and_store("Some answer.", user_query="I use PostgreSQL.")

        call_kwargs = service.store_memory.call_args.kwargs
        assert call_kwargs["conversation_id"] == CONVERSATION_ID

    @pytest.mark.asyncio
    async def test_extract_and_store_uses_agent_layer_and_short_term(self):
        """Verify layer=AGENT and memory_type=SHORT_TERM on store calls."""
        llm_response = _grounded("I use PostgreSQL.")
        model_client = _mock_model_client(llm_response)
        service = _mock_memory_service()
        service.store_memory.return_value = MagicMock(
            memory_id="mem-1", event="ADD"
        )
        extractor = _make_extractor(
            memory_service=service,
            model_client=model_client,
        )

        await extractor.extract_and_store("Some answer.", user_query="I use PostgreSQL.")

        call_kwargs = service.store_memory.call_args.kwargs
        assert call_kwargs["layer"] == MemoryLayer.AGENT
        assert call_kwargs["memory_type"] == MemoryType.SHORT_TERM


# ===================================================================
# ExtractionResult dataclass tests
# ===================================================================


class TestExtractionResult:
    """Tests for the ExtractionResult dataclass."""

    def test_extraction_result_fields(self):
        result = ExtractionResult(
            items=[{"content": "test", "memory_id": "m1", "event": "ADD"}],
            reason="ok",
        )
        assert result.items == [
            {"content": "test", "memory_id": "m1", "event": "ADD"}
        ]
        assert result.reason == "ok"

    def test_extraction_result_empty(self):
        result = ExtractionResult(items=[], reason="no_items")
        assert result.items == []
        assert result.reason == "no_items"
