"""D5 security/reliability checks added for HITL and persistent logging."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from shared.config import load_yaml, test_root as get_test_root
from shared.http import assert_status, client


@pytest.mark.stage("D5")
@pytest.mark.case_id("SEC-11")
@pytest.mark.asyncio
async def test_hitl_run_control_is_owner_scoped_and_secret_safe(tenant_a_user, tenant_b_user) -> None:
    missing = f"security-{uuid4().hex}"
    secret = f"SECRET-{uuid4().hex}"
    observations = []
    for identity in (tenant_a_user, tenant_b_user):
        async with client("runtime", token=identity.access_token) as api:
            observations.extend([
                await api.get(f"/agent/human-interactions/{missing}"),
                await api.get(f"/agent/human-interactions/{missing}/events", params={"after_event": 0}),
                await api.post(f"/agent/human-interactions/{missing}/pause"),
                await api.post(f"/agent/human-interactions/{missing}/steer", json={
                    "message_id": "security_message_1", "text": secret,
                }),
                await api.post(f"/agent/human-interactions/{missing}/terminate"),
            ])
    for response in observations:
        assert response.status_code in {404, 409}
        assert secret not in response.text
        assert "authorization" not in response.text.lower()




