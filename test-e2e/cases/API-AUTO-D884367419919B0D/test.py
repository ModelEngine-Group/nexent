"""D2 contract test: quota usage source-only metering and legacy aliases."""

from __future__ import annotations

import pytest

from shared.http import assert_status, client
from shared.factories.tenant import with_isolated_accounts

CASE_ID = "API-AUTO-D884367419919B0D"

GB = 1024 * 1024 * 1024

_SENSITIVE_PARTS = ("token", "password", "secret", "api_key", "apikey", "access_key", "authorization")


def _assert_no_secret_leak(payload, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = "".join(ch for ch in str(key).lower() if ch.isalnum())
            assert not any(part in normalized for part in _SENSITIVE_PARTS), (
                f"response leaks sensitive field at {path}.{key}"
            )
            _assert_no_secret_leak(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _assert_no_secret_leak(value, f"{path}[{index}]")


def _assert_usage_schema(usage: dict) -> None:
    for key in (
        "total_bytes", "total_readable", "es_physical_bytes", "es_physical_readable",
        "hard_limit_bytes", "hard_limit_readable", "available_bytes", "available_readable",
        "usage_pct", "tenant_warning_level", "warning_enabled",
        "warning_threshold_pct", "critical_threshold_pct", "kb_count", "file_count", "breakdown",
    ):
        assert key in usage, f"usage response missing field {key}"

    assert isinstance(usage["total_bytes"], int) and usage["total_bytes"] >= 0
    assert usage["total_readable"] is None or isinstance(usage["total_readable"], str)
    assert usage["es_physical_bytes"] is None or isinstance(usage["es_physical_bytes"], int)
    assert usage["es_physical_readable"] is None or isinstance(usage["es_physical_readable"], str)
    assert usage["hard_limit_bytes"] is None or isinstance(usage["hard_limit_bytes"], int)
    assert usage["hard_limit_readable"] is None or isinstance(usage["hard_limit_readable"], str)
    assert usage["available_bytes"] is None or isinstance(usage["available_bytes"], int)
    assert usage["available_readable"] is None or isinstance(usage["available_readable"], str)
    assert usage["usage_pct"] is None or isinstance(usage["usage_pct"], (int, float))
    assert usage["tenant_warning_level"] in {"normal", "warning", "critical", "blocked"}
    assert isinstance(usage["warning_enabled"], bool)
    assert isinstance(usage["warning_threshold_pct"], int)
    assert isinstance(usage["critical_threshold_pct"], int)
    assert isinstance(usage["kb_count"], int)
    assert isinstance(usage["file_count"], int)
    assert isinstance(usage["breakdown"], list)


def _assert_breakdown_schema(breakdown: list) -> None:
    for item in breakdown:
        assert isinstance(item, dict)
        assert isinstance(item.get("index_name"), str)
        assert isinstance(item.get("actual_bytes"), int) and item["actual_bytes"] >= 0
        assert item.get("actual_readable") is None or isinstance(item["actual_readable"], str)
        assert item.get("es_physical_bytes") is None or isinstance(item["es_physical_bytes"], int)
        assert item.get("es_physical_readable") is None or isinstance(item["es_physical_readable"], str)
        assert item.get("usage_pct") is None or isinstance(item["usage_pct"], (int, float))
        assert isinstance(item.get("file_count"), int)
        assert item.get("kb_warning_level") in {"normal", "warning", "critical", "exceeded"}


@pytest.mark.asyncio
@pytest.mark.stage("D2")
@pytest.mark.case_id(CASE_ID)
@with_isolated_accounts
async def test_quota_usage_source_only_contract(tenant_a_admin, tenant_a_user, tenant_b_user, super_admin):
    tenant_id = tenant_a_admin.tenant_id

    async with client("config", token=tenant_a_admin.access_token) as api:
        config_resp = await api.get(f"/tenants/{tenant_id}/quota")
    assert_status(config_resp, 200)
    config = config_resp.json()
    hard_limit_bytes = config.get("hard_limit_bytes")

    if hard_limit_bytes is None:
        async with client("config", token=tenant_a_admin.access_token) as api:
            probe = await api.get(f"/tenants/{tenant_id}/quota/usage", params={"force_refresh": "true"})
        assert_status(probe, 200)
        source_bytes = int(probe.json().get("total_bytes") or 0)
        hard_limit_gb = max(1, (source_bytes // GB) + 1)
        async with client("config", token=tenant_a_admin.access_token) as api:
            put = await api.put(f"/tenants/{tenant_id}/quota", json={"hard_limit_gb": hard_limit_gb})
        assert_status(put, 200)
        hard_limit_bytes = hard_limit_gb * GB

    assert isinstance(hard_limit_bytes, int) and hard_limit_bytes > 0

    async with client("config", token=tenant_a_admin.access_token) as api:
        usage_resp = await api.get(
            f"/tenants/{tenant_id}/quota/usage",
            params={"force_refresh": "true", "detail": "true"},
        )
    assert_status(usage_resp, 200)
    usage = usage_resp.json()
    _assert_usage_schema(usage)
    _assert_breakdown_schema(usage["breakdown"])
    _assert_no_secret_leak(usage)

    total_bytes = usage["total_bytes"]
    assert usage["hard_limit_bytes"] == hard_limit_bytes

    expected_usage_pct = round(total_bytes / hard_limit_bytes * 100, 2)
    assert usage["usage_pct"] == expected_usage_pct

    expected_available = max(0, hard_limit_bytes - total_bytes)
    assert usage["available_bytes"] == expected_available

    breakdown_source_sum = sum(item["actual_bytes"] for item in usage["breakdown"])
    assert total_bytes >= breakdown_source_sum

    for item in usage["breakdown"]:
        soft_quota = item.get("soft_quota_bytes")
        if soft_quota and soft_quota > 0:
            assert item["usage_pct"] == round(item["actual_bytes"] / soft_quota * 100, 2)
        else:
            assert item["usage_pct"] is None

    async with client("config", token=tenant_a_user.access_token) as api:
        user_usage_resp = await api.get(
            f"/tenants/{tenant_id}/quota/usage", params={"force_refresh": "true"}
        )
    assert_status(user_usage_resp, 200)
    _assert_no_secret_leak(user_usage_resp.json())

    async with client("config", token=super_admin.access_token) as api:
        kbs_resp = await api.get(
            f"/capacity/personal/users/{tenant_a_user.user_id}/kbs",
            params={"tenant_id": tenant_id},
        )
    assert_status(kbs_resp, 200)
    kbs_payload = kbs_resp.json()
    assert isinstance(kbs_payload.get("kbs"), list)
    for kb in kbs_payload["kbs"]:
        assert kb.get("source_size_bytes") == kb.get("total_size_bytes")
        assert kb.get("source_size") == kb.get("total_size")
        assert kb.get("es_physical_size_bytes") == kb.get("store_size_bytes")
        assert kb.get("es_physical_size") == kb.get("store_size")
    _assert_no_secret_leak(kbs_payload)

    async with client("config", token=super_admin.access_token) as api:
        summary_resp = await api.get("/capacity/personal/summary", params={"tenant_id": tenant_id})
    assert_status(summary_resp, 200)
    summary = summary_resp.json()
    assert isinstance(summary.get("total_bytes"), int)
    assert summary.get("total_es_physical_bytes") is None or isinstance(summary.get("total_es_physical_bytes"), int)
    _assert_no_secret_leak(summary)

    async with client("config", token=tenant_b_user.access_token) as api:
        forbidden = await api.get(f"/tenants/{tenant_id}/quota/usage", params={"force_refresh": "true"})
    assert_status(forbidden, 403)
    forbidden_body = forbidden.json()
    assert "total_bytes" not in forbidden_body and "hard_limit_bytes" not in forbidden_body

    async with client("config") as api:
        unauthorized = await api.get(f"/tenants/{tenant_id}/quota/usage")
    assert_status(unauthorized, 401)

    async with client("config", token=tenant_a_admin.access_token) as api:
        bad_param = await api.get(
            f"/tenants/{tenant_id}/quota/usage", params={"force_refresh": "notabool"}
        )
    assert_status(bad_param, 422)
