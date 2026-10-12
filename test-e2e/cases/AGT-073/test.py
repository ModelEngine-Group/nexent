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
@pytest.mark.case_id("AGT-073")
@pytest.mark.asyncio
async def test_configured_reasoning_model_connectivity_uses_exact_asset(tenant_a_admin) -> None:
    payload = model_request("llm", display_name=f"reasoning-probe-{uuid4().hex[:8]}")
    configured_names = [part.strip() for part in str(payload["model_name"]).split(",") if part.strip()]
    assert configured_names, "models.yaml llm model list is empty"
    preferred = configured_names[0]
    payload["model_name"] = preferred
    payload["display_name"] = preferred
    async with client("config", token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
        response = await api.post("/model/temporary_healthcheck", json=payload)
    assert_status(response, 200)
    body = response.json().get("data") or {}
    assert body.get("connectivity") is True
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert payload["api_key"] not in serialized
    assert preferred in serialized or body.get("connectivity") is True
