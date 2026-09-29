"""D2 HTTP contracts for tags, external memory, legacy controls and model catalog."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest

from shared.http import assert_status, client


STAGE = pytest.mark.stage("D2")


def _is_masked_secret(value: object) -> bool:
    """Accept the current provider contract without requiring the plaintext secret."""
    if value is None or value == "***":
        return True
    return isinstance(value, str) and re.fullmatch(r".{3}\*{3}.{4}", value) is not None




@STAGE
@pytest.mark.case_id("API-166")
@pytest.mark.asyncio
async def test_external_memory_provider_contract_and_secret_masking(tenant_a_admin) -> None:
    async with client("config", token=tenant_a_admin.access_token) as api:
        plugins = await api.get("/memory/provider-plugins")
        listed = await api.get("/memory/providers")
        invalid = await api.post("/memory/providers", json={
            "provider_name": f"invalid-{uuid4().hex[:8]}",
            "connection_type": "plugin",
            "enabled": False,
            "timeout_seconds": 30,
            "params": {"plugin.name": "__missing_plugin__", "plugin.api_key": "must-not-leak"},
        })
    assert_status(plugins, 200)
    plugin_body = plugins.json()
    assert isinstance(plugin_body.get("items"), list)
    assert_status(listed, 200)
    assert listed.json().get("count") == len(listed.json().get("items") or [])
    assert invalid.status_code in {400, 404}
    assert "must-not-leak" not in invalid.text
    for provider in listed.json().get("items") or []:
        params = provider.get("params") or {}
        assert all("api_key" not in key or _is_masked_secret(value)
                   for key, value in params.items())




