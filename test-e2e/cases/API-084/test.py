"""D2 skill and skill-marketplace API contracts."""

from __future__ import annotations
from shared.factories.skill import _skill_payload, _create_skill, _delete_skill
from shared.resource_ids import absent_numeric_id

import uuid

import pytest

from shared.asset_registry import register_asset
from shared.factories.ownership import register_owned_http
from shared.http import assert_status, client


STAGE = pytest.mark.stage("D2")




















@STAGE
@pytest.mark.case_id("API-084")
@pytest.mark.asyncio
async def test_skill_repository_submission_and_withdrawal_state_machine(tenant_a_admin) -> None:
    skill = await _create_skill(tenant_a_admin, "market")
    name = skill["name"]
    skill_id = int(skill["skill_id"])
    try:
        async with client("config", token=tenant_a_admin.access_token) as api:
            submitted = await api.post(f"/repository/skill/{skill_id}")
            assert_status(submitted, 200)
            repository_id = int(submitted.json()["skill_repository_id"])
            detail = await api.get(f"/repository/skill/{repository_id}")
            assert_status(detail, 200)
            withdrawn = await api.patch(
                f"/repository/skill/{repository_id}/status", json={"status": "not_shared"}
            )
            assert_status(withdrawn, 200)
    finally:
        await _delete_skill(tenant_a_admin, name)


