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
@pytest.mark.case_id("API-128")
@pytest.mark.asyncio
async def test_automation_schedule_exposes_fire_limits_end_and_recovery_state(tenant_a_user) -> None:
    task = await _first_task(tenant_a_user)
    async with client("runtime", token=tenant_a_user.access_token) as api:
        detail = await api.get(f"/agent/automations/{task['task_id']}")
    assert_status(detail, 200)
    data = detail.json()["data"]
    trigger = data.get("schedule_trigger") or data.get("schedule_config")
    assert isinstance(trigger, dict), f"automation detail omitted schedule configuration: {sorted(data)}"
    rule_type = trigger.get("rule_type") or data.get("schedule_rule_type")
    timezone = trigger.get("timezone") or data.get("timezone")
    assert rule_type in {"AT", "CRON", "INTERVAL"}
    assert timezone
    # These persisted fields expose the scheduler's next-fire, limit and
    # recovery state even though the API serializes the trigger as
    # `schedule_config` rather than the create-request name.
    for field in ("next_fire_at", "fire_count", "consecutive_failures"):
        assert field in data






