from datetime import datetime, timezone

import pytest

from services.model_capacity_health_service import (
    catalog_freshness,
    classify_capacity_health,
)


NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("verified_at", "expected"),
    [
        ("2026-03-28T00:00:00Z", "current"),
        ("2026-03-27T00:00:00Z", "review_due"),
        ("2026-02-25T00:00:00Z", "expired"),
        (None, "expired"),
        ("bad", "expired"),
    ],
)
def test_catalog_freshness_boundaries(verified_at, expected):
    assert catalog_freshness(verified_at, now=NOW)[0] == expected


def base_record(**updates):
    record = {
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 131_072,
        "max_input_tokens": 991_808,
        "tokenizer_family": "qwen",
        "capacity_source": "profile",
        "capability_profile_version": "dashscope/qwen3.7-plus@1",
        "token_count_probe_metadata": {"status": "supported"},
    }
    record.update(updates)
    return record


def classify(record, verified_at="2026-08-24T00:00:00Z", auto=True):
    return classify_capacity_health(
        record,
        match={"match_kind": "exact", "auto_applicable": auto},
        profile_verified_at=verified_at,
        now=NOW,
    )


def test_healthy_verified_model():
    result = classify(base_record())
    assert result["status"] == "healthy"
    assert result["action"] == "none"


def test_supported_provider_count_is_healthy_without_local_tokenizer():
    result = classify(base_record(tokenizer_family=None))
    assert result["status"] == "healthy"
    assert result["reasons"] == ["capacity_verified"]


def test_invalid_has_highest_precedence():
    result = classify(base_record(max_output_tokens=1_000_000), verified_at="2020-01-01T00:00:00Z")
    assert result["status"] == "invalid"
    assert result["reasons"] == ["output_not_below_context"]


def test_unconfigured_offers_review_only_for_verified_match():
    result = classify(base_record(context_window_tokens=None))
    assert result["status"] == "unconfigured"
    assert result["action"] == "review_profile"
    assert classify(base_record(context_window_tokens=None), auto=False)["action"] == "edit"


def test_expired_precedes_degraded_probe():
    result = classify(
        base_record(token_count_probe_metadata={"status": "failed"}),
        verified_at="2026-02-25T00:00:00Z",
    )
    assert result["status"] == "expired"


def test_probe_and_estimated_states_are_actionable():
    degraded = classify(base_record(token_count_probe_metadata={"status": "temporary_failure"}))
    estimated = classify(base_record(capacity_source="legacy"))
    assert (degraded["status"], degraded["action"]) == ("probe_degraded", "retry_probe")
    assert (estimated["status"], estimated["action"]) == ("estimated", "review_profile")


def test_review_due_is_non_destructive_health_state():
    result = classify(base_record(), verified_at="2026-03-27T00:00:00Z")
    assert result["status"] == "review_due"
    assert result["action"] == "review_profile"
    assert result["profile_version"] == base_record()["capability_profile_version"]
