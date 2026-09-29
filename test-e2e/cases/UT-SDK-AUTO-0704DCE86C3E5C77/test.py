from __future__ import annotations

import logging

import pytest

from nexent.core.agents.context.config import ContextManagerConfig

CASE_ID = "UT-SDK-AUTO-0704DCE86C3E5C77"
AGENT_CONTEXT_LOGGER = "agent_context"
SOFT_WARNING = "legacy context threshold normalized to Compaction Trigger Threshold"
HARD_WARNING = "legacy context rejection limit is deprecated and ignored"


def _has_warning(records: list[logging.LogRecord], needle: str) -> bool:
    return any(needle in record.getMessage() for record in records)


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D1")
def test_post_init_normalizes_legacy_input_budgets(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=AGENT_CONTEXT_LOGGER)

    cfg = ContextManagerConfig(soft_input_budget_tokens=1000)
    assert cfg.compaction_trigger_threshold_tokens == 1000
    assert cfg.effective_input_limit_tokens == 1250
    assert cfg.compaction_target_tokens == 750
    assert _has_warning(caplog.records, SOFT_WARNING)
    assert "soft_input_budget_tokens" not in vars(cfg)
    assert "hard_input_budget_tokens" not in vars(cfg)

    caplog.clear()

    cfg = ContextManagerConfig(hard_input_budget_tokens=2000)
    assert cfg.effective_input_limit_tokens == 0
    assert cfg.compaction_trigger_threshold_tokens == 0
    assert cfg.compaction_target_tokens == 0
    assert _has_warning(caplog.records, HARD_WARNING)
    assert "hard_input_budget_tokens" not in vars(cfg)
    assert "soft_input_budget_tokens" not in vars(cfg)

    caplog.clear()

    cfg = ContextManagerConfig(effective_input_limit_tokens=1000)
    assert cfg.compaction_trigger_threshold_tokens == 800
    assert cfg.compaction_target_tokens == 600
    assert cfg.effective_input_limit_tokens == 1000

    cfg = ContextManagerConfig(soft_input_budget_tokens=1)
    assert cfg.compaction_trigger_threshold_tokens == 1
    assert cfg.effective_input_limit_tokens == 1

    cfg = ContextManagerConfig(effective_input_limit_tokens=1)
    assert cfg.compaction_trigger_threshold_tokens == 1
    assert cfg.compaction_target_tokens == 1

    cfg = ContextManagerConfig(
        soft_input_budget_tokens=1000,
        effective_input_limit_tokens=5000,
        compaction_trigger_threshold_tokens=4000,
    )
    assert cfg.effective_input_limit_tokens == 5000
    assert cfg.compaction_trigger_threshold_tokens == 4000
    assert cfg.compaction_target_tokens == 3000

    cfg = ContextManagerConfig(
        soft_input_budget_tokens=1000,
        hard_input_budget_tokens=2000,
    )
    assert cfg.compaction_trigger_threshold_tokens == 1000
    assert cfg.effective_input_limit_tokens == 1250
    assert cfg.compaction_target_tokens == 750
