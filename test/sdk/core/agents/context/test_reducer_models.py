"""Tests for reducer result models."""

import pytest

from nexent.core.agents.context.context_item import (
    AuthorityTier,
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
from nexent.core.agents.context.reducer_models import ReductionResult


class TestReductionResult:
    """Tests for ReductionResult frozen dataclass."""

    def test_reduction_result_is_frozen(self):
        result = ReductionResult(
            representation=RepresentationTier.FULL,
            source_fingerprint="fp-1",
            token_count=100,
            generator="passthrough",
            generator_version="0.1.0",
            admissible=True,
            loss_metadata={},
            content="test content",
        )

        with pytest.raises(AttributeError):
            result.content = "modified"

    def test_reduction_result_creation(self):
        result = ReductionResult(
            representation=RepresentationTier.COMPRESSED,
            source_fingerprint="fp-abc",
            token_count=50,
            generator="llm-summarizer",
            generator_version="1.2.0",
            admissible=True,
            loss_metadata={"dropped_sections": 3, "compression_ratio": 0.6},
            content="summarized content",
        )

        assert result.representation == RepresentationTier.COMPRESSED
        assert result.source_fingerprint == "fp-abc"
        assert result.token_count == 50
        assert result.generator == "llm-summarizer"
        assert result.generator_version == "1.2.0"
        assert result.admissible is True
        assert result.loss_metadata == {"dropped_sections": 3, "compression_ratio": 0.6}
        assert result.content == "summarized content"

    def test_reduction_result_with_none_content(self):
        result = ReductionResult(
            representation=RepresentationTier.POINTER,
            source_fingerprint="fp-none",
            token_count=0,
            generator="passthrough",
            generator_version="0.1.0",
            admissible=False,
            loss_metadata={"reason": "empty_input"},
            content=None,
        )

        assert result.content is None
        assert result.admissible is False
        assert result.token_count == 0
