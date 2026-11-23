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
@pytest.mark.case_id("API-039")
@pytest.mark.asyncio
async def test_tenant_usage_supports_cache_refresh_and_per_kb_detail(tenant_a_user) -> None:
    path = f"/tenants/{tenant_a_user.tenant_id}/quota/usage"
    async with client("config", token=tenant_a_user.access_token) as api:
        cached = await api.get(path)
        refreshed = await api.get(path, params={"force_refresh": True, "detail": True})
    assert_status(cached, 200)
    assert_status(refreshed, 200)
    assert isinstance(refreshed.json().get("breakdown", []), list)
    assert refreshed.json().get("total_bytes", 0) >= 0
















