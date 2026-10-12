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
@pytest.mark.case_id("API-037")
@pytest.mark.asyncio
@with_isolated_accounts
async def test_tenant_quota_read_update_and_restore_warning_configuration(tenant_a_admin) -> None:
    path = f"/tenants/{tenant_a_admin.tenant_id}/quota"
    async with client("config", token=tenant_a_admin.access_token) as api:
        original = await api.get(path)
        assert_status(original, 200)
        before = original.json()
        changed = await api.put(path, json={
            "warning_enabled": True,
            "warning_threshold_pct": 71,
            "critical_threshold_pct": 91,
        })
        assert_status(changed, 200)
        verified = await api.get(path)
        assert_status(verified, 200)
        assert verified.json()["warning_threshold_pct"] == 71
        restore = await api.put(path, json={
            "warning_enabled": before.get("warning_enabled", True),
            "warning_threshold_pct": before.get("warning_threshold_pct", 80),
            "critical_threshold_pct": before.get("critical_threshold_pct", 95),
        })
        assert_status(restore, 200)




















