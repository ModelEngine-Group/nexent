import pytest

from nexent.core.models.model_identity import (
    MATCHER_VERSION,
    identities_are_safe_aliases,
    parse_model_identity,
)


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("Qwen2-7B-Instruct", {"family": "qwen", "version": "2", "size": "7b", "tune": "instruct"}),
        ("Qwen2.5-VL-7B-Instruct", {"family": "qwen", "version": "2.5", "modality": "vl"}),
        ("DeepSeek-R1-Distill-Qwen-32B", {"family": "deepseek", "reasoning": "r1", "size": "32b"}),
        ("Llama-3.1-8B-Instruct-AWQ", {"family": "llama", "version": "3.1", "quantization": "awq"}),
        ("Qwen2.5-72B-Instruct-128K", {"family": "qwen", "context_extension": "128k"}),
    ],
)
def test_ac_p1_003_parse_capacity_relevant_variants(model_id, expected):
    identity = parse_model_identity(model_id, "silicon")

    assert identity.matcher_version == MATCHER_VERSION
    for field_name, value in expected.items():
        assert getattr(identity, field_name) == value


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Qwen2-7B-Instruct", "Qwen2.5-7B-Instruct"),
        ("Qwen2.5-7B-Instruct", "Qwen2.5-VL-7B-Instruct"),
        ("DeepSeek-R1", "DeepSeek-R1-Distill-Qwen-32B"),
        ("Qwen2.5-72B-Instruct", "Qwen2.5-72B-Instruct-128K"),
    ],
)
def test_ac_p1_003_conflicting_variants_are_not_aliases(left, right):
    assert not identities_are_safe_aliases(
        parse_model_identity(left, "silicon"),
        parse_model_identity(right, "silicon"),
    )


def test_ac_p1_003_separator_variants_are_safe_aliases():
    assert identities_are_safe_aliases(
        parse_model_identity("Deepseek V4 Flash", "silicon"),
        parse_model_identity("DeepSeek-V4-Flash", "silicon"),
    )


def test_ac_p1_003_provider_namespace_is_part_of_canonical_id():
    assert parse_model_identity("qwen-plus", "dashscope").canonical_id != parse_model_identity(
        "qwen-plus", "other"
    ).canonical_id


def test_ac_p1_003_empty_model_id_rejected():
    with pytest.raises(ValueError, match="model_id is required"):
        parse_model_identity("  ")
