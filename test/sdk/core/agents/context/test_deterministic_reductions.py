"""Tests for deterministic handler reductions and registry dispatch."""

import hashlib

import pytest

from nexent.core.agents.context.context_item import (
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
from nexent.core.agents.context.item_handler_registry import ItemHandlerRegistry
from nexent.core.agents.context.reducer_models import ReductionResult
from nexent.core.agents.context.handlers import (
    ExternalAgentHandler,
    ManagedAgentHandler,
    MemoryHandler,
    SkillHandler,
    SystemPromptHandler,
    ToolHandler,
)
from nexent.core.agents.context.handlers import register_all


@pytest.fixture(autouse=True)
def reset_registry():
    ItemHandlerRegistry.reset()
    yield
    ItemHandlerRegistry.reset()


def _fp(content) -> str:
    return hashlib.sha256(str(content).encode()).hexdigest()[:16]


def _te(content) -> int:
    return len(str(content)) // 4


TOOL_CONTENT = {
    "name": "search_web",
    "description": "Search the web for information. Returns top results.",
    "parameters": ["query", "max_results", "language"],
}

SKILL_CONTENT = {
    "name": "code_review",
    "description": "Review code for best practices and common pitfalls in Python projects.",
}

AGENT_CONTENT = {
    "name": "research_agent",
    "description": "Performs deep research on topics. Uses web search and summarization.",
    "tools": ["search_web", "summarize"],
    "capability_tags": ["research", "summarization"],
}


class TestToolHandlerReduction:
    """Tests for ToolHandler deterministic reduce()."""

    def test_full_returns_original(self):
        handler = ToolHandler()
        item = ContextItem(
            item_id="t1", item_type=ContextItemType.TOOL, content=TOOL_CONTENT
        )
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.content == TOOL_CONTENT
        assert result.representation == RepresentationTier.FULL
        assert result.admissible is True
        assert result.generator == "tool_handler_deterministic"
        assert result.source_fingerprint == _fp(TOOL_CONTENT)

    def test_structured_keeps_name_first_sentence_params(self):
        handler = ToolHandler()
        item = ContextItem(
            item_id="t1", item_type=ContextItemType.TOOL, content=TOOL_CONTENT
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["name"] == "search_web"
        assert result.content["description"] == "Search the web for information"
        assert result.content["parameters"] == ["query", "max_results", "language"]
        assert result.representation == RepresentationTier.STRUCTURED

    def test_pointer_keeps_name_and_param_count(self):
        handler = ToolHandler()
        item = ContextItem(
            item_id="t1", item_type=ContextItemType.TOOL, content=TOOL_CONTENT
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.content["name"] == "search_web"
        assert result.content["param_count"] == 3
        assert result.representation == RepresentationTier.POINTER

    def test_string_content_fallback(self):
        handler = ToolHandler()
        item = ContextItem(
            item_id="t1", item_type=ContextItemType.TOOL, content="simple tool"
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["name"] == "simple tool"
        assert result.content["description"] == ""
        assert result.content["parameters"] == []


class TestSkillHandlerReduction:
    """Tests for SkillHandler deterministic reduce()."""

    def test_full_returns_original(self):
        handler = SkillHandler()
        item = ContextItem(
            item_id="s1", item_type=ContextItemType.SKILL, content=SKILL_CONTENT
        )
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.content == SKILL_CONTENT
        assert result.generator == "skill_handler_deterministic"

    def test_structured_keeps_name_first_sentence_truncated(self):
        handler = SkillHandler()
        long_desc = {"name": "skill", "description": "A" * 200 + ". More text."}
        item = ContextItem(
            item_id="s1", item_type=ContextItemType.SKILL, content=long_desc
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["name"] == "skill"
        assert len(result.content["description"]) <= 100

    def test_pointer_keeps_name_only(self):
        handler = SkillHandler()
        item = ContextItem(
            item_id="s1", item_type=ContextItemType.SKILL, content=SKILL_CONTENT
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.content == {"name": "code_review"}
        assert result.representation == RepresentationTier.POINTER


class TestManagedAgentHandlerReduction:
    """Tests for ManagedAgentHandler deterministic reduce()."""

    def test_full_returns_original(self):
        handler = ManagedAgentHandler()
        item = ContextItem(
            item_id="a1",
            item_type=ContextItemType.MANAGED_AGENT,
            content=AGENT_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.content == AGENT_CONTENT
        assert result.generator == "managed_agent_handler_deterministic"

    def test_structured_keeps_name_desc_tags(self):
        handler = ManagedAgentHandler()
        item = ContextItem(
            item_id="a1",
            item_type=ContextItemType.MANAGED_AGENT,
            content=AGENT_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["name"] == "research_agent"
        assert result.content["description"] == "Performs deep research on topics"
        assert result.content["capability_tags"] == ["research", "summarization"]
        assert "tools" not in result.content

    def test_pointer_keeps_name_and_tags(self):
        handler = ManagedAgentHandler()
        item = ContextItem(
            item_id="a1",
            item_type=ContextItemType.MANAGED_AGENT,
            content=AGENT_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.content["name"] == "research_agent"
        assert result.content["capability_tags"] == ["research", "summarization"]
        assert "description" not in result.content
        assert "tools" not in result.content


class TestExternalAgentHandlerReduction:
    """Tests for ExternalAgentHandler deterministic reduce()."""

    def test_full_returns_original(self):
        handler = ExternalAgentHandler()
        item = ContextItem(
            item_id="e1",
            item_type=ContextItemType.EXTERNAL_AGENT,
            content=AGENT_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.content == AGENT_CONTENT
        assert result.generator == "external_agent_handler_deterministic"

    def test_structured_keeps_name_desc_tags(self):
        handler = ExternalAgentHandler()
        item = ContextItem(
            item_id="e1",
            item_type=ContextItemType.EXTERNAL_AGENT,
            content=AGENT_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.content["name"] == "research_agent"
        assert result.content["description"] == "Performs deep research on topics"
        assert result.content["capability_tags"] == ["research", "summarization"]

    def test_pointer_keeps_name_and_tags(self):
        handler = ExternalAgentHandler()
        item = ContextItem(
            item_id="e1",
            item_type=ContextItemType.EXTERNAL_AGENT,
            content=AGENT_CONTENT,
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.content["name"] == "research_agent"
        assert result.content["capability_tags"] == ["research", "summarization"]


class TestSystemPromptHandlerReduction:
    """Tests for SystemPromptHandler irreducible behavior."""

    def test_full_passes(self):
        handler = SystemPromptHandler()
        content = "You are a helpful assistant."
        item = ContextItem(
            item_id="sp1",
            item_type=ContextItemType.SYSTEM_PROMPT,
            content=content,
        )
        result = handler.reduce(item, RepresentationTier.FULL, 1000)
        assert result.admissible is True
        assert result.content == content
        assert result.representation == RepresentationTier.FULL
        assert result.generator == "system_prompt_passthrough"

    def test_structured_rejected(self):
        handler = SystemPromptHandler()
        item = ContextItem(
            item_id="sp1",
            item_type=ContextItemType.SYSTEM_PROMPT,
            content="You are a helpful assistant.",
        )
        result = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert result.admissible is False
        assert result.loss_metadata["reason"] == "system_prompt_irreducible"
        assert result.representation == RepresentationTier.FULL

    def test_pointer_rejected(self):
        handler = SystemPromptHandler()
        item = ContextItem(
            item_id="sp1",
            item_type=ContextItemType.SYSTEM_PROMPT,
            content="prompt",
        )
        result = handler.reduce(item, RepresentationTier.POINTER, 1000)
        assert result.admissible is False


class TestMemoryHandlerPassthrough:
    """Tests that MemoryHandler remains unchanged passthrough."""

    def test_passthrough_at_all_tiers(self):
        handler = MemoryHandler()
        content = "User prefers dark mode."
        item = ContextItem(
            item_id="m1",
            item_type=ContextItemType.MEMORY,
            content=content,
            token_estimate=50,
        )
        for tier in RepresentationTier:
            result = handler.reduce(item, tier, 1000)
            assert result.content == content
            assert result.admissible is True
            assert result.generator == "passthrough"


class TestItemHandlerRegistryReduceItem:
    """Tests for ItemHandlerRegistry.reduce_item() dispatch."""

    def test_reduce_item_dispatches_to_tool_handler(self):
        register_all()
        item = ContextItem(
            item_id="t1",
            item_type=ContextItemType.TOOL,
            content=TOOL_CONTENT,
            minimum_fidelity=RepresentationTier.POINTER,
        )
        result = ItemHandlerRegistry.reduce_item(
            item, RepresentationTier.STRUCTURED, 1000
        )
        assert isinstance(result, ReductionResult)
        assert result.admissible is True
        assert result.content["name"] == "search_web"
        assert result.source_fingerprint != ""

    def test_reduce_item_validates_minimum_fidelity(self):
        register_all()
        item = ContextItem(
            item_id="t1",
            item_type=ContextItemType.TOOL,
            content=TOOL_CONTENT,
            minimum_fidelity=RepresentationTier.FULL,
        )
        result = ItemHandlerRegistry.reduce_item(
            item, RepresentationTier.STRUCTURED, 1000
        )
        assert result.admissible is False
        assert result.loss_metadata["reason"] == "minimum_fidelity_violation"

    def test_reduce_item_system_prompt_irreducible(self):
        register_all()
        item = ContextItem(
            item_id="sp1",
            item_type=ContextItemType.SYSTEM_PROMPT,
            content="You are helpful.",
            minimum_fidelity=RepresentationTier.FULL,
        )
        result = ItemHandlerRegistry.reduce_item(
            item, RepresentationTier.STRUCTURED, 1000
        )
        assert result.admissible is False


class TestTokenEstimates:
    """Tests for token estimate accuracy."""

    @pytest.mark.parametrize(
        "handler_cls,item_type,content",
        [
            (ToolHandler, ContextItemType.TOOL, TOOL_CONTENT),
            (SkillHandler, ContextItemType.SKILL, SKILL_CONTENT),
            (ManagedAgentHandler, ContextItemType.MANAGED_AGENT, AGENT_CONTENT),
            (ExternalAgentHandler, ContextItemType.EXTERNAL_AGENT, AGENT_CONTENT),
        ],
        ids=["tool", "skill", "managed_agent", "external_agent"],
    )
    def test_token_estimate_within_20_percent(self, handler_cls, item_type, content):
        handler = handler_cls()
        item = ContextItem(item_id="x", item_type=item_type, content=content)
        for tier in [RepresentationTier.FULL, RepresentationTier.STRUCTURED, RepresentationTier.POINTER]:
            result = handler.reduce(item, tier, 1000)
            actual = _te(result.content)
            if actual == 0:
                assert result.token_count == 0
            else:
                assert abs(result.token_count - actual) <= max(1, actual * 0.2)


class TestFingerprintStability:
    """Tests for source_fingerprint determinism."""

    def test_same_input_same_fingerprint(self):
        handler = ToolHandler()
        item = ContextItem(
            item_id="t1", item_type=ContextItemType.TOOL, content=TOOL_CONTENT
        )
        r1 = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        r2 = handler.reduce(item, RepresentationTier.STRUCTURED, 1000)
        assert r1.source_fingerprint == r2.source_fingerprint

    def test_different_input_different_fingerprint(self):
        handler = ToolHandler()
        item1 = ContextItem(
            item_id="t1", item_type=ContextItemType.TOOL, content=TOOL_CONTENT
        )
        item2 = ContextItem(
            item_id="t2",
            item_type=ContextItemType.TOOL,
            content={"name": "other_tool", "description": "Other", "parameters": []},
        )
        r1 = handler.reduce(item1, RepresentationTier.FULL, 1000)
        r2 = handler.reduce(item2, RepresentationTier.FULL, 1000)
        assert r1.source_fingerprint != r2.source_fingerprint


class TestDeterminism:
    """Tests that same input always produces same output."""

    @pytest.mark.parametrize(
        "handler_cls,item_type,content",
        [
            (ToolHandler, ContextItemType.TOOL, TOOL_CONTENT),
            (SkillHandler, ContextItemType.SKILL, SKILL_CONTENT),
            (ManagedAgentHandler, ContextItemType.MANAGED_AGENT, AGENT_CONTENT),
            (ExternalAgentHandler, ContextItemType.EXTERNAL_AGENT, AGENT_CONTENT),
            (SystemPromptHandler, ContextItemType.SYSTEM_PROMPT, "You are helpful."),
        ],
        ids=["tool", "skill", "managed", "external", "system_prompt"],
    )
    def test_deterministic_output(self, handler_cls, item_type, content):
        handler = handler_cls()
        item = ContextItem(item_id="x", item_type=item_type, content=content)
        for tier in RepresentationTier:
            r1 = handler.reduce(item, tier, 1000)
            r2 = handler.reduce(item, tier, 1000)
            assert r1.content == r2.content
            assert r1.source_fingerprint == r2.source_fingerprint
            assert r1.token_count == r2.token_count
            assert r1.generator == r2.generator
            assert r1.admissible == r2.admissible
