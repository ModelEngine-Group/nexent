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
@pytest.mark.case_id("API-078")
@pytest.mark.asyncio
async def test_skill_create_rejects_duplicate_name_tool_names_and_invalid_upload(tenant_a_admin) -> None:
    skill = await _create_skill(tenant_a_admin, "duplicate")
    name = skill["name"]
    try:
        async with client("config", token=tenant_a_admin.access_token) as api:
            duplicate = await api.post("/skills", json=_skill_payload(name))
            unsupported = _skill_payload(f"tool-name-{uuid.uuid4().hex[:8]}")
            unsupported["tool_names"] = ["not-supported"]
            tool_names = await api.post("/skills", json=unsupported)
            upload = await api.post("/skills/upload", files={"file": ("bad.txt", b"not a skill", "text/plain")})
        assert_status(duplicate, 409)
        assert_status(tool_names, 500)
        assert_status(upload, 400)
    finally:
        await _delete_skill(tenant_a_admin, name)










