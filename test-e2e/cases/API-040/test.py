"""D2 quota contracts against the deployed config service."""

from __future__ import annotations

import pytest

from shared.auth import sign_in
from shared.http import assert_status, client
from shared.factories.tenant import with_isolated_accounts
from shared.factories.platform_capacity import (
    begin_capacity_probe, capacity_gb_from_overview, restore_capacity_probe,
)


STAGE = pytest.mark.stage("D2")


async def _platform_manager():
    for alias in ("super_admin", "asset_owner"):
        try:
            return await sign_in(alias)
        except (KeyError, RuntimeError):
            continue
    pytest.skip("API requires a super_admin or asset_owner entry in config/users.yaml")








@STAGE
@pytest.mark.case_id("API-040")
@pytest.mark.asyncio
async def test_platform_overview_and_capacity_round_trip() -> None:
    manager = await _platform_manager()
    async with client("config", token=manager.access_token) as api:
        overview = await api.get("/platform/quota/overview")
        assert_status(overview, 200)
        original = capacity_gb_from_overview(overview.json())
    key, expected = await begin_capacity_probe(manager, original)
    try:
        async with client("config", token=manager.access_token) as api:
            update = await api.put("/platform/quota/capacity", json={"capacity_gb": expected})
            assert_status(update, 200)
            verify = await api.get("/platform/quota/overview")
            assert_status(verify, 200)
            assert capacity_gb_from_overview(verify.json()) == expected
    finally:
        await restore_capacity_probe(manager, key, original, expected)














