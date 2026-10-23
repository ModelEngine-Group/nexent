"""Real-model acceptance tests for Dreaming semantic compression."""

import os

import pytest

from nexent.memory.dreaming import DreamingMemoryUnit, build_user_memory_summary
from services.memory_dreaming_summarizer import TenantDreamingSummarizer
from utils.monitoring import monitoring_manager


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DREAMING_MODEL_INTEGRATION") != "1",
    reason="Set RUN_DREAMING_MODEL_INTEGRATION=1 for real-model verification",
)


def _ac019_units() -> list[DreamingMemoryUnit]:
    """Build the reproducible 14,163-character RAW acceptance fixture."""
    shared_detail = (
        "The microservice uses event-driven communication, an isolated data "
        "store, health-aware service discovery, gateway authentication and "
        "rate limiting, OpenTelemetry correlation IDs, circuit breakers, "
        "blue-green rollback, structured logs, and metrics-based monitoring."
    )
    units = [
        DreamingMemoryUnit(
            unit_id=f"pattern-{index}",
            content=(
                f"System architecture pattern {index}: {shared_detail} "
                f"The explicit verification marker is pattern {index}."
            ),
            evidence_ids=[str(index)],
            is_new=True,
        )
        for index in range(1, 36)
    ]
    current_length = len("\n".join(f"- {unit.content}" for unit in units))
    padding = 14_163 - current_length
    if padding < 0:
        raise AssertionError("AC-019 fixture template exceeds 14,163 characters")
    units[-1].content += "x" * padding
    assert len("\n".join(f"- {unit.content}" for unit in units)) == 14_163
    return units


def test_ac048_ac049_real_model_fact_preservation():
    assert monitoring_manager is not None
    tenant_id = os.environ["DREAMING_TEST_TENANT_ID"]
    user_id = os.environ["DREAMING_TEST_USER_ID"]
    compressor = TenantDreamingSummarizer(tenant_id, user_id)

    result = build_user_memory_summary(
        parent_units=[],
        new_units=_ac019_units(),
        max_chars=10_000,
        compressor=compressor,
        max_attempts=int(os.getenv("DREAMING_TEST_MAX_ATTEMPTS", "2")),
        run_id=49,
        agent_id=os.getenv("DREAMING_TEST_AGENT_ID", "1"),
    )

    assert result.raw_char_count == 14_163
    assert result.compression_status == "semantic", result.compression_audit
    assert result.published_char_count <= 10_000
    assert result.omitted_evidence_ids == []
    for index in range(1, 36):
        assert f"pattern {index}" in result.markdown
    assert result.compression_audit[-1] == {
        "attempt": result.compression_attempts,
        "outcome": "accepted",
        "validation": [],
    }
