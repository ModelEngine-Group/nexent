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
@pytest.mark.case_id("API-043")
@pytest.mark.asyncio
@with_isolated_accounts
async def test_tenant_hard_quota_rejects_unprivileged_cross_tenant_write(tenant_a_user, tenant_b_admin) -> None:
    async with client("config", token=tenant_a_user.access_token) as api:
        response = await api.put(
            f"/platform/quota/tenants/{tenant_b_admin.tenant_id}",
            json={"hard_limit_mb": 1},
        )
    assert_status(response, 403)








