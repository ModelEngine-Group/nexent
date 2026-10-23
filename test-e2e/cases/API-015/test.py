"""D2 identity, session, token and external-login boundary contracts."""

from __future__ import annotations

import uuid

import pytest

from shared.auth import sign_in
from shared.http import assert_status, client
from shared.resource_ids import absent_numeric_id


STAGE = pytest.mark.stage("D2")


def _data(response):
    payload = response.json()
    return payload.get("data") if isinstance(payload, dict) else None






























@STAGE
@pytest.mark.case_id("API-015")
@pytest.mark.asyncio
async def test_config_and_oauth_provider_feature_flags_are_structured(tenant_a_user) -> None:
    async with client("config", token=tenant_a_user.access_token) as api:
        config = await api.get("/config/load_config", params={"language": "zh"})
        providers = await api.get("/user/oauth/providers")
    assert_status(config, 200)
    assert isinstance(config.json(), dict)
    assert_status(providers, 200)
    assert isinstance(_data(providers), list)












