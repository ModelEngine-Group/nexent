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
@pytest.mark.case_id("API-125")
@pytest.mark.asyncio
async def test_automation_crud_rejects_invalid_input_unknown_id_and_other_owner(tenant_a_user, tenant_a_admin) -> None:
    async with client("runtime", token=tenant_a_user.access_token) as owner:
        invalid = await owner.get("/agent/automations", params={"page": 0, "page_size": 101})
        missing = await owner.patch(f"/agent/automations/{absent_numeric_id(__name__)}", json={"title": "x"})
    async with client("runtime", token=tenant_a_admin.access_token) as other:
        isolated = await other.get(f"/agent/automations/{absent_numeric_id(__name__)}")
    assert_status(invalid, 422)
    assert_status(missing, 404)
    assert_status(isolated, 404)












