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
@pytest.mark.case_id("AGT-072")
@pytest.mark.skip(reason="SKIPPED_BY_POLICY: HITL approval and run-control capability was removed from develop; legacy fields are covered by UT-BE-027 and API-167")
@pytest.mark.asyncio
async def test_hitl_capability_snapshot_and_control_contract(tenant_a_user) -> None:
    """The real approval journey owns tool execution; D3 proves the live API contract is enabled."""
    async with client("runtime", token=tenant_a_user.access_token, timeout=MODEL_TIMEOUT) as api:
        capabilities = await api.get("/agent/human-interactions/capabilities")
    assert_status(capabilities, 200)
    body = capabilities.json()
    assert body.get("enabled") is True
    assert body.get("accept_new_runs") is True
    assert body.get("live_resume") is True
    assert body.get("executor") in {"linear-json-v1", "native-live-v1"}
    assert isinstance(body.get("tool_approval_enabled"), bool)


