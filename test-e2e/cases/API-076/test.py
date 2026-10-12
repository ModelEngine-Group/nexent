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
@pytest.mark.case_id("API-076")
@pytest.mark.asyncio
async def test_skill_and_official_lists_expose_installation_state(tenant_a_user) -> None:
    async with client("config", token=tenant_a_user.access_token) as api:
        visible = await api.get("/skills")
        official = await api.get("/skills/official")
    assert_status(visible, 200)
    assert_status(official, 200)
    assert isinstance(visible.json()["skills"], list)
    assert all(item.get("status") in {"installable", "installed"} for item in official.json()["skills"])














