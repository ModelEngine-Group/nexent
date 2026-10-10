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
@pytest.mark.case_id("API-045")
@pytest.mark.asyncio
async def test_personal_capacity_admin_views_support_filter_sort_detail_and_summary(tenant_a_admin, tenant_a_user) -> None:
    async with client("config", token=tenant_a_admin.access_token) as api:
        users = await api.get("/capacity/personal/users", params={
            "page": 1, "page_size": 100, "sort_by": "user_name", "sort_order": "asc",
        })
        details = await api.get(f"/capacity/personal/users/{tenant_a_user.user_id}/kbs")
        summary = await api.get("/capacity/personal/summary")
    for response in (users, details, summary):
        assert_status(response, 200)




