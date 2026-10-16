"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")






















@STAGE
@pytest.mark.case_id("UT-BE-023")
def test_config_sync_noop_does_not_delete_or_reinsert(monkeypatch: pytest.MonkeyPatch) -> None:
    from services import config_sync_service as service

    calls: list[tuple[str, tuple]] = []
    manager = SimpleNamespace(
        update_single_config=lambda *args: calls.append(("update", args)),
        delete_single_config=lambda *args: calls.append(("delete", args)),
        set_single_config=lambda *args: calls.append(("set", args)),
    )
    monkeypatch.setattr(service, "tenant_config_manager", manager)
    service.handle_model_config("t1", "u1", "LLM_ID", 7, {"LLM_ID": "7"})
    assert [name for name, _ in calls] == ["update"]




