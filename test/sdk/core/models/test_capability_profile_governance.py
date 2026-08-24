import pytest

from nexent.core.models.capacity_resolver import (
    CapabilityProfile,
    validate_capability_catalog,
)


def _profile(**overrides):
    values = {
        "provider": "dashscope",
        "model_name": "qwen-plus",
        "capability_profile_version": "dashscope/qwen-plus@2",
        "window_shape": "combined",
        "context_window_tokens": 131_072,
        "max_output_tokens": 16_384,
        "default_output_reserve_tokens": 4_096,
        "tokenizer_family": "qwen",
        "aliases": ("qwen-plus",),
        "exclusions": ("qwen-vl",),
        "evidence": ("aliyun-model-doc-2026-08",),
        "verified_at": "2026-08-01T00:00:00Z",
        "shared_context": True,
        "independent_input": False,
        "max_output": 16_384,
        "reasoning_behavior": "unknown",
        "overhead_behavior": "bounded",
        "confidence": "high",
    }
    values.update(overrides)
    return CapabilityProfile(**values)


def test_complete_evidence_backed_profile_is_auto_applicable():
    profile = _profile()
    result = validate_capability_catalog({("dashscope", "qwen-plus"): profile})
    assert profile.auto_applicable is True
    assert result[("dashscope", "qwen-plus")] == ()


def test_incomplete_legacy_profile_remains_suggestion_only():
    profile = _profile(
        aliases=(), evidence=(), verified_at=None, confidence="unknown"
    )
    result = validate_capability_catalog({("dashscope", "qwen-plus"): profile})
    assert profile.auto_applicable is False
    assert "evidence_missing" in result[("dashscope", "qwen-plus")]


def test_incomplete_profile_cannot_claim_verified_high_confidence():
    profile = _profile(evidence=())
    with pytest.raises(ValueError, match="incomplete_verified_profile"):
        validate_capability_catalog({("dashscope", "qwen-plus"): profile})


def test_declared_max_output_must_match_capacity_value():
    profile = _profile(max_output=8_192)
    with pytest.raises(ValueError, match="max_output_conflict"):
        validate_capability_catalog({("dashscope", "qwen-plus"): profile})


def test_catalog_key_must_match_profile_identity():
    with pytest.raises(ValueError, match="catalog_key_mismatch"):
        validate_capability_catalog({("other", "qwen-plus"): _profile()})


def test_production_catalog_verified_rows_are_complete_and_legacy_rows_are_suggestion_only():
    from consts.capability_profiles import CATALOG

    diagnostics = validate_capability_catalog(CATALOG)
    qwen = CATALOG[("dashscope", "qwen-plus")]
    assert qwen.auto_applicable is True
    assert diagnostics[("dashscope", "qwen-plus")] == ()
    qwen_37 = CATALOG[("dashscope", "qwen3.7-plus")]
    assert qwen_37.auto_applicable is True

    silicon_qwen = CATALOG[("silicon", "Qwen/Qwen3.6-27B")]
    assert silicon_qwen.auto_applicable is True
    assert silicon_qwen.capability_profile_version == "silicon/qwen3.6-27b@2"
    assert qwen_37.max_input_tokens == 991_808
    assert diagnostics[("dashscope", "qwen3.7-plus")] == ()
    assert CATALOG[("openai", "gpt-4o")].auto_applicable is False
