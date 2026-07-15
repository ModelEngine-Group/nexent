"""Tests for AdmissibilityValidator."""

import hashlib


from nexent.core.agents.context.admissibility_validator import AdmissibilityValidator
from nexent.core.agents.context.context_item import (
    ContextItem,
    ContextItemType,
    RepresentationTier,
)
from nexent.core.agents.context.reducer_models import ReductionResult


def _make_item(
    minimum_fidelity: RepresentationTier = RepresentationTier.STRUCTURED,
    content: str = "test content",
) -> ContextItem:
    return ContextItem(
        item_id="test-item",
        item_type=ContextItemType.TOOL,
        content=content,
        minimum_fidelity=minimum_fidelity,
    )


def _make_result(
    admissible: bool = True,
    source_fingerprint: str = "abc123",
    content: str = "reduced content",
    representation: RepresentationTier = RepresentationTier.STRUCTURED,
) -> ReductionResult:
    return ReductionResult(
        representation=representation,
        source_fingerprint=source_fingerprint,
        token_count=10,
        generator="test",
        generator_version="1.0.0",
        admissible=admissible,
        loss_metadata={},
        content=content,
    )


class TestAdmissibilityValidatorMinimumFidelity:
    """Tests for minimum fidelity violation checks."""

    def test_target_below_minimum_fidelity_returns_inadmissible(self):
        item = _make_item(minimum_fidelity=RepresentationTier.FULL)
        result = _make_result()
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.STRUCTURED
        )
        assert validated.admissible is False
        assert validated.loss_metadata["reason"] == "minimum_fidelity_violation"

    def test_target_at_minimum_fidelity_passes(self):
        item = _make_item(minimum_fidelity=RepresentationTier.STRUCTURED)
        result = _make_result()
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.STRUCTURED
        )
        assert validated.admissible is True

    def test_target_above_minimum_fidelity_passes(self):
        item = _make_item(minimum_fidelity=RepresentationTier.POINTER)
        result = _make_result()
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.FULL
        )
        assert validated.admissible is True

    def test_pointer_below_structured_minimum(self):
        item = _make_item(minimum_fidelity=RepresentationTier.STRUCTURED)
        result = _make_result()
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.POINTER
        )
        assert validated.admissible is False
        assert validated.loss_metadata["reason"] == "minimum_fidelity_violation"


class TestAdmissibilityValidatorPassthrough:
    """Tests for already-inadmissible result passthrough."""

    def test_already_inadmissible_passes_through(self):
        item = _make_item()
        result = _make_result(
            admissible=False,
            source_fingerprint="fp123",
        )
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.STRUCTURED
        )
        assert validated.admissible is False
        assert validated.source_fingerprint == "fp123"
        assert validated is result


class TestAdmissibilityValidatorFingerprint:
    """Tests for empty source_fingerprint generation."""

    def test_empty_fingerprint_gets_generated(self):
        content = "test content"
        item = _make_item(content=content)
        result = _make_result(source_fingerprint="")
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.STRUCTURED
        )
        expected = hashlib.sha256(str(content).encode()).hexdigest()[:16]
        assert validated.source_fingerprint == expected
        assert len(validated.source_fingerprint) == 16

    def test_non_empty_fingerprint_preserved(self):
        item = _make_item()
        result = _make_result(source_fingerprint="existing_fp")
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.STRUCTURED
        )
        assert validated.source_fingerprint == "existing_fp"


class TestAdmissibilityValidatorContentCheck:
    """Tests for None content validation."""

    def test_none_content_at_non_pointer_rejected(self):
        item = _make_item()
        result = _make_result(content=None)
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.STRUCTURED
        )
        assert validated.admissible is False
        assert validated.loss_metadata["reason"] == "content_required_but_none"

    def test_none_content_at_pointer_allowed(self):
        item = _make_item(minimum_fidelity=RepresentationTier.POINTER)
        result = _make_result(content=None, representation=RepresentationTier.POINTER)
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.POINTER
        )
        assert validated.admissible is True


class TestAdmissibilityValidatorWithPolicy:
    """Tests for policy parameter (currently unused but accepted)."""

    def test_policy_none_accepted(self):
        item = _make_item()
        result = _make_result()
        validated = AdmissibilityValidator.validate(
            item, result, RepresentationTier.STRUCTURED, policy=None
        )
        assert validated.admissible is True
