from consts.model_feature_capabilities import (
    CATALOG_REVISION,
    EXACT_CATALOG,
    FAMILY_RULES,
)
from nexent.core.models.feature_capability import resolve_feature_capabilities


def _resolve(factory: str, model: str) -> dict:
    return resolve_feature_capabilities(
        factory,
        model,
        exact_catalog=EXACT_CATALOG,
        family_rules=FAMILY_RULES,
        catalog_revision=CATALOG_REVISION,
    )


def test_p8_catalog_covers_representative_target_model_families():
    cases = {
        ("openai", "gpt-5.2"): ("catalog_family", True, True),
        ("dashscope", "qwen3.7-plus"): ("catalog_family", True, True),
        ("deepseek", "deepseek-reasoner"): ("catalog_exact", True, True),
        ("silicon", "Qwen/Qwen3-32B"): ("catalog_family", True, None),
        ("silicon", "deepseek-ai/DeepSeek-R1"): ("catalog_family", True, None),
        ("silicon", "moonshotai/Kimi-K2.5"): ("catalog_family", None, None),
        ("silicon", "MiniMaxAI/MiniMax-M2.1"): ("catalog_family", None, None),
        ("silicon", "zai-org/GLM-4.5"): ("catalog_family", None, None),
    }

    for (factory, model), expected in cases.items():
        resolved = _resolve(factory, model)
        assert (
            resolved["source"],
            resolved["reasoning"]["supported"],
            resolved["prompt_cache"]["supported"],
        ) == expected
        assert resolved["catalog_revision"] == CATALOG_REVISION
        assert resolved["evidence"]
        if resolved["reasoning"]["mode"] == "effort":
            assert resolved["reasoning"]["default_effort"] == "medium"
            assert "medium" in resolved["reasoning"]["efforts"]


def test_p8_catalog_never_propagates_capabilities_across_factories():
    assert _resolve("modelengine", "gpt-5.2")["source"] == "unknown"
    assert _resolve("tokenpony", "zai-org/GLM-4.5")["source"] == "unknown"
