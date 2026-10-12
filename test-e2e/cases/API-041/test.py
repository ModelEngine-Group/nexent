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
@pytest.mark.case_id("API-041")
@pytest.mark.asyncio
async def test_platform_quota_rejects_unprivileged_and_invalid_capacity(tenant_a_user) -> None:
    async with client("config", token=tenant_a_user.access_token) as user:
        forbidden = await user.get("/platform/quota/overview")
        invalid = await user.put("/platform/quota/capacity", json={"capacity_gb": -1})
    assert_status(forbidden, 403)
    assert_status(invalid, 403)












