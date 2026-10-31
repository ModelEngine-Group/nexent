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
@pytest.mark.case_id("API-080")
@pytest.mark.asyncio
async def test_skill_file_access_rejects_traversal_missing_skill_and_missing_file(tenant_a_user) -> None:
    async with client("config", token=tenant_a_user.access_token) as api:
        missing_skill = await api.get("/skills/no-such-skill/files")
        missing_file = await api.get("/skills/no-such-skill/files/missing.txt")
        traversal = await api.get("/skills/no-such-skill/files/%2e%2e/%2e%2e/secrets.env")
    assert_status(missing_skill, 404)
    assert_status(missing_file, 404)
    assert traversal.status_code in {400, 404}
    assert "password" not in traversal.text.lower()






