from types import SimpleNamespace

from nexent.core.models.provider_usage import (
    PROVIDER_USAGE_SCHEMA_VERSION,
    ProviderCallUsage,
    normalize_provider_usage,
)


def test_ac_tu_001_normalizes_provider_totals_and_disjoint_details():
    raw = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=30,
        total_tokens=130,
        prompt_tokens_details=SimpleNamespace(cached_tokens=40, cache_creation_input_tokens=10),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=20),
    )

    usage, quality, source, metadata = normalize_provider_usage(
        raw,
        provider="siliconflow",
        model="glm-5",
        capability_profile={
            "cache_partition_semantics": "disjoint_inclusive",
            "reasoning_usage_semantics": "included",
        },
    )

    assert source == "provider"
    assert usage.input_tokens == 100
    assert usage.fresh_input_tokens == 50
    assert usage.cache_read_tokens == 40
    assert usage.cache_write_tokens == 10
    assert usage.visible_output_tokens == 10
    assert usage.reasoning_tokens == 20
    assert usage.total_tokens == 130
    assert quality.degraded is False
    assert metadata == {
        "cached_tokens": 40,
        "cache_creation_input_tokens": 10,
        "reasoning_tokens": 20,
    }


def test_ac_tu_002_rejects_invalid_values_and_marks_conflicts():
    raw = {
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": float("inf"),
        "prompt_tokens_details": {"cached_tokens": 8, "cache_creation_input_tokens": 7},
        "completion_tokens_details": {"reasoning_tokens": 5},
    }

    usage, quality, source, _ = normalize_provider_usage(
        raw,
        provider="dashscope",
        model="qwen",
        capability_profile={
            "cache_partition_semantics": "disjoint_inclusive",
            "reasoning_usage_semantics": "included",
        },
    )

    assert source == "provider"
    assert usage.fresh_input_tokens == 0
    assert usage.visible_output_tokens == 0
    assert usage.total_tokens == 13
    assert usage.total_source == "derived"
    assert quality.degraded is True
    assert set(quality.reasons) == {
        "invalid_total_tokens",
        "cache_partition_exceeds_input",
        "reasoning_exceeds_output",
    }


def test_ac_tu_003_preserves_missing_as_null_and_explicit_zero():
    usage, quality, source, _ = normalize_provider_usage(
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        provider="modelengine",
        model="model",
    )

    assert source == "provider"
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.total_tokens == 0
    assert usage.cache_read_tokens is None
    assert usage.cache_write_tokens is None
    assert usage.reasoning_tokens is None
    assert usage.visible_output_tokens is None
    assert quality.degraded is False


def test_p10_ac_001_missing_provider_usage_stays_null():
    usage, quality, source, _ = normalize_provider_usage(
        None,
        provider="unknown",
        model="model",
    )

    assert source == "missing"
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.total_tokens is None
    assert usage.total_source == "missing"
    assert usage.fresh_input_tokens is None
    assert usage.reasoning_tokens is None
    assert quality.degraded is False


def test_ac_tu_004_call_record_contract_is_complete_and_versioned():
    record = ProviderCallUsage(call_id="call-1", turn_id="turn-1", step_number=2)

    payload = record.to_dict()

    assert payload["schema_version"] == PROVIDER_USAGE_SCHEMA_VERSION
    assert payload["call_id"] == "call-1"
    assert payload["turn_id"] == "turn-1"
    assert payload["usage"]["input_tokens"] is None
    assert payload["quality"] == {"degraded": False, "reasons": ()}


def test_ac_tu_002_siliconflow_hit_miss_conflict_is_not_silently_reconciled():
    usage, quality, _, metadata = normalize_provider_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 1,
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 50,
        },
        provider="siliconflow",
        model="model",
        capability_profile={
            "cache_write_semantics": "unsupported",
            "cache_hit_miss_semantics": "disjoint_inclusive",
        },
    )

    assert usage.cache_read_tokens == 40
    assert usage.cache_write_tokens == 0
    assert usage.fresh_input_tokens is None
    assert metadata["prompt_cache_hit_tokens"] == 40
    assert metadata["prompt_cache_miss_tokens"] == 50
    assert "cache_hit_miss_input_conflict" in quality.reasons
