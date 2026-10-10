"""D3 real-provider scenarios for external memory, HITL and reasoning models."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest

from d3.assets import model_request
from shared.config import load_secret_env
from shared.http import MODEL_TIMEOUT, assert_status, client


def _required_secret(name: str) -> str:
    value = load_secret_env().get(name) or os.environ.get(name)
    if not value:
        raise AssertionError(f"required real test asset {name} is missing from secrets.env")
    return str(value)


@pytest.mark.stage("D3")
@pytest.mark.case_id("AGT-071")
@pytest.mark.skip(reason="SKIPPED_BY_POLICY: User-deferred real external memory provider and safe test-data deletion")
@pytest.mark.asyncio
async def test_external_memory_real_ingest_search_and_hot_update(tenant_a_admin) -> None:
    plugin = _required_secret("NEXENT_EXTERNAL_MEMORY_PLUGIN")
    endpoint = _required_secret("NEXENT_EXTERNAL_MEMORY_ENDPOINT")
    api_key = _required_secret("NEXENT_EXTERNAL_MEMORY_API_KEY")
    marker = f"EXTMEM-{uuid4().hex[:12]}"
    name = f"daily-memory-{uuid4().hex[:8]}"
    provider_id = None
    async with client("config", token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
        created = await api.post("/memory/providers", json={
            "provider_name": name,
            "connection_type": "plugin",
            "enabled": True,
            "timeout_seconds": 30,
            "params": {
                "plugin.name": plugin,
                "plugin.endpoint": endpoint,
                "plugin.api_key": api_key,
            },
        })
        assert_status(created, 200)
        provider_id = int(created.json()["provider_config_id"])
        try:
            ingested = await api.post(f"/memory/providers/{provider_id}/test-ingest", json={
                "units": [{
                    "content": f"Nexent external memory marker {marker}",
                    "metadata": {"run_marker": marker},
                }],
            })
            assert_status(ingested, 200)
            searched = await api.post(
                f"/memory/providers/{provider_id}/test-search",
                json={"query": marker, "top_k": 10},
            )
            assert_status(searched, 200)
            assert marker.lower() in json.dumps(searched.json(), ensure_ascii=False).lower()
            updated = await api.put(f"/memory/providers/{provider_id}", json={
                "provider_name": f"{name}-updated", "timeout_seconds": 45,
            })
            assert_status(updated, 200)
            reread = await api.get(f"/memory/providers/{provider_id}")
            assert_status(reread, 200)
            assert reread.json()["timeout_seconds"] == 45
            assert api_key not in reread.text
        finally:
            if provider_id is not None:
                deleted = await api.delete(f"/memory/providers/{provider_id}")
                assert_status(deleted, (200, 404))




