import os
import sys

import pytest

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

from unittest import mock

from services.model_capacity_suggestion_service import (
    CapacitySuggestionMatchKind,
    _fuzzy_catalog_match,
    normalize_model_name,
    pick_provider,
    pick_provider_from_base_url,
    suggest_capacity,
)
import services.model_capacity_suggestion_service as suggestion_module


class Profile:
    def __init__(
        self,
        context_window_tokens,
        max_output_tokens,
        capability_profile_version,
        max_input_tokens=None,
        default_output_reserve_tokens=4096,
        tokenizer_family="test-tokenizer",
    ):
        self.context_window_tokens = context_window_tokens
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.default_output_reserve_tokens = default_output_reserve_tokens
        self.tokenizer_family = tokenizer_family
        self.capability_profile_version = capability_profile_version


CATALOG = {
    ("openai", "gpt-4o"): Profile(128_000, 16_384, "openai/gpt-4o@1"),
    ("dashscope", "qwen-plus"): Profile(131_072, 16_384, "dashscope/qwen-plus@1"),
    ("other", "qwen-plus"): Profile(131_072, 16_384, "other/qwen-plus@1"),
    ("silicon", "deepseek-ai/DeepSeek-V4-Flash"): Profile(
        1_000_000,
        384_000,
        "silicon/deepseek-v4-flash@1",
    ),
    ("silicon", "Pro/moonshotai/Kimi-K2.6"): Profile(
        262_144,
        131_072,
        "silicon/kimi-k2.6@1",
    ),
}


def test_suggest_capacity_catalog_exact_from_base_url():
    result = suggest_capacity(
        model_name="gpt-4o",
        base_url="https://api.openai.com/v1",
        model_type="llm",
        catalog=CATALOG,
    )

    assert result.match_kind == CapacitySuggestionMatchKind.CATALOG_EXACT
    assert result.suggested_provider == "openai"
    assert result.canonical_model_name == "gpt-4o"
    assert result.capability_profile_version == "openai/gpt-4o@1"
    assert result.capacity_source_on_accept == "operator"
    assert result.suggestions.context_window_tokens == 128_000
    assert result.suggestions.max_output_tokens == 16_384


def test_suggest_capacity_catalog_exact_case_insensitive():
    result = suggest_capacity(
        model_name="GPT-4o",
        provider_hint="openai",
        model_type="llm",
        catalog=CATALOG,
    )

    assert result.match_kind == CapacitySuggestionMatchKind.CATALOG_EXACT
    assert result.canonical_model_name == "gpt-4o"


def test_suggest_capacity_catalog_fuzzy_normalized_name():
    result = suggest_capacity(
        model_name="Deepseek V4 Flash",
        provider_hint="silicon",
        model_type="llm",
        catalog=CATALOG,
    )

    assert result.match_kind == CapacitySuggestionMatchKind.CATALOG_FUZZY
    assert result.suggested_provider == "silicon"
    assert result.canonical_model_name == "deepseek-ai/DeepSeek-V4-Flash"
    assert result.capability_profile_version == "silicon/deepseek-v4-flash@1"


def test_suggest_capacity_catalog_fuzzy_unique_final_segment():
    result = suggest_capacity(
        model_name="Kimi-K2.6",
        provider_hint="silicon",
        model_type="llm",
        catalog=CATALOG,
    )

    assert result.match_kind == CapacitySuggestionMatchKind.CATALOG_FUZZY
    assert result.canonical_model_name == "Pro/moonshotai/Kimi-K2.6"


def test_suggest_capacity_rejects_ambiguous_providerless_model():
    result = suggest_capacity(
        model_name="qwen-plus",
        base_url="http://localhost:8000/v1",
        model_type="llm",
        catalog=CATALOG,
    )

    assert result.match_kind == CapacitySuggestionMatchKind.NONE
    assert result.suggestions is None


def test_suggest_capacity_flag_off_returns_none():
    result = suggest_capacity(
        model_name="gpt-4o",
        base_url="https://api.openai.com/v1",
        model_type="llm",
        catalog=CATALOG,
        enabled=False,
    )

    assert result.match_kind == CapacitySuggestionMatchKind.NONE
    assert result.suggestions is None
    assert "disabled" in result.match_explanation


def test_suggest_capacity_unsupported_model_type_returns_none():
    result = suggest_capacity(
        model_name="gpt-4o",
        base_url="https://api.openai.com/v1",
        model_type="embedding",
        catalog=CATALOG,
    )

    assert result.match_kind == CapacitySuggestionMatchKind.NONE
    assert result.suggestions is None


def test_suggest_capacity_empty_model_name_raises():
    with pytest.raises(ValueError, match="model_name is required"):
        suggest_capacity(model_name="", base_url="https://api.openai.com/v1", catalog=CATALOG)


def test_pick_provider_prefers_hint_then_base_url_then_unique_catalog():
    assert pick_provider("dashscope", "https://api.openai.com/v1", "gpt-4o", CATALOG) == "dashscope"
    assert pick_provider(None, "https://api.openai.com/v1", "gpt-4o", CATALOG) == "openai"
    assert pick_provider(None, None, "Kimi-K2.6", CATALOG) == "silicon"


def test_pick_provider_from_base_url_uses_shared_host_map():
    assert pick_provider_from_base_url("https://dashscope.aliyuncs.com/compatible-mode/v1") == "dashscope"
    assert pick_provider_from_base_url("https://api.siliconflow.cn/v1") == "silicon"
    assert pick_provider_from_base_url("https://api.tokenpony.ai/v1") == "tokenpony"
    assert pick_provider_from_base_url("http://localhost:8000/v1") is None


def test_pick_provider_from_base_url_recognises_extended_patterns():
    # Patterns added to mirror frontend PROVIDER_HINTS (modelConfig.ts).
    assert pick_provider_from_base_url("https://api.deepseek.com/v1") == "deepseek"
    assert pick_provider_from_base_url("https://api.jina.ai/v1") == "jina"
    # Broader OpenAI pattern: Azure OpenAI hosted endpoints also resolve.
    assert pick_provider_from_base_url("https://myorg.openai.azure.com/v1") == "openai"
    # Aliyun generic host without "dashscope" substring still resolves to
    # dashscope so capacity lookup can hit the existing dashscope catalog.
    assert pick_provider_from_base_url("https://bailian.aliyuncs.com/v1") == "dashscope"
    # Full-URL substring matching: self-hosted reverse proxy with the
    # provider name in the path is recognised (matches frontend behaviour).
    assert pick_provider_from_base_url("https://corp.example.com/openai/v1") == "openai"


def test_pick_provider_from_base_url_dashscope_wins_over_aliyuncs():
    # Both substrings present; order in HOST_PROVIDER_PATTERNS makes
    # dashscope win, which is the correct (more-specific) routing.
    assert pick_provider_from_base_url("https://dashscope.aliyuncs.com/v1") == "dashscope"


# ---------------------------------------------------------------------------
# W11 V1.5 - request/latency metrics wiring
# ---------------------------------------------------------------------------


def test_suggest_capacity_records_requests_and_latency_on_catalog_match():
    """Spec L706-708: every suggest_capacity invocation records one entry in
    requests_total (labelled by match_kind, model_type, provider) and one
    sample in latency_ms (labelled by match_kind, provider). A successful
    catalog match must fire the recorder exactly once with the right labels.
    """
    counter = mock.MagicMock()
    histogram = mock.MagicMock()

    with mock.patch.object(suggestion_module, "_capacity_suggestion_requests_total", counter), \
            mock.patch.object(suggestion_module, "_capacity_suggestion_latency_ms", histogram):
        result = suggest_capacity(
            model_name="gpt-4o",
            base_url="https://api.openai.com/v1",
            model_type="llm",
            catalog=CATALOG,
        )

    assert result.match_kind == CapacitySuggestionMatchKind.CATALOG_EXACT
    counter.add.assert_called_once()
    add_args = counter.add.call_args
    assert add_args.args[0] == 1
    assert add_args.args[1] == {
        "match_kind": "catalog_exact",
        "model_type": "llm",
        "provider": "openai",
    }
    histogram.record.assert_called_once()
    record_args = histogram.record.call_args
    assert record_args.args[0] >= 0  # non-negative duration in ms
    assert record_args.args[1] == {
        "match_kind": "catalog_exact",
        "provider": "openai",
    }


def test_suggest_capacity_records_none_match_with_unknown_provider_label():
    """When no provider can be inferred the result.suggested_provider is None
    and the metric labels fall back to provider='unknown'. Cardinality stays
    bounded -- we never emit raw user input as a label.
    """
    counter = mock.MagicMock()
    histogram = mock.MagicMock()

    with mock.patch.object(suggestion_module, "_capacity_suggestion_requests_total", counter), \
            mock.patch.object(suggestion_module, "_capacity_suggestion_latency_ms", histogram):
        result = suggest_capacity(
            model_name="unknown-local-model",
            base_url="http://localhost:8000/v1",
            model_type="llm",
            catalog=CATALOG,
        )

    assert result.match_kind == CapacitySuggestionMatchKind.NONE
    assert counter.add.call_args.args[1] == {
        "match_kind": "none",
        "model_type": "llm",
        "provider": "unknown",
    }
    assert histogram.record.call_args.args[1] == {
        "match_kind": "none",
        "provider": "unknown",
    }


def test_suggest_capacity_validation_error_does_not_record():
    """A ValueError (model_name required / too long) is a client-shape error
    raised before the matcher runs. It must not increment requests_total --
    that counter is for completed evaluations only, and SLO ratios would
    otherwise be skewed by client input mistakes.
    """
    counter = mock.MagicMock()
    histogram = mock.MagicMock()

    with mock.patch.object(suggestion_module, "_capacity_suggestion_requests_total", counter), \
            mock.patch.object(suggestion_module, "_capacity_suggestion_latency_ms", histogram), \
            pytest.raises(ValueError):
        suggest_capacity(model_name="", catalog=CATALOG)

    counter.add.assert_not_called()
    histogram.record.assert_not_called()


def test_suggest_capacity_no_op_when_instruments_disabled():
    """Same OTel-optional guard as the other recorders: if the instruments
    are None (OTel not installed in this deployment), suggest_capacity still
    returns the correct result without raising.
    """
    with mock.patch.object(suggestion_module, "_capacity_suggestion_requests_total", None), \
            mock.patch.object(suggestion_module, "_capacity_suggestion_latency_ms", None):
        result = suggest_capacity(
            model_name="gpt-4o",
            base_url="https://api.openai.com/v1",
            model_type="llm",
            catalog=CATALOG,
        )

    assert result.match_kind == CapacitySuggestionMatchKind.CATALOG_EXACT


# ---------------------------------------------------------------------------
# normalize_model_name — dedicated unit tests
# Spec "Tests and Release Evidence" §Unit Tests: covers all catalog entries
# and documented variants (GPT-4o, glm5.1, Deepseek V4 Flash, Kimi-K2.6,
# namespaced Silicon entries).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    ("gpt-4o", "gpt4o"),
    ("GPT-4o", "gpt4o"),
    ("glm-5.1", "glm51"),
    ("glm5.1", "glm51"),
    ("Deepseek V4 Flash", "deepseekv4flash"),
    ("deepseek-ai/DeepSeek-V4-Flash", "deepseekaideepseekv4flash"),
    ("Kimi-K2.6", "kimik26"),
    ("Pro/moonshotai/Kimi-K2.6", "promoonshotaikimik26"),
    ("qwen-plus", "qwenplus"),
    ("  gpt-4o  ", "gpt4o"),
    ("model_name.v2", "modelnamev2"),
    ("a-b_c.d/e f", "abcdef"),
    ("", ""),
    ("   ", ""),
])
def test_normalize_model_name_strips_lowercases_and_collapses_separators(raw, expected):
    assert normalize_model_name(raw) == expected


def test_normalize_model_name_all_catalog_entries_converge():
    """Every catalog model_name and its documented user-typed variant must
    normalize to the same string, proving the matcher can bridge them."""
    # Full-name convergence: case/separator variants of the same string
    full_name_cases = [
        ("gpt-4o", "GPT-4o"),
        ("glm-5.1", "glm5.1"),
        ("qwen-plus", "Qwen-Plus"),
    ]
    for canonical, user_typed in full_name_cases:
        assert normalize_model_name(canonical) == normalize_model_name(user_typed), \
            f"{canonical!r} and {user_typed!r} must normalize identically"

    # Final-segment convergence: namespaced catalog names match their
    # short form via _unique_final_segment_match, not full-name equality
    segment_cases = [
        ("deepseek-ai/DeepSeek-V4-Flash", "Deepseek V4 Flash"),
        ("Pro/moonshotai/Kimi-K2.6", "Kimi-K2.6"),
    ]
    for canonical, user_typed in segment_cases:
        final_segment = canonical.split("/")[-1]
        assert normalize_model_name(final_segment) == normalize_model_name(user_typed), \
            f"final segment of {canonical!r} and {user_typed!r} must normalize identically"


# ---------------------------------------------------------------------------
# _fuzzy_catalog_match — dedicated unit tests
# Spec "Tests and Release Evidence" §Unit Tests: rejects ambiguous
# final-segment matches.
# ---------------------------------------------------------------------------


def test_fuzzy_catalog_match_finds_normalized_name():
    result = _fuzzy_catalog_match("Deepseek V4 Flash", CATALOG, "silicon")
    assert result is not None
    key, profile = result
    assert key == ("silicon", "deepseek-ai/DeepSeek-V4-Flash")
    assert profile.capability_profile_version == "silicon/deepseek-v4-flash@1"


def test_fuzzy_catalog_match_unique_final_segment():
    result = _fuzzy_catalog_match("Kimi-K2.6", CATALOG, "silicon")
    assert result is not None
    key, _ = result
    assert key == ("silicon", "Pro/moonshotai/Kimi-K2.6")


def test_fuzzy_catalog_match_rejects_ambiguous_final_segment():
    """Two entries under the same provider whose final segments both match
    must be rejected — the operator's intent is unclear."""
    ambiguous_catalog = {
        ("silicon", "org-a/Kimi-K2.6"): Profile(262_144, 131_072, "silicon/org-a@1"),
        ("silicon", "org-b/Kimi-K2.6"): Profile(131_072, 65_536, "silicon/org-b@1"),
    }
    result = _fuzzy_catalog_match("Kimi-K2.6", ambiguous_catalog, "silicon")
    assert result is None


def test_fuzzy_catalog_match_returns_none_on_empty_catalog():
    result = _fuzzy_catalog_match("gpt-4o", {}, "openai")
    assert result is None


def test_fuzzy_catalog_match_returns_none_when_provider_has_no_match():
    result = _fuzzy_catalog_match("gpt-4o", CATALOG, "dashscope")
    assert result is None


def test_fuzzy_catalog_match_returns_none_for_unrelated_name():
    result = _fuzzy_catalog_match("totally-unknown-model", CATALOG, "silicon")
    assert result is None


# ---------------------------------------------------------------------------
# Pydantic constructor-audit tests
# Spec "Tests and Release Evidence" §Unit Tests: pin explicit Pydantic
# constructor call_args for ModelCapacitySuggestionResponse and
# CapacitySuggestionFields. Detects wire-format drift at the model boundary.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _pydantic_models():
    """Lazy-load Pydantic models from consts.model, skipping the entire
    test group when the SDK import chain is unavailable (e.g. missing
    smolagents/mem0 in the test environment)."""
    try:
        from consts.model import (
            CapacityCoverageBareModel,
            CapacityCoverageResponse,
            CapacitySuggestionFields,
            ModelCapacitySuggestionResponse,
        )
        return {
            "CapacitySuggestionFields": CapacitySuggestionFields,
            "ModelCapacitySuggestionResponse": ModelCapacitySuggestionResponse,
            "CapacityCoverageBareModel": CapacityCoverageBareModel,
            "CapacityCoverageResponse": CapacityCoverageResponse,
        }
    except (ImportError, ModuleNotFoundError):
        pytest.skip("consts.model import chain unavailable (missing SDK deps)")


def test_capacity_suggestion_fields_model_dump_shape(_pydantic_models):
    """Pin the wire-format of CapacitySuggestionFields.model_dump().
    Any new field, renamed field, or changed default will break this test."""
    CapacitySuggestionFields = _pydantic_models["CapacitySuggestionFields"]

    fields = CapacitySuggestionFields(
        context_window_tokens=128_000,
        max_input_tokens=64_000,
        max_output_tokens=16_384,
        default_output_reserve_tokens=4_096,
        tokenizer_family="tiktoken",
    )
    dumped = fields.model_dump()

    assert set(dumped.keys()) == {
        "context_window_tokens",
        "max_input_tokens",
        "max_output_tokens",
        "default_output_reserve_tokens",
        "tokenizer_family",
    }
    assert dumped == {
        "context_window_tokens": 128_000,
        "max_input_tokens": 64_000,
        "max_output_tokens": 16_384,
        "default_output_reserve_tokens": 4_096,
        "tokenizer_family": "tiktoken",
    }


def test_capacity_suggestion_fields_all_optional_defaults_none(_pydantic_models):
    CapacitySuggestionFields = _pydantic_models["CapacitySuggestionFields"]
    fields = CapacitySuggestionFields()
    dumped = fields.model_dump()

    assert all(v is None for v in dumped.values())


def test_model_capacity_suggestion_response_catalog_exact_shape(_pydantic_models):
    """Pin the wire-format of a catalog_exact response. Every field name,
    type, and presence/absence matters for the frontend contract."""
    CapacitySuggestionFields = _pydantic_models["CapacitySuggestionFields"]
    ModelCapacitySuggestionResponse = _pydantic_models["ModelCapacitySuggestionResponse"]

    response = ModelCapacitySuggestionResponse(
        suggestions=CapacitySuggestionFields(
            context_window_tokens=128_000,
            max_output_tokens=16_384,
            default_output_reserve_tokens=4_096,
            tokenizer_family="tiktoken",
        ),
        match_kind="catalog_exact",
        match_confidence="high",
        match_explanation="Matched approved catalog profile openai/gpt-4o@1",
        suggested_provider="openai",
        canonical_model_name="gpt-4o",
        capability_profile_version="openai/gpt-4o@1",
        capacity_source_on_accept="operator",
    )
    dumped = response.model_dump()

    assert set(dumped.keys()) == {
        "suggestions",
        "match_kind",
        "match_confidence",
        "match_explanation",
        "suggested_provider",
        "canonical_model_name",
        "capability_profile_version",
        "capacity_source_on_accept",
    }
    assert dumped["match_kind"] == "catalog_exact"
    assert dumped["match_confidence"] == "high"
    assert dumped["capacity_source_on_accept"] == "operator"
    assert dumped["suggestions"]["context_window_tokens"] == 128_000


def test_model_capacity_suggestion_response_none_match_shape(_pydantic_models):
    """When match_kind=none, suggestions is null and optional metadata fields
    are absent (None). The frontend depends on this shape."""
    ModelCapacitySuggestionResponse = _pydantic_models["ModelCapacitySuggestionResponse"]

    response = ModelCapacitySuggestionResponse(
        suggestions=None,
        match_kind="none",
        match_explanation="No approved catalog profile matched",
    )
    dumped = response.model_dump()

    assert dumped["match_kind"] == "none"
    assert dumped["suggestions"] is None
    assert dumped["match_confidence"] is None
    assert dumped["suggested_provider"] is None
    assert dumped["canonical_model_name"] is None
    assert dumped["capability_profile_version"] is None
    assert dumped["capacity_source_on_accept"] is None


def test_model_capacity_suggestion_response_rejects_invalid_match_kind(_pydantic_models):
    """Pydantic must reject match_kind values outside the Literal set.
    Catches wire-format drift where a new match kind is added to the service
    but not to the Pydantic schema."""
    ModelCapacitySuggestionResponse = _pydantic_models["ModelCapacitySuggestionResponse"]
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ModelCapacitySuggestionResponse(
            match_kind="invalid_kind",
            match_explanation="test",
        )


def test_capacity_coverage_bare_model_shape(_pydantic_models):
    """Pin the wire-format of CapacityCoverageBareModel.model_dump()."""
    CapacityCoverageBareModel = _pydantic_models["CapacityCoverageBareModel"]

    bare = CapacityCoverageBareModel(
        model_id=42,
        model_name="glm-5",
        model_factory="OpenAI-API-Compatible",
        model_type="llm",
        max_tokens=131_072,
        suggestion_available=True,
    )
    dumped = bare.model_dump()

    assert set(dumped.keys()) == {
        "model_id",
        "model_name",
        "model_factory",
        "model_type",
        "max_tokens",
        "suggestion_available",
    }
    assert dumped["model_id"] == 42
    assert dumped["model_type"] == "llm"
    assert dumped["suggestion_available"] is True


def test_capacity_coverage_response_shape(_pydantic_models):
    """Pin the wire-format of CapacityCoverageResponse.model_dump()."""
    CapacityCoverageBareModel = _pydantic_models["CapacityCoverageBareModel"]
    CapacityCoverageResponse = _pydantic_models["CapacityCoverageResponse"]

    response = CapacityCoverageResponse(
        total_llm_vlm=5,
        bare_count=2,
        bare_models=[
            CapacityCoverageBareModel(
                model_id=1, model_name="m1", model_type="llm",
            ),
            CapacityCoverageBareModel(
                model_id=2, model_name="m2", model_type="vlm",
            ),
        ],
    )
    dumped = response.model_dump()

    assert set(dumped.keys()) == {"total_llm_vlm", "bare_count", "bare_models"}
    assert dumped["total_llm_vlm"] == 5
    assert dumped["bare_count"] == 2
    assert len(dumped["bare_models"]) == 2
    assert dumped["bare_models"][0]["model_id"] == 1
