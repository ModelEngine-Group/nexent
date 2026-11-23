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
@pytest.mark.case_id("API-002")
@pytest.mark.asyncio
async def test_signup_rejects_weak_password_empty_invite_and_bad_email() -> None:
    invalid_payloads = [
        {"email": "bad", "password": "123", "invite_code": "x"},
        {"email": "new@example.com", "password": "123", "invite_code": "x"},
        {"email": "new@example.com", "password": "long-enough", "invite_code": "   "},
    ]
    async with client("config") as api:
        for payload in invalid_payloads:
            response = await api.post("/user/signup", json=payload)
            assert_status(response, 422)






































