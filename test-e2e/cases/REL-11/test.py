"""D5 security/reliability checks added for HITL and persistent logging."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from shared.config import load_yaml, test_root as get_test_root
from shared.http import assert_status, client




@pytest.mark.stage("D5")
@pytest.mark.case_id("REL-11")
@pytest.mark.asyncio
async def test_hitl_missing_run_is_stable_across_repeated_recovery_reads(tenant_a_user) -> None:
    run_id = f"recovery-{uuid4().hex}"
    snapshots = []
    async with client("runtime", token=tenant_a_user.access_token) as api:
        for _ in range(3):
            snapshot = await api.get(f"/agent/human-interactions/{run_id}")
            events = await api.get(
                f"/agent/human-interactions/{run_id}/events", params={"after_event": 0},
            )
            snapshots.append((snapshot.status_code, events.status_code, snapshot.text, events.text))
    assert all(item[:2] == snapshots[0][:2] for item in snapshots)
    assert snapshots[0][0] in {404, 409}
    assert snapshots[0][1] in {404, 409}
    assert len({json.dumps(item, ensure_ascii=False) for item in snapshots}) == 1


