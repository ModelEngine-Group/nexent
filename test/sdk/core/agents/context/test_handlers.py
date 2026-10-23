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


def test_history_turn_to_messages_includes_only_non_empty_parts():
    item = ContextItem(
        item_id="history-1",
        item_type=ContextItemType.HISTORY_TURN,
        content={"user_query": "What is the status?", "assistant_response": "It is ready."},
    )

    assert HistoryTurnHandler().to_messages(item) == [
        {"role": "user", "content": [{"type": "text", "text": "What is the status?"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "It is ready."}]},
    ]


@pytest.mark.parametrize(
    "content, expected",
    [
        (None, []),
        (
            {"user_query": "Only a question"},
            [{"role": "user", "content": [{"type": "text", "text": "Only a question"}]}],
        ),
        (
            {"assistant_response": "Only an answer"},
            [{"role": "assistant", "content": [{"type": "text", "text": "Only an answer"}]}],
        ),
    ],
)
def test_history_turn_to_messages_handles_missing_parts(content, expected):
    item = ContextItem(
        item_id="history-2",
        item_type=ContextItemType.HISTORY_TURN,
        content=content,
    )

    assert HistoryTurnHandler().to_messages(item) == expected


def test_tool_call_result_to_messages_formats_call_and_result():
    item = ContextItem(
        item_id="tool-result-1",
        item_type=ContextItemType.TOOL_CALL_RESULT,
        content={"tool_call": "search('Nexent')", "execution_result": "2 results"},
    )

    assert ToolCallResultHandler().to_messages(item) == [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "[Tool Call]\nsearch('Nexent')\n\n[Execution Result]\n2 results",
                }
            ],
        }
    ]


def test_tool_call_result_to_messages_uses_empty_values_for_missing_content():
    item = ContextItem(
        item_id="tool-result-2",
        item_type=ContextItemType.TOOL_CALL_RESULT,
        content=None,
    )

    message = ToolCallResultHandler().to_messages(item)
    assert message[0]["content"][0]["text"] == "[Tool Call]\n\n\n[Execution Result]\n"
