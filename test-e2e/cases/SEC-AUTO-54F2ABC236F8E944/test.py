from __future__ import annotations

import json
import uuid

import pytest

from shared.http import assert_status, client
from shared.factories.provider import owned_provider_client

CASE_ID = "SEC-AUTO-54F2ABC236F8E944"

SHORT_SECRET = "shortkey"
LONG_SECRET = "sk-abcdef123456"
SHORT_MASK = "***"
LONG_MASK = "sk-***3456"

BASE_URL = "https://api.mem0.ai"
ORG_ID = "org-42"


def _build_params(api_key: str) -> dict[str, str]:
    return {
        "plugin.name": "mem0",
        "plugin.api_key": api_key,
        "plugin.base_url": BASE_URL,
        "plugin.org_id": ORG_ID,
    }


def _assert_no_plaintext(payload: object, secrets: tuple[str, ...]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for secret in secrets:
        assert secret not in text, f"plaintext secret leaked in response: {secret!r}"


def _assert_provider_masked(provider: dict, expected_mask: str) -> None:
    params = provider["params"]
    assert params["plugin.api_key"] == expected_mask, (
        f"plugin.api_key should be masked as {expected_mask!r}, "
        f"got {params['plugin.api_key']!r}"
    )
    assert params["plugin.base_url"] == BASE_URL, (
        f"non-secret base_url was altered: {params['plugin.base_url']!r}"
    )
    assert params["plugin.org_id"] == ORG_ID, (
        f"non-secret org_id was altered: {params['plugin.org_id']!r}"
    )
    assert params["plugin.name"] == "mem0"


@pytest.mark.asyncio
@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D5")
async def test_external_provider_secret_masking(tenant_a_admin) -> None:
    suffix = uuid.uuid4().hex[:8]
    created: list[int] = []

    async with owned_provider_client(tenant_a_admin) as api:
        try:
            for label, secret, mask in (
                ("short", SHORT_SECRET, SHORT_MASK),
                ("long", LONG_SECRET, LONG_MASK),
            ):
                response = await api.post(
                    "/memory/providers",
                    json={
                        "provider_name": f"sec-mask-{label}-{suffix}",
                        "connection_type": "plugin",
                        "enabled": False,
                        "timeout_seconds": 30,
                        "params": _build_params(secret),
                    },
                )
                assert_status(response, 200)
                body = response.json()
                created.append(body["provider_config_id"])
                _assert_no_plaintext(body, (SHORT_SECRET, LONG_SECRET))
                _assert_provider_masked(body, mask)

            short_id, long_id = created

            list_response = await api.get("/memory/providers")
            assert_status(list_response, 200)
            list_body = list_response.json()
            _assert_no_plaintext(list_body, (SHORT_SECRET, LONG_SECRET))
            items = {p["provider_config_id"]: p for p in list_body["items"]}
            _assert_provider_masked(items[short_id], SHORT_MASK)
            _assert_provider_masked(items[long_id], LONG_MASK)

            get_short = await api.get(f"/memory/providers/{short_id}")
            assert_status(get_short, 200)
            _assert_no_plaintext(get_short.json(), (SHORT_SECRET, LONG_SECRET))
            _assert_provider_masked(get_short.json(), SHORT_MASK)

            get_long = await api.get(f"/memory/providers/{long_id}")
            assert_status(get_long, 200)
            _assert_no_plaintext(get_long.json(), (SHORT_SECRET, LONG_SECRET))
            _assert_provider_masked(get_long.json(), LONG_MASK)

            update_response = await api.put(
                f"/memory/providers/{long_id}",
                json={"enabled": True},
            )
            assert_status(update_response, 200)
            update_body = update_response.json()
            _assert_no_plaintext(update_body, (SHORT_SECRET, LONG_SECRET))
            _assert_provider_masked(update_body, LONG_MASK)
            assert update_body["enabled"] is True
        finally:
            for provider_id in created:
                try:
                    cleanup = await api.delete(f"/memory/providers/{provider_id}")
                    assert_status(cleanup, (200, 400, 404))
                except Exception:
                    pass
