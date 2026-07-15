"""Tests for semantic handler reductions (KnowledgeBase, HistoryTurn, ToolCallResult)."""

import hashlib

import pytest

from nexent.core.agents.context.context_item import (
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
from nexent.core.agents.context.handlers import (
    HistoryTurnHandler,
    KnowledgeBaseHandler,
    ToolCallResultHandler,
)
from nexent.core.agents.context.handlers import register_all
from nexent.core.agents.context.item_handler_registry import ItemHandlerRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    ItemHandlerRegistry.reset()
    yield
    ItemHandlerRegistry.reset()


def _fp(content) -> str:
    return hashlib.sha256(str(content).encode()).hexdigest()[:16]


def _te(content) -> int:
    return len(str(content)) // 4


KB_CONTENT = {
    "kb_id": "kb-001",
    "title": "Python Best Practices",
    "content": "Python best practices include using type hints, writing docstrings, "
    "following PEP 8 style guidelines, and using virtual environments for dependency management.",
    "relevance_score": 0.95,
}

HISTORY_CONTENT = {
    "user_query": "How do I implement a binary search tree in Python?",
    "assistant_response": "You can implement a BST using a Node class with left and right children. "
    "Here is a basic implementation with insert and search methods.",
}

TOOL_CALL_CONTENT = {
    "tool_call": "search_web(query='Python BST implementation')",
    "execution_result": "Found 10 results. Top result: https://example.com/bst-guide - "
    "A comprehensive guide to implementing binary search trees in Python with examples.",
    "tool_name": "search_web",
    "status": "success",
}


class TestKnowledgeBaseHandlerReduction:

    def test_full_returns_original(self):
        handler = KnowledgeBaseHandler()
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=KB_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.content == KB_CONTENT
        assert result.representation == RepresentationTier.FULL
        assert result.admissible is True
        assert result.generator == "knowledge_base_handler"
        assert result.source_fingerprint == _fp(KB_CONTENT)

    def test_compressed_with_precomputed_summary(self):
        handler = KnowledgeBaseHandler()
        summary = "Python best practices: type hints, docstrings, PEP 8, virtual envs."
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=KB_CONTENT,
            metadata={"compressed_summary": summary},
        )
        result = handler.reduce(item, RepresentationTier.COMPRESSED, 1000)
        assert result.content == summary
        assert result.representation == RepresentationTier.COMPRESSED
        assert result.admissible is True
        assert result.generator == "knowledge_base_handler"
        assert result.token_count == _te(summary)

    def test_compressed_without_summary_deterministic_fallback(self):
        handler = KnowledgeBaseHandler()
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=KB_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.COMPRESSED, 1000)
        expected_text = KB_CONTENT["content"][:500]
        assert result.content == expected_text
        assert result.representation == RepresentationTier.COMPRESSED
        assert result.admissible is True
        assert result.generator == "knowledge_base_handler_deterministic"

    def test_compressed_truncates_long_content(self):
        handler = KnowledgeBaseHandler()
        long_content = {"kb_id": "kb-2", "title": "Long", "content": "A" * 1000, "relevance_score": 0.5}
        item = ContextItem(
            item_id="kb2",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=long_content,
        )
        result = handler.reduce(item, RepresentationTier.COMPRESSED, 1000)
        assert len(result.content) == 500

    def test_structured_keeps_kb_id_title_score(self):
        handler = KnowledgeBaseHandler()
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=KB_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["kb_id"] == "kb-001"
        assert result.content["title"] == "Python Best Practices"
        assert result.content["relevance_score"] == 0.95
        assert result.representation == RepresentationTier.STRUCTURED
        assert result.generator == "knowledge_base_handler_deterministic"

    def test_structured_with_string_content(self):
        handler = KnowledgeBaseHandler()
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content="plain text knowledge",
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["kb_id"] == ""
        assert result.content["title"] == "plain text knowledge"
        assert result.content["relevance_score"] == 0.0

    def test_pointer_rejected(self):
        handler = KnowledgeBaseHandler()
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=KB_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.admissible is False
        assert "pointer" in result.loss_metadata["reason"].lower()

    def test_fingerprint_stability(self):
        handler = KnowledgeBaseHandler()
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=KB_CONTENT,
        )
        r1 = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        r2 = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert r1.source_fingerprint == r2.source_fingerprint


class TestHistoryTurnHandlerReduction:

    def test_full_returns_original(self):
        handler = HistoryTurnHandler()
        item = ContextItem(
            item_id="h1",
            item_type=ContextItemType.HISTORY_TURN,
            content=HISTORY_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.content == HISTORY_CONTENT
        assert result.representation == RepresentationTier.FULL
        assert result.admissible is True
        assert result.generator == "history_turn_handler"
        assert result.source_fingerprint == _fp(HISTORY_CONTENT)

    def test_compressed_with_precomputed_summary(self):
        handler = HistoryTurnHandler()
        summary = "User asked about BST implementation; assistant provided Node class approach."
        item = ContextItem(
            item_id="h1",
            item_type=ContextItemType.HISTORY_TURN,
            content=HISTORY_CONTENT,
            metadata={"compressed_summary": summary},
        )
        result = handler.reduce(item, RepresentationTier.COMPRESSED, 1000)
        assert result.content == summary
        assert result.representation == RepresentationTier.COMPRESSED
        assert result.admissible is True
        assert result.generator == "history_turn_handler"

    def test_compressed_without_summary_deterministic_fallback(self):
        handler = HistoryTurnHandler()
        item = ContextItem(
            item_id="h1",
            item_type=ContextItemType.HISTORY_TURN,
            content=HISTORY_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.COMPRESSED, 1000)
        assert isinstance(result.content, dict)
        assert result.content["user_query"] == HISTORY_CONTENT["user_query"][:200]
        assert result.content["assistant_response"] == HISTORY_CONTENT["assistant_response"][:200]
        assert result.generator == "history_turn_handler_deterministic"

    def test_compressed_truncates_long_fields(self):
        handler = HistoryTurnHandler()
        long_content = {
            "user_query": "Q" * 500,
            "assistant_response": "A" * 500,
        }
        item = ContextItem(
            item_id="h2",
            item_type=ContextItemType.HISTORY_TURN,
            content=long_content,
        )
        result = handler.reduce(item, RepresentationTier.COMPRESSED, 1000)
        assert len(result.content["user_query"]) == 200
        assert len(result.content["assistant_response"]) == 200

    def test_structured_first_sentence_truncated(self):
        handler = HistoryTurnHandler()
        item = ContextItem(
            item_id="h1",
            item_type=ContextItemType.HISTORY_TURN,
            content=HISTORY_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert isinstance(result.content, dict)
        assert "user_query" in result.content
        assert "assistant_response" in result.content
        assert len(result.content["user_query"]) <= 100
        assert len(result.content["assistant_response"]) <= 100
        assert result.generator == "history_turn_handler_deterministic"

    def test_structured_first_sentence_splits_on_period(self):
        handler = HistoryTurnHandler()
        content = {
            "user_query": "First question. Second question.",
            "assistant_response": "First answer. Second answer.",
        }
        item = ContextItem(
            item_id="h3",
            item_type=ContextItemType.HISTORY_TURN,
            content=content,
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["user_query"] == "First question"
        assert result.content["assistant_response"] == "First answer"

    def test_pointer_rejected(self):
        handler = HistoryTurnHandler()
        item = ContextItem(
            item_id="h1",
            item_type=ContextItemType.HISTORY_TURN,
            content=HISTORY_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.admissible is False
        assert "pointer" in result.loss_metadata["reason"].lower()

    def test_to_messages_unchanged(self):
        handler = HistoryTurnHandler()
        item = ContextItem(
            item_id="h1",
            item_type=ContextItemType.HISTORY_TURN,
            content=HISTORY_CONTENT,
        )
        messages = handler.to_messages(item)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"


class TestToolCallResultHandlerReduction:

    def test_full_returns_original(self):
        handler = ToolCallResultHandler()
        item = ContextItem(
            item_id="tc1",
            item_type=ContextItemType.TOOL_CALL_RESULT,
            content=TOOL_CALL_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.content == TOOL_CALL_CONTENT
        assert result.representation == RepresentationTier.FULL
        assert result.admissible is True
        assert result.generator == "tool_call_result_handler_deterministic"
        assert result.source_fingerprint == _fp(TOOL_CALL_CONTENT)

    def test_structured_keeps_tool_name_truncated_result(self):
        handler = ToolCallResultHandler()
        item = ContextItem(
            item_id="tc1",
            item_type=ContextItemType.TOOL_CALL_RESULT,
            content=TOOL_CALL_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["tool_name"] == "search_web"
        assert len(result.content["execution_result"]) <= 200
        assert result.representation == RepresentationTier.STRUCTURED
        assert result.generator == "tool_call_result_handler_deterministic"

    def test_structured_truncates_long_result(self):
        handler = ToolCallResultHandler()
        long_content = {
            "tool_call": "call()",
            "execution_result": "R" * 500,
            "tool_name": "test_tool",
            "status": "success",
        }
        item = ContextItem(
            item_id="tc2",
            item_type=ContextItemType.TOOL_CALL_RESULT,
            content=long_content,
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert len(result.content["execution_result"]) == 200

    def test_pointer_keeps_tool_name_and_status(self):
        handler = ToolCallResultHandler()
        item = ContextItem(
            item_id="tc1",
            item_type=ContextItemType.TOOL_CALL_RESULT,
            content=TOOL_CALL_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.content["tool_name"] == "search_web"
        assert result.content["status"] == "success"
        assert "execution_result" not in result.content
        assert "tool_call" not in result.content
        assert result.representation == RepresentationTier.POINTER

    def test_pointer_with_string_content(self):
        handler = ToolCallResultHandler()
        item = ContextItem(
            item_id="tc3",
            item_type=ContextItemType.TOOL_CALL_RESULT,
            content="raw result string",
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.content["tool_name"] == ""
        assert result.content["status"] == ""

    def test_to_messages_unchanged(self):
        handler = ToolCallResultHandler()
        item = ContextItem(
            item_id="tc1",
            item_type=ContextItemType.TOOL_CALL_RESULT,
            content=TOOL_CALL_CONTENT,
        )
        messages = handler.to_messages(item)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "[Tool Call]" in messages[0]["content"][0]["text"]

    def test_fingerprint_stability(self):
        handler = ToolCallResultHandler()
        item = ContextItem(
            item_id="tc1",
            item_type=ContextItemType.TOOL_CALL_RESULT,
            content=TOOL_CALL_CONTENT,
        )
        r1 = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        r2 = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert r1.source_fingerprint == r2.source_fingerprint
        assert r1.content == r2.content


class TestSemanticReductionsViaRegistry:

    def test_reduce_item_kb_structured(self):
        register_all()
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=KB_CONTENT,
            minimum_fidelity=RepresentationTier.STRUCTURED,
        )
        result = ItemHandlerRegistry.reduce_item(
            item, RepresentationTier.STRUCTURED, 1000
        )
        assert result.admissible is True
        assert result.content["kb_id"] == "kb-001"

    def test_reduce_item_kb_pointer_rejected_by_minimum_fidelity(self):
        register_all()
        item = ContextItem(
            item_id="kb1",
            item_type=ContextItemType.KNOWLEDGE_BASE,
            content=KB_CONTENT,
            minimum_fidelity=RepresentationTier.COMPRESSED,
        )
        result = ItemHandlerRegistry.reduce_item(
            item, RepresentationTier.POINTER, 1000
        )
        assert result.admissible is False
        assert result.loss_metadata["reason"] == "minimum_fidelity_violation"

    def test_reduce_item_history_structured(self):
        register_all()
        item = ContextItem(
            item_id="h1",
            item_type=ContextItemType.HISTORY_TURN,
            content=HISTORY_CONTENT,
            minimum_fidelity=RepresentationTier.STRUCTURED,
        )
        result = ItemHandlerRegistry.reduce_item(
            item, RepresentationTier.STRUCTURED, 1000
        )
        assert result.admissible is True
        assert "user_query" in result.content

    def test_reduce_item_tool_call_pointer(self):
        register_all()
        item = ContextItem(
            item_id="tc1",
            item_type=ContextItemType.TOOL_CALL_RESULT,
            content=TOOL_CALL_CONTENT,
            minimum_fidelity=RepresentationTier.POINTER,
        )
        result = ItemHandlerRegistry.reduce_item(
            item, RepresentationTier.POINTER, 1000
        )
        assert result.admissible is True
        assert result.content["tool_name"] == "search_web"
        assert result.content["status"] == "success"


class TestTokenEstimatesSemanticHandlers:

    @pytest.mark.parametrize(
        "handler_cls,item_type,content",
        [
            (KnowledgeBaseHandler, ContextItemType.KNOWLEDGE_BASE, KB_CONTENT),
            (HistoryTurnHandler, ContextItemType.HISTORY_TURN, HISTORY_CONTENT),
            (ToolCallResultHandler, ContextItemType.TOOL_CALL_RESULT, TOOL_CALL_CONTENT),
        ],
        ids=["knowledge_base", "history_turn", "tool_call_result"],
    )
    def test_token_estimate_matches_content_length(self, handler_cls, item_type, content):
        handler = handler_cls()
        item = ContextItem(item_id="x", item_type=item_type, content=content)
        for tier in [RepresentationTier.FULL, RepresentationTier.STRUCTURED]:
            result = handler.reduce(item, tier, 1000)
            actual = _te(result.content)
            if actual == 0:
                assert result.token_count == 0
            else:
                assert abs(result.token_count - actual) <= max(1, actual * 0.2)


class TestDeterminismSemanticHandlers:

    @pytest.mark.parametrize(
        "handler_cls,item_type,content",
        [
            (KnowledgeBaseHandler, ContextItemType.KNOWLEDGE_BASE, KB_CONTENT),
            (HistoryTurnHandler, ContextItemType.HISTORY_TURN, HISTORY_CONTENT),
            (ToolCallResultHandler, ContextItemType.TOOL_CALL_RESULT, TOOL_CALL_CONTENT),
        ],
        ids=["knowledge_base", "history_turn", "tool_call_result"],
    )
    def test_deterministic_output(self, handler_cls, item_type, content):
        handler = handler_cls()
        item = ContextItem(item_id="x", item_type=item_type, content=content)
        for tier in [RepresentationTier.FULL, RepresentationTier.STRUCTURED]:
            r1 = handler.reduce(item, tier, 1000)
            r2 = handler.reduce(item, tier, 1000)
            assert r1.content == r2.content
            assert r1.source_fingerprint == r2.source_fingerprint
            assert r1.token_count == r2.token_count
            assert r1.generator == r2.generator
            assert r1.admissible == r2.admissible
