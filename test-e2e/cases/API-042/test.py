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
@pytest.mark.case_id("API-042")
@pytest.mark.asyncio
@with_isolated_accounts
async def test_platform_manager_can_set_and_remove_tenant_hard_quota(tenant_a_admin) -> None:
    manager = await _platform_manager()
    path = f"/platform/quota/tenants/{tenant_a_admin.tenant_id}"
    async with client("config", token=manager.access_token) as api:
        set_limit = await api.put(path, json={"hard_limit_mb": 1048576})
        assert_status(set_limit, 200)
        assert set_limit.json()["tenant_id"] == tenant_a_admin.tenant_id
        removed = await api.delete(path)
        assert_status(removed, 200)










