"""D2 fixed HTTP contracts for persisted automation tasks.

Task creation from natural language belongs to D3. These tests use an isolated
seed task when present and skip stateful checks explicitly when that asset is absent.
"""

from __future__ import annotations
from shared.resource_ids import absent_numeric_id

import pytest

from shared.asset_registry import resolve_asset
from shared.http import assert_status, client


STAGE = pytest.mark.stage("D2")


async def _first_task(identity) -> dict:
    seeded_id = resolve_asset("automation", "seeded_task_id", required=True)
    if seeded_id not in (None, ""):
        async with client("runtime", token=identity.access_token) as api:
            response = await api.get(f"/agent/automations/{int(seeded_id)}")
        assert_status(response, 200)
        data = response.json().get("data") or response.json()
        if isinstance(data, dict):
            return data
    raise AssertionError('isolated automation task response must be an object')












@STAGE
@pytest.mark.case_id("API-129")
@pytest.mark.asyncio
async def test_automation_schedule_patch_rejects_invalid_timezone_and_combinations(tenant_a_user) -> None:
    task = await _first_task(tenant_a_user)
    task_id = int(task["task_id"])
    invalid_trigger = {
        "mode": "RECURRING", "rule_type": "AT", "timezone": "Not/AZone",
        "start_at": "2030-01-01T00:00:00Z", "interval_seconds": 0,
    }
    async with client("runtime", token=tenant_a_user.access_token) as api:
        response = await api.patch(
            f"/agent/automations/{task_id}", json={"schedule_trigger": invalid_trigger}
        )
    assert_status(response, 422)




