"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")


























@STAGE
@pytest.mark.case_id("UT-BE-025")
def test_memory_pipeline_policy_uses_configured_scope_and_token_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import memory_context_service as service

    monkeypatch.setattr(service, "MEMORY_TOKEN_BUDGET", 2048)
    monkeypatch.setattr(service, "MMR_FINAL_TOP_K", 7)
    monkeypatch.setattr(service, "MMR_CANDIDATE_TOP_K", 20)
    config = service._build_pipeline_config()
    assert config.token_budget == 2048
    assert config.mmr_final_top_k == 7
    assert config.mmr_candidate_top_k == 20
