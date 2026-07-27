"""Tests for context item data models and enumerations."""

from dataclasses import fields

from nexent.core.agents.context.context_item import (
    AuthorityTier,
    ContextItem,
    ContextItemType,
    RepresentationTier,
)


class TestContextItemTypeEnum:
    """Tests for ContextItemType enumeration."""

    def test_context_item_type_enum_has_all_values(self):
        expected = {
            "SYSTEM_PROMPT",
            "TOOL",
            "SKILL",
            "MEMORY",
            "KNOWLEDGE_BASE",
            "MANAGED_AGENT",
            "EXTERNAL_AGENT",
            "HISTORY_TURN",
            "TOOL_CALL_RESULT",
        }
        actual = {member.name for member in ContextItemType}
        assert actual == expected

    def test_context_item_type_is_string_enum(self):
        for member in ContextItemType:
            assert isinstance(member.value, str)


class TestRepresentationTierEnum:
    """Tests for RepresentationTier enumeration."""

    def test_representation_tier_enum_has_all_values(self):
        expected = {"FULL", "COMPRESSED", "STRUCTURED", "POINTER"}
        actual = {member.name for member in RepresentationTier}
        assert actual == expected


class TestAuthorityTierEnum:
    """Tests for AuthorityTier enumeration."""

    def test_authority_tier_enum_has_all_values(self):
        expected = {
            "PLATFORM",
            "TENANT",
            "USER",
            "TOOL_RESULT",
            "RETRIEVED_MEMORY",
            "SUMMARY",
            "AGENT_INFERENCE",
        }
        actual = {member.name for member in AuthorityTier}
        assert actual == expected


class TestContextItem:
    """Tests for ContextItem dataclass."""

    def test_context_item_default_values(self):
        item = ContextItem(item_id="test-1", item_type=ContextItemType.TOOL)

        assert item.item_id == "test-1"
        assert item.item_type == ContextItemType.TOOL
        assert item.source_refs == []
        assert item.authority_tier == AuthorityTier.AGENT_INFERENCE
        assert item.minimum_fidelity == RepresentationTier.STRUCTURED
        assert item.current_representation == RepresentationTier.FULL
        assert item.content is None
        assert item.token_estimate == 0
        assert item.metadata == {}
        assert item.lifecycle_status == "active"
        assert item.recompute_cost is None

    def test_context_item_custom_values(self):
        item = ContextItem(
            item_id="custom-1",
            item_type=ContextItemType.MEMORY,
            source_refs=["ref-1", "ref-2"],
            authority_tier=AuthorityTier.USER,
            minimum_fidelity=RepresentationTier.FULL,
            current_representation=RepresentationTier.COMPRESSED,
            content="some memory content",
            token_estimate=150,
            metadata={"key": "value"},
            lifecycle_status="archived",
            recompute_cost=50,
        )

        assert item.item_id == "custom-1"
        assert item.item_type == ContextItemType.MEMORY
        assert item.source_refs == ["ref-1", "ref-2"]
        assert item.authority_tier == AuthorityTier.USER
        assert item.minimum_fidelity == RepresentationTier.FULL
        assert item.current_representation == RepresentationTier.COMPRESSED
        assert item.content == "some memory content"
        assert item.token_estimate == 150
        assert item.metadata == {"key": "value"}
        assert item.lifecycle_status == "archived"
        assert item.recompute_cost == 50

    def test_context_item_serialization(self):
        """Verify dataclass fields round-trip correctly."""
        original = ContextItem(
            item_id="serial-1",
            item_type=ContextItemType.SKILL,
            source_refs=["src-a"],
            authority_tier=AuthorityTier.PLATFORM,
            minimum_fidelity=RepresentationTier.POINTER,
            current_representation=RepresentationTier.STRUCTURED,
            content={"skill": "data"},
            token_estimate=200,
            metadata={"version": 2},
            lifecycle_status="active",
            recompute_cost=10,
        )

        field_values = {f.name: getattr(original, f.name) for f in fields(original)}
        reconstructed = ContextItem(**field_values)

        for f in fields(original):
            assert getattr(original, f.name) == getattr(reconstructed, f.name)
