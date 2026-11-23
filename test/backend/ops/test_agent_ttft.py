# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent TTFT uses measured samples and weighted publication arithmetic."""

from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from ops.monitoring.agent import AGENT_MONITORING, AgentFact, accumulate_agent, summarize_agent
from ops.monitoring.contracts import MAX_LONG


def document(run_id, **values):
    return AgentFact.model_validate({
        "tenant_id": "a", "fact_id": run_id, "agent_run_id": run_id, "root_run_id": run_id,
        "call_context_id": run_id, "agent_id": 21, "is_root": True, "started_at": "2026-11-18T23:59:59Z",
        "record_revision": 2, "outcome": "succeeded", **values,
    }).document(ZoneInfo("UTC"))


@pytest.mark.parametrize("value", [-1, MAX_LONG + 1, "invalid"])
def test_ttft_rejects_invalid_values(value):
    with pytest.raises(ValidationError):
        document("bad", ttft_ms=value)


def test_ttft_aggregates_zero_and_partial_output_independently_of_terminal_result():
    facts = [document("zero", ttft_ms=0), document("failed", ttft_ms=60, outcome="failed"),
             document("cancelled", ttft_ms=120, outcome="cancelled"), document("missing")]
    (_, row), = accumulate_agent(facts)
    assert row["ttft_sum_ms"] == 180 and row["ttft_sample_count"] == 3
    result = summarize_agent([row])
    assert result["avg_ttft_ms"] == 60 and result["ttft_sample_count"] == 3
    assert row["statistic_date"] == "2026-11-18"
    assert AGENT_MONITORING.fact_fields["ttft_ms"] == "long"
    assert AGENT_MONITORING.daily_fields["ttft_sum_ms"] == "long"


def test_ttft_merges_sums_and_samples_across_days_and_old_publications():
    old = {"execution_count": 3, "duration_sum_ms": 0, "duration_sample_count": 0}
    rows = [old, {**old, "ttft_sum_ms": 300, "ttft_sample_count": 3},
            {**old, "ttft_sum_ms": 500, "ttft_sample_count": 1}]
    result = summarize_agent(rows)
    assert result["avg_ttft_ms"] == 200 and result["ttft_sample_count"] == 4
    assert summarize_agent([old])["avg_ttft_ms"] is None
    assert summarize_agent(())["ttft_sample_count"] == 0
    (_, empty), = accumulate_agent([document("no-answer")])
    assert summarize_agent([empty])["avg_ttft_ms"] is None
    large = {**old, "ttft_sum_ms": 2**53 + 9, "ttft_sample_count": 1}
    assert summarize_agent([large])["avg_ttft_ms"] == (2**53 + 9) / 1
    (_, exact), = accumulate_agent([document("large", ttft_ms=2**53 + 9)])
    assert exact["ttft_sum_ms"] == 2**53 + 9
