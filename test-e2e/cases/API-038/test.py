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
@pytest.mark.case_id("API-038")
@pytest.mark.asyncio
@with_isolated_accounts
async def test_tenant_quota_rejects_invalid_thresholds_and_cross_tenant_access(tenant_a_admin, tenant_a_user) -> None:
    path = f"/tenants/{tenant_a_admin.tenant_id}/quota"
    async with client("config", token=tenant_a_admin.access_token) as admin:
        invalid = await admin.put(path, json={"warning_threshold_pct": 99, "critical_threshold_pct": 50})
    assert_status(invalid, 400)
    async with client("config", token=tenant_a_user.access_token) as user:
        forbidden = await user.get("/tenants/not-the-users-tenant/quota")
    assert_status(forbidden, 403)


















