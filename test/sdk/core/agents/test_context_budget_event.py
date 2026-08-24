import json
from types import SimpleNamespace

from nexent.core.agents.context_budget_event import build_context_budget_event
from nexent.core.agents.summary_cache import CompressionCallRecord


def test_context_budget_event_is_content_free_and_totals_savings():
    preflight = SimpleNamespace(
        components=SimpleNamespace(message_text=40, message_framing=5, tools=7, media=0, reasoning=3, other_semantic=2),
        count_source=SimpleNamespace(value="provider"), soft_budget=90, hard_budget=100,
        hard_count=57, request_fingerprint="request-hash", identity_fingerprint="budget-hash", retry_ordinal=1,
    )
    evidence = SimpleNamespace(
        purpose="step", raw_token_estimate=80, final_token_estimate=50,
        compression_attempted=True, fallback_compaction_used=False,
        compression_records=(CompressionCallRecord(call_type="history_summary"),),
    )
    event = build_context_budget_event(preflight, evidence, step_number=2, recovery_state="recovered")
    assert event["compression"] == {
        "attempted": True,
        "saved_tokens": 30,
        "ratio": 0.375,
        "fallback_compaction": False,
        "reasons": ["history_summary"],
    }
    assert sum(event["components"].values()) == 57
    assert event["count_source"] == "provider"
    serialized = json.dumps(event)
    for secret in ("messages", "prompt", "api_key", "tool_arguments", "endpoint"):
        assert secret not in serialized


def test_context_budget_event_handles_missing_context_evidence():
    preflight = SimpleNamespace(
        components=SimpleNamespace(message_text=1, message_framing=1, tools=0, media=0, reasoning=0, other_semantic=0),
        count_source="estimator", soft_budget=9, hard_budget=10, hard_count=2,
        request_fingerprint="r", identity_fingerprint="b", retry_ordinal=0,
    )
    event = build_context_budget_event(preflight, None, step_number=1)
    assert event["raw_tokens"] == event["final_tokens"] == 0
    assert event["compression"]["ratio"] == 0


def test_context_budget_event_allowlists_compression_reasons():
    preflight = SimpleNamespace(
        components=SimpleNamespace(message_text=1, message_framing=1, tools=0, media=0, reasoning=0, other_semantic=0),
        count_source="estimator", soft_budget=9, hard_budget=10, hard_count=2,
        request_fingerprint="r", identity_fingerprint="b", retry_ordinal=0,
    )
    evidence = SimpleNamespace(
        raw_token_estimate=8,
        final_token_estimate=4,
        compression_attempted=True,
        fallback_compaction_used=True,
        compression_records=(
            CompressionCallRecord(call_type="history_incremental"),
            CompressionCallRecord(call_type="history_incremental"),
            {"call_type": "long_term_memory_block_selection"},
            CompressionCallRecord(
                call_type="attacker-controlled-value",
                details={"error": "prompt and credential text must not escape"},
            ),
        ),
    )

    event = build_context_budget_event(preflight, evidence, step_number=3)

    assert event["compression"]["reasons"] == [
        "history_incremental",
        "long_term_memory_selection",
        "representation_compaction",
    ]
    serialized = json.dumps(event)
    assert "attacker-controlled-value" not in serialized
    assert "credential text" not in serialized
