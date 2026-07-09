"""Tests for all context item handler implementations."""

import math

import pytest

from nexent.core.agents.context.context_item import (
    AuthorityTier,
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
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


ALL_HANDLERS = [
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

MANDATORY_HANDLERS = [SystemPromptHandler]

NON_MANDATORY_HANDLERS = [
    ToolHandler,
    SkillHandler,
    MemoryHandler,
    KnowledgeBaseHandler,
    ManagedAgentHandler,
    ExternalAgentHandler,
    HistoryTurnHandler,
    ToolCallResultHandler,
]


def _make_item(handler_cls):
    """Create a ContextItem matching the handler's first supported type."""
    handler = handler_cls()
    item_type = handler.supported_types()[0]
    return ContextItem(
        item_id=f"test-{item_type.value}",
        item_type=item_type,
        content=f"content for {item_type.value}",
        token_estimate=100,
    )


class TestHandlerSupportedTypes:
    """Tests for handler supported_types() method."""

    @pytest.mark.parametrize("handler_cls", ALL_HANDLERS, ids=lambda h: h.__name__)
    def test_handler_supported_types(self, handler_cls):
        handler = handler_cls()
        types = handler.supported_types()
        assert len(types) > 0
        for t in types:
            assert isinstance(t, ContextItemType)


class TestHandlerScore:
    """Tests for handler score() method."""

    @pytest.mark.parametrize("handler_cls", ALL_HANDLERS, ids=lambda h: h.__name__)
    def test_handler_score_returns_float(self, handler_cls):
        handler = handler_cls()
        item = _make_item(handler_cls)
        result = handler.score(item, "test query", {})
        assert isinstance(result, float)

    @pytest.mark.parametrize("handler_cls", MANDATORY_HANDLERS, ids=lambda h: h.__name__)
    def test_mandatory_handlers_return_inf_score(self, handler_cls):
        handler = handler_cls()
        item = _make_item(handler_cls)
        result = handler.score(item, "test query", {})
        assert math.isinf(result)

    @pytest.mark.parametrize("handler_cls", NON_MANDATORY_HANDLERS, ids=lambda h: h.__name__)
    def test_non_mandatory_handlers_return_1_0_score(self, handler_cls):
        handler = handler_cls()
        item = _make_item(handler_cls)
        result = handler.score(item, "test query", {})
        assert result == pytest.approx(1.0, rel=1e-9)


class TestHandlerReduce:
    """Tests for handler reduce() method."""

    @pytest.mark.parametrize("handler_cls", ALL_HANDLERS, ids=lambda h: h.__name__)
    def test_handler_reduce_returns_reduction_result(self, handler_cls):
        handler = handler_cls()
        item = _make_item(handler_cls)
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert isinstance(result, ReductionResult)

    @pytest.mark.parametrize("handler_cls", ALL_HANDLERS, ids=lambda h: h.__name__)
    def test_handler_reduce_passthrough_preserves_content(self, handler_cls):
        handler = handler_cls()
        item = _make_item(handler_cls)
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.content == item.content
        assert result.admissible is True


class TestHandlerCoverage:
    """Tests for handler type coverage and disjointness."""

    def test_all_handler_supported_types_are_disjoint(self):
        seen_types = set()
        for handler_cls in ALL_HANDLERS:
            handler = handler_cls()
            for t in handler.supported_types():
                assert t not in seen_types, (
                    f"{handler_cls.__name__} duplicates type {t.name}"
                )
                seen_types.add(t)

    def test_all_context_item_types_covered_by_handlers(self):
        covered = set()
        for handler_cls in ALL_HANDLERS:
            handler = handler_cls()
            covered.update(handler.supported_types())

        assert covered == set(ContextItemType)
