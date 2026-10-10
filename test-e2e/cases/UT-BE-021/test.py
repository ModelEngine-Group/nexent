"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")


















@STAGE
@pytest.mark.case_id("UT-BE-021")
@pytest.mark.asyncio
async def test_northbound_idempotency_rejects_inflight_and_allows_replay_after_end(monkeypatch: pytest.MonkeyPatch) -> None:
    from consts.exceptions import LimitExceededError
    from services import northbound_service as service

    monkeypatch.setattr(type(service.runtime_state_service), "enabled", property(lambda _self: False))
    service._IDEMPOTENCY_RUNNING.clear()
    key = service._build_idempotency_key("tenant", "chat", "same request")
    await service.idempotency_start(key, ttl_seconds=60)
    with pytest.raises(LimitExceededError, match="Duplicate"):
        await service.idempotency_start(key, ttl_seconds=60)
    await service.idempotency_end(key)
    await service.idempotency_start(key, ttl_seconds=60)
    await service.idempotency_end(key)








