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
@pytest.mark.case_id("API-167")
@pytest.mark.asyncio
async def test_removed_hitl_controls_are_rejected_for_each_tenant(tenant_a_user, tenant_b_user) -> None:
    for identity in (tenant_a_user, tenant_b_user):
        async with client("runtime", token=identity.access_token) as api:
            for field, value in (
                ("enable_hitl", True),
                ("hitl_run_id", "00000000-0000-0000-0000-000000000001"),
                ("hitl_after_event", 1),
            ):
                response = await api.post("/agent/run", json={"query": "normal query", field: value})
                assert_status(response, 422)
                assert "legacy human interaction fields" in response.text.lower()
                assert identity.access_token not in response.text


