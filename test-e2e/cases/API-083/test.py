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
@pytest.mark.case_id("API-083")
@pytest.mark.asyncio
async def test_skill_repository_list_search_mine_counts_and_detail_contract(tenant_a_dev) -> None:
    async with client("config", token=tenant_a_dev.access_token) as api:
        listing = await api.get("/repository/skill", params={"page": 1, "page_size": 10, "search": ""})
        mine = await api.get("/repository/skill/mine")
        counts = await api.get("/repository/skill/mine/counts")
    for response in (listing, mine, counts):
        assert_status(response, 200)
    assert isinstance(listing.json(), dict)




