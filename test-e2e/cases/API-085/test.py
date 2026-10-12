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
@pytest.mark.case_id("API-085")
@pytest.mark.asyncio
async def test_skill_repository_rejects_missing_listing_invalid_status_and_anonymous_access(tenant_a_dev) -> None:
    async with client("config", token=tenant_a_dev.access_token) as api:
        missing = await api.get(f"/repository/skill/{absent_numeric_id(__name__)}")
        invalid = await api.patch(f"/repository/skill/{absent_numeric_id(__name__)}/status", json={"status": "invented"})
    async with client("config") as anonymous:
        unauthorized = await anonymous.get("/repository/skill/mine")
    assert_status(missing, 404)
    assert_status(invalid, 400)
    assert_status(unauthorized, 401)
