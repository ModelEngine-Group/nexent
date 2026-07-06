"""Unit tests for HistoryProjector.

Verifies that HistoryProjector correctly projects conversation history
units into ContextItem instances for model_context, resume, and chat purposes.
"""

import pytest
from unittest.mock import MagicMock, patch

from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.agent_model import (
    MemoryComponent,
    SystemPromptComponent,
)
from nexent.core.agents.context.history_projector import HistoryProjector
from nexent.core.agents.context.context_item import (
    AuthorityTier,
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
from nexent.core.agents.context.handlers import register_all
from nexent.core.agents.summary_config import ContextManagerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_unit(
    unit_id=1,
    unit_type="user_input",
    unit_content="hello",
    run_id=1,
    step_id=1,
    tool_call_id=None,
):
    """Build a minimal unit dict matching the database row shape."""
    return {
        "unit_id": unit_id,
        "unit_type": unit_type,
        "unit_content": unit_content,
        "run_id": run_id,
        "step_id": step_id,
        "tool_call_id": tool_call_id,
    }


def make_query_fn(units):
    """Return a query_units_fn closure over a fixed list of units."""
    def query_fn(conversation_id, run_id=None):
        if run_id is not None:
            return [u for u in units if u.get("run_id") == run_id]
        return units
    return query_fn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def ensure_handlers():
    """Register all item handlers so ItemHandlerRegistry.get() succeeds."""
    register_all()


# ===================================================================
# 1. Basic Projection Tests
# ===================================================================

class TestBasicProjection:
    """Tests for core model_context projection behavior."""

    def test_project_model_context_empty_units(self):
        """Empty units list returns empty items."""
        projector = HistoryProjector(make_query_fn([]))
        items = projector.project(conversation_id=1, purpose="model_context")
        assert items == []

    def test_project_model_context_single_turn(self):
        """Single user_input + final_answer produces one HISTORY_TURN."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="What is AI?", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="AI is artificial intelligence.", run_id=1, step_id=1),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        assert len(items) == 1
        assert items[0].item_type == ContextItemType.HISTORY_TURN
        assert items[0].content["user_query"] == "What is AI?"
        assert items[0].content["assistant_response"] == "AI is artificial intelligence."

    def test_project_model_context_multiple_turns(self):
        """Multiple runs/steps produce multiple HISTORY_TURNs."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="Q1", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="A1", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="user_input", unit_content="Q2", run_id=1, step_id=2),
            make_unit(unit_id=4, unit_type="final_answer", unit_content="A2", run_id=1, step_id=2),
            make_unit(unit_id=5, unit_type="user_input", unit_content="Q3", run_id=2, step_id=1),
            make_unit(unit_id=6, unit_type="final_answer", unit_content="A3", run_id=2, step_id=1),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        history_turns = [i for i in items if i.item_type == ContextItemType.HISTORY_TURN]
        assert len(history_turns) == 3

    def test_project_model_context_excludes_thinking(self):
        """model_output_thinking and model_output_deep_thinking are NOT included in HISTORY_TURN."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="Think hard", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="model_output_thinking", unit_content="internal thought", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="model_output_deep_thinking", unit_content="deep thought", run_id=1, step_id=1),
            make_unit(unit_id=4, unit_type="final_answer", unit_content="The answer.", run_id=1, step_id=1),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        assert len(items) == 1
        turn = items[0]
        assert turn.item_type == ContextItemType.HISTORY_TURN
        # Content only has user_query and assistant_response, no thinking
        assert "internal thought" not in str(turn.content)
        assert "deep thought" not in str(turn.content)
        assert turn.content["user_query"] == "Think hard"
        assert turn.content["assistant_response"] == "The answer."

    def test_project_invalid_purpose(self):
        """Unknown purpose raises ValueError."""
        projector = HistoryProjector(make_query_fn([]))
        with pytest.raises(ValueError, match="Unknown purpose"):
            projector.project(conversation_id=1, purpose="invalid_purpose")


# ===================================================================
# 2. Tool Call Result Tests
# ===================================================================

class TestToolCallResult:
    """Tests for tool/execution_logs pairing into TOOL_CALL_RESULT items."""

    def test_tool_call_result_pairing(self):
        """tool + execution_logs with same tool_call_id produces TOOL_CALL_RESULT."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="search", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="done", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="tool", unit_content="web_search('AI')", run_id=1, step_id=1, tool_call_id="tc-1"),
            make_unit(unit_id=4, unit_type="execution_logs", unit_content="result: found AI", run_id=1, step_id=1, tool_call_id="tc-1"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        tool_results = [i for i in items if i.item_type == ContextItemType.TOOL_CALL_RESULT]
        assert len(tool_results) == 1
        assert tool_results[0].content["tool_call"] == "web_search('AI')"
        assert tool_results[0].content["execution_result"] == "result: found AI"

    def test_tool_call_result_multiple_pairs(self):
        """Multiple tool/execution_logs pairs produce multiple TOOL_CALL_RESULTs."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="multi", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="done", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="tool", unit_content="tool_a()", run_id=1, step_id=1, tool_call_id="tc-a"),
            make_unit(unit_id=4, unit_type="execution_logs", unit_content="result_a", run_id=1, step_id=1, tool_call_id="tc-a"),
            make_unit(unit_id=5, unit_type="tool", unit_content="tool_b()", run_id=1, step_id=1, tool_call_id="tc-b"),
            make_unit(unit_id=6, unit_type="execution_logs", unit_content="result_b", run_id=1, step_id=1, tool_call_id="tc-b"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        tool_results = [i for i in items if i.item_type == ContextItemType.TOOL_CALL_RESULT]
        assert len(tool_results) == 2
        tool_call_ids = {i.metadata["tool_call_id"] for i in tool_results}
        assert tool_call_ids == {"tc-a", "tc-b"}

    def test_tool_call_result_unpaired_tool(self):
        """tool without execution_logs does NOT produce TOOL_CALL_RESULT."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="q", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="a", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="tool", unit_content="orphan_tool()", run_id=1, step_id=1, tool_call_id="tc-orphan"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        tool_results = [i for i in items if i.item_type == ContextItemType.TOOL_CALL_RESULT]
        assert len(tool_results) == 0

    def test_tool_call_result_unpaired_logs(self):
        """execution_logs without tool does NOT produce TOOL_CALL_RESULT."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="q", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="a", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="execution_logs", unit_content="orphan logs", run_id=1, step_id=1, tool_call_id="tc-orphan"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        tool_results = [i for i in items if i.item_type == ContextItemType.TOOL_CALL_RESULT]
        assert len(tool_results) == 0

    def test_tool_call_result_different_ids(self):
        """tool and execution_logs with different tool_call_ids do NOT pair."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="q", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="a", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="tool", unit_content="tool_x()", run_id=1, step_id=1, tool_call_id="tc-x"),
            make_unit(unit_id=4, unit_type="execution_logs", unit_content="logs_y", run_id=1, step_id=1, tool_call_id="tc-y"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        tool_results = [i for i in items if i.item_type == ContextItemType.TOOL_CALL_RESULT]
        assert len(tool_results) == 0


# ===================================================================
# 3. Resume Context Tests
# ===================================================================

class TestResumeContext:
    """Tests for resume purpose producing WORKING_MEMORY items."""

    def test_resume_context_active_goal(self):
        """Last user_input produces WORKING_MEMORY with active_goal."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="first query", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="first answer", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="user_input", unit_content="latest goal", run_id=2, step_id=1),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="resume")

        goal_items = [i for i in items if i.content.get("type") == "active_goal"]
        assert len(goal_items) == 1
        assert goal_items[0].item_type == ContextItemType.WORKING_MEMORY
        assert goal_items[0].content["text"] == "latest goal"
        assert goal_items[0].authority_tier == AuthorityTier.USER

    def test_resume_context_incomplete_tools(self):
        """Tool without execution_logs produces WORKING_MEMORY with pending_tool_call."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="do something", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="tool", unit_content="pending_tool()", run_id=1, step_id=1, tool_call_id="tc-pending"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="resume")

        pending_items = [i for i in items if i.content.get("type") == "pending_tool_call"]
        assert len(pending_items) == 1
        assert pending_items[0].item_type == ContextItemType.WORKING_MEMORY
        assert pending_items[0].content["tool_call_id"] == "tc-pending"
        assert pending_items[0].content["tool_content"] == "pending_tool()"
        assert pending_items[0].authority_tier == AuthorityTier.TOOL_RESULT

    def test_resume_context_empty_units(self):
        """Empty units returns empty items."""
        projector = HistoryProjector(make_query_fn([]))
        items = projector.project(conversation_id=1, purpose="resume")
        assert items == []

    def test_resume_context_no_user_input(self):
        """No user_input in last step returns no active_goal."""
        units = [
            make_unit(unit_id=1, unit_type="tool", unit_content="some_tool()", run_id=1, step_id=1, tool_call_id="tc-1"),
            make_unit(unit_id=2, unit_type="execution_logs", unit_content="logs", run_id=1, step_id=1, tool_call_id="tc-1"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="resume")

        goal_items = [i for i in items if i.content.get("type") == "active_goal"]
        assert len(goal_items) == 0


# ===================================================================
# 4. Chat Context Tests
# ===================================================================

class TestChatContext:
    """Tests for chat purpose which includes thinking units."""

    def test_chat_context_includes_thinking(self):
        """Chat context includes model_output_thinking units."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="Explain", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="model_output_thinking", unit_content="Let me think...", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="final_answer", unit_content="The answer is X.", run_id=1, step_id=1),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="chat")

        assert len(items) == 1
        turn = items[0]
        assert turn.item_type == ContextItemType.HISTORY_TURN
        # Chat turn includes all relevant units as a list
        unit_types = [u["type"] for u in turn.content["units"]]
        assert "user_input" in unit_types
        assert "model_output_thinking" in unit_types
        assert "final_answer" in unit_types
        assert turn.metadata.get("includes_thinking") is True

    def test_chat_context_empty_units(self):
        """Empty units returns empty items."""
        projector = HistoryProjector(make_query_fn([]))
        items = projector.project(conversation_id=1, purpose="chat")
        assert items == []


# ===================================================================
# 5. Grouping Tests
# ===================================================================

class TestGrouping:
    """Tests for _group_by_run handling of None/falsy IDs."""

    def test_group_by_run_handles_none_run_id(self):
        """Units with None run_id are grouped under run_id=0."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="q", run_id=None, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="a", run_id=None, step_id=1),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        assert len(items) == 1
        assert items[0].item_id == "history_turn:0:1"
        assert items[0].metadata["run_id"] == 0

    def test_group_by_run_handles_none_step_id(self):
        """Units with None step_id are grouped under step_id=0."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="q", run_id=1, step_id=None),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="a", run_id=1, step_id=None),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        assert len(items) == 1
        assert items[0].item_id == "history_turn:1:0"
        assert items[0].metadata["step_id"] == 0


# ===================================================================
# 6. Item Validation Tests
# ===================================================================

class TestItemValidation:
    """Verify field-level correctness of produced ContextItems."""

    def test_history_turn_item_fields(self):
        """Verify item_id format, item_type, source_refs, authority_tier, content structure."""
        units = [
            make_unit(unit_id=10, unit_type="user_input", unit_content="query text", run_id=3, step_id=2),
            make_unit(unit_id=20, unit_type="final_answer", unit_content="answer text", run_id=3, step_id=2),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        assert len(items) == 1
        item = items[0]

        assert item.item_id == "history_turn:3:2"
        assert item.item_type == ContextItemType.HISTORY_TURN
        assert item.source_refs == ["unit:10", "unit:20"]
        assert item.authority_tier == AuthorityTier.AGENT_INFERENCE
        assert item.minimum_fidelity == RepresentationTier.STRUCTURED
        assert item.current_representation == RepresentationTier.FULL
        assert item.content == {
            "user_query": "query text",
            "assistant_response": "answer text",
        }
        assert item.token_estimate == (len("query text") + len("answer text")) // 4
        assert item.metadata == {"run_id": 3, "step_id": 2}

    def test_tool_call_result_item_fields(self):
        """Verify item_id format, item_type, source_refs, authority_tier, content structure."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="q", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="a", run_id=1, step_id=1),
            make_unit(unit_id=5, unit_type="tool", unit_content="search('x')", run_id=1, step_id=1, tool_call_id="tc-42"),
            make_unit(unit_id=6, unit_type="execution_logs", unit_content="found: x", run_id=1, step_id=1, tool_call_id="tc-42"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="model_context")

        tool_items = [i for i in items if i.item_type == ContextItemType.TOOL_CALL_RESULT]
        assert len(tool_items) == 1
        item = tool_items[0]

        assert item.item_id == "tool_call_result:tc-42"
        assert item.item_type == ContextItemType.TOOL_CALL_RESULT
        assert item.source_refs == ["unit:5", "unit:6"]
        assert item.authority_tier == AuthorityTier.TOOL_RESULT
        assert item.minimum_fidelity == RepresentationTier.STRUCTURED
        assert item.current_representation == RepresentationTier.FULL
        assert item.content == {
            "tool_call": "search('x')",
            "execution_result": "found: x",
        }
        assert item.token_estimate == (len("search('x')") + len("found: x")) // 4
        assert item.metadata == {
            "tool_call_id": "tc-42",
            "run_id": 1,
            "step_id": 1,
        }

    def test_working_memory_item_fields(self):
        """Verify item_id format, item_type, source_refs, authority_tier, content structure."""
        units = [
            make_unit(unit_id=7, unit_type="user_input", unit_content="my goal", run_id=5, step_id=3),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="resume")

        goal_items = [i for i in items if i.content.get("type") == "active_goal"]
        assert len(goal_items) == 1
        item = goal_items[0]

        assert item.item_id == "working_memory:goal:5:3"
        assert item.item_type == ContextItemType.WORKING_MEMORY
        assert item.source_refs == ["unit:7"]
        assert item.authority_tier == AuthorityTier.USER
        assert item.minimum_fidelity == RepresentationTier.STRUCTURED
        assert item.current_representation == RepresentationTier.FULL
        assert item.content == {"type": "active_goal", "text": "my goal"}
        assert item.token_estimate == len("my goal") // 4
        assert item.metadata == {"run_id": 5, "step_id": 3}


# ===================================================================
# 7. Chat Projection Completeness Tests
# ===================================================================

class TestChatProjectionCompleteness:
    """Verify chat projection produces sufficient content for UI reconstruction."""

    def test_chat_projection_covers_all_displayable_unit_types(self):
        """Chat projection includes user_input, model_output_thinking,
        model_output_code, and final_answer — the correct display set.

        model_output_deep_thinking is intentionally excluded from the
        current implementation's relevant_types.
        """
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="Explain recursion", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="model_output_thinking", unit_content="Let me reason...", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="model_output_code", unit_content="def recurse(): ...", run_id=1, step_id=1),
            make_unit(unit_id=4, unit_type="model_output_deep_thinking", unit_content="deep analysis", run_id=1, step_id=1),
            make_unit(unit_id=5, unit_type="final_answer", unit_content="Recursion is...", run_id=1, step_id=1),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="chat")

        assert len(items) == 1
        turn = items[0]
        unit_types = [u["type"] for u in turn.content["units"]]

        assert "user_input" in unit_types
        assert "model_output_thinking" in unit_types
        assert "model_output_code" in unit_types
        assert "final_answer" in unit_types
        assert "model_output_deep_thinking" not in unit_types

    def test_chat_projection_preserves_unit_ordering(self):
        """Units within a chat turn maintain their original ordering by position."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="Q", run_id=1, step_id=1),
            make_unit(unit_id=2, unit_type="model_output_thinking", unit_content="think first", run_id=1, step_id=1),
            make_unit(unit_id=3, unit_type="model_output_code", unit_content="code second", run_id=1, step_id=1),
            make_unit(unit_id=4, unit_type="final_answer", unit_content="answer third", run_id=1, step_id=1),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="chat")

        assert len(items) == 1
        content_units = items[0].content["units"]
        types_in_order = [u["type"] for u in content_units]

        assert types_in_order == [
            "user_input",
            "model_output_thinking",
            "model_output_code",
            "final_answer",
        ]

    def test_chat_projection_includes_metadata_for_reconstruction(self):
        """Metadata contains run_id, step_id, and includes_thinking flag
        needed by any adapter converting to frontend format."""
        units = [
            make_unit(unit_id=1, unit_type="user_input", unit_content="Q", run_id=7, step_id=3),
            make_unit(unit_id=2, unit_type="final_answer", unit_content="A", run_id=7, step_id=3),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="chat")

        assert len(items) == 1
        meta = items[0].metadata
        assert meta["run_id"] == 7
        assert meta["step_id"] == 3
        assert meta["includes_thinking"] is True

    def test_chat_projection_source_refs_cover_all_included_units(self):
        """source_refs list contains references to ALL units included in the content."""
        units = [
            make_unit(unit_id=10, unit_type="user_input", unit_content="Q", run_id=1, step_id=1),
            make_unit(unit_id=20, unit_type="model_output_thinking", unit_content="think", run_id=1, step_id=1),
            make_unit(unit_id=30, unit_type="model_output_code", unit_content="code", run_id=1, step_id=1),
            make_unit(unit_id=40, unit_type="final_answer", unit_content="A", run_id=1, step_id=1),
            make_unit(unit_id=50, unit_type="tool", unit_content="tool()", run_id=1, step_id=1, tool_call_id="tc-1"),
        ]
        projector = HistoryProjector(make_query_fn(units))
        items = projector.project(conversation_id=1, purpose="chat")

        assert len(items) == 1
        turn = items[0]

        expected_refs = {"unit:10", "unit:20", "unit:30", "unit:40"}
        assert set(turn.source_refs) == expected_refs
        assert len(turn.source_refs) == len(turn.content["units"])


# ===================================================================
# 8. End-to-End Integration Tests
# ===================================================================

class MockHistoryProjector:
    """Mock projector for integration tests — no real DB needed."""

    def __init__(self, items=None, should_fail=False):
        self._items = items or []
        self._should_fail = should_fail

    def project(self, conversation_id, run_id=None, purpose="model_context"):
        if self._should_fail:
            raise RuntimeError("Simulated projection failure")
        return self._items


class TestEndToEndIntegration:
    """Full flow: ContextManager + HistoryProjector -> assemble_final_context -> FinalContext."""

    def test_assemble_final_context_with_history_projector(self):
        """FinalContext.evidence.context_items contains both component-projected
        AND history-projected items when conversation_id is provided."""
        history_items = [
            ContextItem(
                item_id="chat_turn:1:1",
                item_type=ContextItemType.HISTORY_TURN,
                source_refs=["unit:1", "unit:2"],
                authority_tier=AuthorityTier.AGENT_INFERENCE,
                minimum_fidelity=RepresentationTier.STRUCTURED,
                current_representation=RepresentationTier.FULL,
                content={"user_query": "Hello", "assistant_response": "Hi there"},
                token_estimate=4,
                metadata={"run_id": 1, "step_id": 1},
            ),
        ]
        mock_projector = MockHistoryProjector(items=history_items)

        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
            history_projector=mock_projector,
        )
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="You are helpful"))
        manager.register_component(
            MemoryComponent(
                memories=[{"content": "User prefers Python", "memory_type": "user"}],
                formatted_content="User preferences: Python",
            )
        )

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        mock_handler = MagicMock()
        mock_handler.to_messages.return_value = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        with patch(
            "nexent.core.agents.context.item_handler_registry.ItemHandlerRegistry.get",
            return_value=mock_handler,
        ):
            final = manager.assemble_final_context(
                model=None,
                memory=memory,
                current_run_start_idx=0,
                tools=[],
                conversation_id=123,
            )

        assert final is not None
        assert len(final.evidence.context_items) > 0

        component_types = {item.item_type for item in final.evidence.context_items}
        assert ContextItemType.SYSTEM_PROMPT in component_types

        history_turn_items = [
            item for item in final.evidence.context_items
            if item.item_id == "chat_turn:1:1"
        ]
        assert len(history_turn_items) == 1
        assert history_turn_items[0].content["user_query"] == "Hello"

    def test_assemble_final_context_without_conversation_id_skips_history(self):
        """Without conversation_id, only component-projected items appear."""
        history_items = [
            ContextItem(
                item_id="chat_turn:1:1",
                item_type=ContextItemType.HISTORY_TURN,
                source_refs=["unit:1"],
                authority_tier=AuthorityTier.AGENT_INFERENCE,
                minimum_fidelity=RepresentationTier.STRUCTURED,
                current_representation=RepresentationTier.FULL,
                content={"user_query": "Should not appear"},
                token_estimate=3,
                metadata={"run_id": 1, "step_id": 1},
            ),
        ]
        mock_projector = MockHistoryProjector(items=history_items)

        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
            history_projector=mock_projector,
        )
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="You are helpful"))

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
        )

        assert final is not None
        assert len(final.evidence.context_items) > 0

        history_turn_items = [
            item for item in final.evidence.context_items
            if item.item_id == "chat_turn:1:1"
        ]
        assert len(history_turn_items) == 0

        component_types = {item.item_type for item in final.evidence.context_items}
        assert ContextItemType.SYSTEM_PROMPT in component_types

    def test_assemble_final_context_history_projector_failure_graceful(self):
        """When history projector raises, assemble_final_context continues
        with component items only — no crash."""
        mock_projector = MockHistoryProjector(should_fail=True)

        config = ContextManagerConfig(
            enabled=True,
            token_threshold=10000,
            use_context_items=True,
            history_projector=mock_projector,
        )
        manager = ContextManager(config=config)

        manager.register_component(SystemPromptComponent(content="You are helpful"))
        manager.register_component(
            MemoryComponent(
                memories=[{"content": "Important fact", "memory_type": "user"}],
                formatted_content="Memory: Important fact",
            )
        )

        memory = MagicMock()
        memory.system_prompt = None
        memory.steps = []

        final = manager.assemble_final_context(
            model=None,
            memory=memory,
            current_run_start_idx=0,
            tools=[],
            conversation_id=123,
        )

        assert final is not None
        assert len(final.messages) > 0
        assert len(final.evidence.context_items) > 0
        component_types = {item.item_type for item in final.evidence.context_items}
        assert ContextItemType.SYSTEM_PROMPT in component_types


if __name__ == "__main__":
    pytest.main([__file__])
