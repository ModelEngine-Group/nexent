# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Regression coverage for silent run-level context evidence finalization."""

import logging

import pytest

from nexent.core.agents.context.evidence import ContextEvidenceCollector
from nexent.core.context_runtime.contracts import ContextEvidence


@pytest.mark.parametrize("status", ["completed", "error", "cancelled"])
@pytest.mark.parametrize("has_calls", [False, True], ids=["empty", "populated"])
def test_finalize_keeps_evidence_without_logging(caplog, status, has_calls):
    """AC-001/002: finalization is silent even with DEBUG logging enabled."""
    collector = ContextEvidenceCollector()
    if has_calls:
        collector.record_call(ContextEvidence(
            processing_mode="adaptive_compact",
            raw_token_estimate=120,
            final_token_estimate=80,
        ))

    with caplog.at_level(logging.DEBUG):
        evidence = collector.finalize(status=status)
        assert collector.finalize(status="other") is evidence

    assert caplog.records == []
    assert collector.finalized is evidence
    assert evidence.loop_status == status
    assert evidence.model_call_count == int(has_calls)
    assert evidence.final_token_estimate == (80 if has_calls else 0)


def test_finalize_preserves_aggregation_and_reset():
    """AC-002: the evidence consumer contract survives removal of its log."""
    collector = ContextEvidenceCollector()
    collector.record_call(ContextEvidence(
        raw_token_estimate=200,
        final_token_estimate=150,
        history_compression_triggered=True,
        representation_cache_hits=2,
        representation_cache_misses=1,
        compaction_attempts=1,
    ))
    collector.record_call(ContextEvidence(
        raw_token_estimate=120,
        final_token_estimate=80,
        representation_cache_hits=3,
        representation_cache_misses=2,
        compaction_attempts=2,
    ))
    evidence = collector.finalize(status="completed")
    assert evidence.raw_token_estimate == 200
    assert evidence.final_token_estimate == 80
    assert evidence.model_call_count == 2
    assert evidence.history_compression_triggered is True
    assert evidence.representation_cache_hits == 5
    assert evidence.representation_cache_misses == 3
    assert evidence.compaction_attempts == 3
    with pytest.raises(RuntimeError, match="already finalized"):
        collector.record_call(ContextEvidence())
    collector.reset()
    assert collector.finalized is None
    assert collector.finalize(status="cancelled") == ContextEvidence(loop_status="cancelled")
