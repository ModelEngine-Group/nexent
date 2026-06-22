import os
import sys

import pytest

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

from services.model_capacity_suggestion_service import (
    CapacitySuggestionMatchKind,
    pick_provider,
    pick_provider_from_base_url,
    suggest_capacity,
)


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
