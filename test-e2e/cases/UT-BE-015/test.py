"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")






@STAGE
@pytest.mark.case_id("UT-BE-015")
def test_agent_version_availability_and_rollback_target_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import agent_version_service as service

    # Unit boundary: supply the DB-backed system-Agent classification, not the
    # mutation guard itself, so rollback validation still executes normally.
    monkeypatch.setattr(service, "is_system_agent", lambda *_args: False)

    available, reasons = service._check_version_snapshot_availability(
        agent_id=1, tenant_id="t1", agent_info={"model_ids": [1]}, tool_instances=[{"enabled": True}]
    )
    assert available is True and reasons == []
    unavailable, reasons = service._check_version_snapshot_availability(
        agent_id=1, tenant_id="t1", agent_info={"model_ids": []}, tool_instances=[{"enabled": False}]
    )
    assert unavailable is False and len(reasons) == 2
    monkeypatch.setattr(service, "search_version_by_version_no", lambda *args: None)
    with pytest.raises(ValueError, match="not found"):
        service.rollback_version_impl(1, "t1", 99)




















