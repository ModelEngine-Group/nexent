from nexent.monitor.monitoring import (
    _enrich_record_with_final_request_evidence,
    set_monitoring_final_request_evidence,
    update_monitoring_final_request_evidence,
)


def test_physical_request_evidence_is_allowlisted_and_joins_own_usage():
    set_monitoring_final_request_evidence({
        "schema_version": 1,
        "raw_estimate_tokens": 120,
        "hard_count_tokens": 138,
        "request_fingerprint": "hash",
        "compression_attempted": True,
    })
    update_monitoring_final_request_evidence(recovery_attempted=True, recovery_succeeded=True)
    record = {"input_tokens": 125}
    _enrich_record_with_final_request_evidence(record)
    assert record["context_budget_evidence"]["provider_prompt_usage_tokens"] == 125
    assert record["context_budget_evidence"]["recovery_succeeded"] is True
    assert "prompt" not in record["context_budget_evidence"]


def test_missing_evidence_leaves_legacy_record_unchanged():
    set_monitoring_final_request_evidence(None)
    record = {"input_tokens": 10}
    _enrich_record_with_final_request_evidence(record)
    assert "context_budget_evidence" not in record
