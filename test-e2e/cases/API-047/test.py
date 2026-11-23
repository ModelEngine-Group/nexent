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
@pytest.mark.case_id("API-047")
@pytest.mark.asyncio
@with_isolated_accounts
async def test_personal_quota_rejects_missing_value_bad_sort_and_unprivileged_write(tenant_a_admin, tenant_a_user) -> None:
    async with client("config", token=tenant_a_admin.access_token) as admin:
        missing = await admin.put(
            f"/capacity/personal/users/{tenant_a_user.user_id}/quota", json={}
        )
        bad_sort = await admin.get("/capacity/personal/users", params={"sort_by": "secret"})
    assert_status(missing, 400)
    assert_status(bad_sort, 400)
    async with client("config", token=tenant_a_user.access_token) as user:
        forbidden = await user.put("/capacity/personal/default-quota", json={"unlimited": True})
    assert_status(forbidden, 403)
