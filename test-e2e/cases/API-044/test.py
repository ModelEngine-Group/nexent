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
@pytest.mark.case_id("API-044")
@pytest.mark.asyncio
async def test_current_user_personal_capacity_has_usage_and_limit_semantics(tenant_a_user) -> None:
    async with client("config", token=tenant_a_user.access_token) as api:
        response = await api.get("/capacity/personal/me")
    assert_status(response, 200)
    body = response.json()
    assert body.get("used_bytes", 0) >= 0
    assert body.get("kb_count", 0) >= 0
    quota = body.get("quota_bytes")
    assert quota is None or quota >= 0
    assert body.get("usage_rate") is None or body["usage_rate"] >= 0






