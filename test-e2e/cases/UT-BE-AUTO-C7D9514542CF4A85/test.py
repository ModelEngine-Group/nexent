from __future__ import annotations

import pytest

from agents.agent_run_manager import (
    AgentRunConcurrencyExceededError,
    AgentRunManager,
)


@pytest.fixture
def manager() -> AgentRunManager:
    """Return the singleton and isolate per-agent capacity state for repeatability."""
    mgr = AgentRunManager()
    mgr._agent_capacity_counts.clear()
    mgr._agent_capacity_tokens.clear()
    return mgr


@pytest.mark.case_id("UT-BE-AUTO-C7D9514542CF4A85")
@pytest.mark.stage("D1")
def test_agent_capacity_reserve_release(manager: AgentRunManager) -> None:
    # Step 2: same agent_id=101 with max_concurrent_runs=1.
    token1 = manager.reserve_agent_capacity(101, 1)
    assert isinstance(token1, str) and token1 != ""
    assert manager.get_agent_capacity_count(101) == 1

    with pytest.raises(AgentRunConcurrencyExceededError):
        manager.reserve_agent_capacity(101, 1)
    assert manager.get_agent_capacity_count(101) == 1

    # Step 3: another agent_id=202 with max_concurrent_runs=2; third reserve exceeds.
    token202_1 = manager.reserve_agent_capacity(202, 2)
    token202_2 = manager.reserve_agent_capacity(202, 2)
    with pytest.raises(AgentRunConcurrencyExceededError):
        manager.reserve_agent_capacity(202, 2)
    assert manager.get_agent_capacity_count(202) == 2
    assert manager.get_agent_capacity_count(101) == 1

    # Step 4: max_concurrent_runs <= 0 raises ValueError with the exact message.
    for bad_limit in (0, -1):
        with pytest.raises(ValueError) as exc_info:
            manager.reserve_agent_capacity(303, bad_limit)
        assert "max_concurrent_runs must be greater than zero" in str(exc_info.value)
    assert manager.get_agent_capacity_count(303) == 0

    # Step 5: releasing the same token twice is idempotent.
    assert manager.release_agent_capacity(token1) is True
    assert manager.get_agent_capacity_count(101) == 0
    assert manager.release_agent_capacity(token1) is False
    assert manager.get_agent_capacity_count(101) == 0

    # Step 6: releasing a never-registered token returns False.
    assert manager.release_agent_capacity("forged-token-not-registered") is False

    # Step 7: release remaining capacity and verify counts roll back to zero.
    assert manager.release_agent_capacity(token202_1) is True
    assert manager.release_agent_capacity(token202_2) is True
    assert manager.get_agent_capacity_count(202) == 0
    assert manager.get_agent_capacity_count(101) == 0
    assert manager._agent_capacity_counts == {}
    assert manager._agent_capacity_tokens == {}
