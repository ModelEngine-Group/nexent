"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")








@STAGE
@pytest.mark.case_id("UT-BE-016")
def test_mcp_port_suggestion_checks_every_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import remote_mcp_service as service

    candidates = iter([2001, 2002, 2003])
    monkeypatch.setattr(service.random, "randint", lambda low, high: next(candidates))
    checked: list[int] = []

    def available(port: int) -> bool:
        checked.append(port)
        return port == 2003

    monkeypatch.setattr(service, "check_container_port_conflict", available)
    assert service.suggest_container_port() == 2003
    assert checked == [2001, 2002, 2003]


















