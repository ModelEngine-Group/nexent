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
@pytest.mark.case_id("API-079")
@pytest.mark.asyncio
async def test_skill_file_tree_and_content_round_trip(tenant_a_admin) -> None:
    skill = await _create_skill(tenant_a_admin, "files")
    name = skill["name"]
    try:
        async with client("config", token=tenant_a_admin.access_token) as api:
            tree = await api.get(f"/skills/{name}/files")
            content = await api.get(f"/skills/{name}/files/references/check.txt")
        assert_status(tree, 200)
        assert "references" in tree.text
        assert_status(content, 200)
        assert content.json()["content"] == "contract-asset"
    finally:
        await _delete_skill(tenant_a_admin, name)








