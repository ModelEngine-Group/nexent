from backend.services.model_profile_match_service import (
    resolve_model_profiles,
    serialize_profile_match,
)
from nexent.core.models.model_identity import MATCHER_VERSION
from nexent.core.models import tokenizer_registry
from nexent.core.models.tokenizer_registry import TokenizerProfile


def test_capacity_match_does_not_imply_tokenizer_match(monkeypatch):
    monkeypatch.setattr(tokenizer_registry, "PROFILES", {})
    result = resolve_model_profiles(
        model_name="qwen-plus",
        provider="dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_type="llm",
    )
    assert result.capacity_match.selected_profile == "dashscope/qwen-plus@1"
    assert result.tokenizer_match.selected_profile is None
    assert result.tokenizer_counting_mode == "estimated"
    assert result.canonical_model_id == "dashscope:qwen-plus"
    assert result.identity_metadata["matcher_version"] == MATCHER_VERSION


def test_unverified_tokenizer_profile_still_falls_back(monkeypatch):
    monkeypatch.setattr(tokenizer_registry, "PROFILES", {})
    tokenizer_registry.PROFILES["qwen-test@1"] = TokenizerProfile(
        profile_id="qwen-test@1",
        family="qwen",
        aliases=("qwen-plus",),
        adapter_version="1",
        package_version="1",
        fixture_version="1",
        verification_status="unverified",
    )
    result = resolve_model_profiles(
        model_name="qwen-plus",
        provider="dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_type="llm",
    )
    assert result.capacity_match.selected_profile is not None
    assert result.tokenizer_match.selected_profile == "qwen-test@1"
    assert result.tokenizer_match.reason in {
        "tokenizer_adapter_unavailable",
        "tokenizer_profile_unverified",
    }
    assert result.tokenizer_match.auto_applicable is False
    assert serialize_profile_match(result.tokenizer_match)["schema_version"] == 1
