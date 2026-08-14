"""Tests for ItemHandlerRegistry."""

import pytest

from nexent.core.agents.context.context_item import (
    AuthorityTier,
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
from nexent.core.agents.context.item_handler import ContextItemHandler
from nexent.core.agents.context.item_handler_registry import ItemHandlerRegistry
from nexent.core.agents.context.reducer_models import ReductionResult

from nexent.core.agents.context.handlers import (
    ExternalAgentHandler,
    HistoryTurnHandler,
    KnowledgeBaseHandler,
    ManagedAgentHandler,
    MemoryHandler,
    SkillHandler,
    SystemPromptHandler,
    ToolCallResultHandler,
    ToolHandler,
)


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the shared class-level registry before each test."""
    ItemHandlerRegistry.reset()
    yield
    ItemHandlerRegistry.reset()


class _StubHandler(ContextItemHandler):
    """Minimal handler for testing registry operations."""

    def __init__(self, types):
        self._types = types

    def supported_types(self):
        return self._types


class TestItemHandlerRegistry:
    """Tests for ItemHandlerRegistry class methods."""

    def test_register_and_get_handler(self):
        handler = _StubHandler([ContextItemType.TOOL])
        ItemHandlerRegistry.register(handler)

        retrieved = ItemHandlerRegistry.get(ContextItemType.TOOL)
        assert retrieved is handler

    def test_get_unregistered_type_raises_key_error(self):
        with pytest.raises(KeyError, match="No handler registered"):
            ItemHandlerRegistry.get(ContextItemType.SKILL)

    def test_all_types_covered_returns_false_when_empty(self):
        assert ItemHandlerRegistry.all_types_covered() is False

    def test_all_types_covered_returns_true_when_complete(self):
        all_handler_classes = [
            SystemPromptHandler,
            ToolHandler,
            SkillHandler,
            MemoryHandler,
            KnowledgeBaseHandler,
            ManagedAgentHandler,
            ExternalAgentHandler,
            HistoryTurnHandler,
            ToolCallResultHandler,
        ]
        for handler_cls in all_handler_classes:
            ItemHandlerRegistry.register(handler_cls())

        assert ItemHandlerRegistry.all_types_covered() is True

    def test_reset_clears_handlers(self):
        handler = _StubHandler([ContextItemType.TOOL])
        ItemHandlerRegistry.register(handler)
        assert ItemHandlerRegistry.get(ContextItemType.TOOL) is handler

        ItemHandlerRegistry.reset()

        with pytest.raises(KeyError):
            ItemHandlerRegistry.get(ContextItemType.TOOL)

    def test_register_all_handlers_covers_all_types(self):
        """Register all built-in handlers and verify complete coverage."""
        all_handler_classes = [
            SystemPromptHandler,
            ToolHandler,
            SkillHandler,
            MemoryHandler,
            KnowledgeBaseHandler,
            ManagedAgentHandler,
            ExternalAgentHandler,
            HistoryTurnHandler,
            ToolCallResultHandler,
        ]
        for handler_cls in all_handler_classes:
            ItemHandlerRegistry.register(handler_cls())

        assert ItemHandlerRegistry.all_types_covered() is True

        assert isinstance(ItemHandlerRegistry.get(ContextItemType.SYSTEM_PROMPT), SystemPromptHandler)
        assert isinstance(ItemHandlerRegistry.get(ContextItemType.TOOL), ToolHandler)

    def test_base_handler_score_and_reduce_are_passthroughs(self):
        handler = _StubHandler([ContextItemType.TOOL])
        item = ContextItem(
            item_id="item-1",
            item_type=ContextItemType.TOOL,
            content={"value": 1},
            token_estimate=7,
            current_representation=RepresentationTier.STRUCTURED,
        )

        assert handler.score(item, "query", {}) == 1.0
        result = handler.reduce(item, RepresentationTier.POINTER, budget=3)
        assert result.representation == RepresentationTier.STRUCTURED
        assert result.token_count == 7
        assert result.generator == "passthrough"
        assert result.generator_version == "0.1.0"
        assert result.admissible is True
        assert result.loss_metadata == {}
        assert result.content == {"value": 1}

    @pytest.mark.parametrize(
        "content, expected_text",
        [("plain text", "plain text"), ({"value": 1}, "{'value': 1}")],
    )
    def test_base_handler_to_messages_stringifies_non_string_content(self, content, expected_text):
        handler = _StubHandler([ContextItemType.TOOL])
        item = ContextItem(
            item_id="item-2",
            item_type=ContextItemType.TOOL,
            content=content,
        )

        assert handler.to_messages(item) == [
            {"role": "user", "content": [{"type": "text", "text": expected_text}]}
        ]
