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
@pytest.mark.case_id("API-046")
@pytest.mark.asyncio
@with_isolated_accounts
async def test_personal_user_and_default_quota_support_unlimited_round_trip(tenant_a_admin, tenant_a_user) -> None:
    async with client("config", token=tenant_a_admin.access_token) as api:
        original = await api.get("/capacity/personal/default-quota")
        assert_status(original, 200)
        set_user = await api.put(
            f"/capacity/personal/users/{tenant_a_user.user_id}/quota",
            json={"unlimited": True},
        )
        assert_status(set_user, 200)
        set_default = await api.put("/capacity/personal/default-quota", json={"quota_limit_bytes": 1073741824})
        assert_status(set_default, 200)
        before = original.json()
        restore_payload = {"unlimited": True} if before.get("unlimited") else {
            "quota_limit_bytes": before["quota_limit_bytes"]
        }
        restore = await api.put("/capacity/personal/default-quota", json=restore_payload)
        assert_status(restore, 200)


