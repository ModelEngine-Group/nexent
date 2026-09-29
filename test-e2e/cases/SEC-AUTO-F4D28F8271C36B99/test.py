"""D5 security matrix for external memory provider authorization and tenant isolation."""

from __future__ import annotations

import uuid

import httpx
import pytest

from shared.config import repo_root
from shared.http import assert_status, client
from shared.factories.ownership import register_owned_http

pytestmark = [
    pytest.mark.case_id("SEC-AUTO-F4D28F8271C36B99"),
    pytest.mark.stage("D5"),
]

_SECRET = "sk-sec-auto-9f8e7d6c5b4a3928170f1e2d3c"
_PROVIDER_BASE = "/memory/providers"
_PLUGINS = "/memory/provider-plugins"
_TEST_OP_TIMEOUT = httpx.Timeout(20, connect=10)


async def _call(token, method, path, json=None, timeout=None):
    async with client("config", token=token, timeout=timeout) as api:
        return await api.request(method, path, json=json)


async def _list_plugins(token):
    resp = await _call(token, "GET", _PLUGINS)
    assert_status(resp, 200)
    return resp.json().get("items", [])


def _pick_plugin(plugins):
    plugin = next((p for p in plugins if p.get("name") == "mem0"), None)
    if plugin is None:
        plugin = next((p for p in plugins if p.get("implements")), None)
    if plugin is None:
        raise AssertionError("no memory provider plugin installed; cannot build the security matrix")
    return plugin


def _build_params(plugin, secret):
    params = {"plugin.name": plugin["name"]}
    for field in plugin.get("config_schema", []):
        if not field.get("required"):
            continue
        key = str(field.get("key", "")).strip()
        if not key:
            continue
        field_type = str(field.get("type", "")).lower()
        if field_type == "secret" or key.endswith("api_key"):
            params[f"plugin.{key}"] = secret
        elif field_type == "number":
            params[f"plugin.{key}"] = "30"
        elif field_type == "boolean":
            params[f"plugin.{key}"] = "false"
        else:
            params[f"plugin.{key}"] = f"sec-auto-{key}"
    if not any(k.endswith("api_key") for k in params):
        params["plugin.api_key"] = secret
    return params


def _assert_no_secret(resp):
    assert _SECRET not in resp.text, f"response leaked plaintext secret: {resp.text[:500]!r}"


def _test_units():
    return [{
        "event_id": "evt-sec-auto",
        "event_type": "agent",
        "unit_type": "model_output",
        "unit_content": "security probe",
    }]


def _assert_frontend_permission_keys():
    text = (repo_root() / "frontend/app/[locale]/memory/ProviderConfigCard.tsx").read_text(encoding="utf-8")
    for key in ("mem.provider:create", "mem.provider:update", "mem.provider:delete"):
        assert key in text, f"ProviderConfigCard.tsx is missing permission key {key!r}"
    assert "Can" in text, "ProviderConfigCard.tsx does not gate actions behind a <Can> guard"


@pytest.mark.asyncio
async def test_memory_provider_permission_and_idor(tenant_a_admin, tenant_a_user, tenant_b_admin):
    admin = tenant_a_admin
    user = tenant_a_user
    attacker = tenant_b_admin

    _assert_frontend_permission_keys()

    plugins = await _list_plugins(admin.access_token)
    plugin = _pick_plugin(plugins)

    params = _build_params(plugin, _SECRET)
    provider_name = f"sec-auto-{uuid.uuid4().hex[:8]}"
    create_payload = {
        "provider_name": provider_name,
        "connection_type": "plugin",
        "enabled": False,
        "timeout_seconds": 2,
        "params": params,
    }

    created = await _call(admin.access_token, "POST", _PROVIDER_BASE, json=create_payload)
    assert_status(created, 200)
    provider_id = created.json()["provider_config_id"]
    assert isinstance(provider_id, int) and provider_id > 0
    register_owned_http(admin, 'owned_memory_providers', provider_id,
                        f'{_PROVIDER_BASE}/{provider_id}')

    try:
        _assert_no_secret(created)

        got = await _call(admin.access_token, "GET", f"{_PROVIDER_BASE}/{provider_id}")
        assert_status(got, 200)
        _assert_no_secret(got)
        got_body = got.json()
        assert got_body.get("tenant_id") == admin.tenant_id, "created provider not scoped to the owning tenant"
        for value in got_body.get("params", {}).values():
            assert _SECRET not in str(value), "masked params still expose the plaintext secret"

        listed = await _call(admin.access_token, "GET", _PROVIDER_BASE)
        assert_status(listed, 200)
        assert provider_id in [item["provider_config_id"] for item in listed.json()["items"]]

        updated = await _call(admin.access_token, "PUT", f"{_PROVIDER_BASE}/{provider_id}", json={"enabled": False})
        assert_status(updated, 200)

        cross_tenant_ops = [
            ("GET", f"{_PROVIDER_BASE}/{provider_id}", None),
            ("PUT", f"{_PROVIDER_BASE}/{provider_id}", {"provider_name": "hijacked-by-tenant-b"}),
            ("POST", f"{_PROVIDER_BASE}/{provider_id}/test-search", {"query": "probe", "top_k": 3}),
            ("POST", f"{_PROVIDER_BASE}/{provider_id}/test-ingest", {"units": _test_units()}),
            ("DELETE", f"{_PROVIDER_BASE}/{provider_id}", None),
        ]
        for method, path, payload in cross_tenant_ops:
            resp = await _call(attacker.access_token, method, path, json=payload, timeout=_TEST_OP_TIMEOUT)
            assert resp.status_code in (403, 404), (
                f"cross-tenant {method} {path}: expected 403/404, got {resp.status_code}; body={resp.text[:500]!r}"
            )
            _assert_no_secret(resp)

        after = await _call(admin.access_token, "GET", f"{_PROVIDER_BASE}/{provider_id}")
        assert_status(after, 200)
        after_body = after.json()
        assert after_body.get("provider_name") == provider_name, "cross-tenant PUT tampered with tenant A's provider"
        assert after_body.get("last_error_code") is None, (
            f"cross-tenant test call wrote tenant A's last_error_code: {after_body.get('last_error_code')!r}"
        )

        unauthorized_ops = [
            ("POST", _PROVIDER_BASE, {
                "provider_name": "unpriv-create",
                "connection_type": "plugin",
                "params": {"plugin.name": plugin["name"]},
            }),
            ("GET", _PROVIDER_BASE, None),
            ("GET", f"{_PROVIDER_BASE}/{provider_id}", None),
            ("PUT", f"{_PROVIDER_BASE}/{provider_id}", {"enabled": True}),
            ("POST", f"{_PROVIDER_BASE}/{provider_id}/test-search", {"query": "probe", "top_k": 3}),
            ("POST", f"{_PROVIDER_BASE}/{provider_id}/test-ingest", {"units": _test_units()}),
            ("DELETE", f"{_PROVIDER_BASE}/{provider_id}", None),
        ]
        for method, path, payload in unauthorized_ops:
            resp = await _call(user.access_token, method, path, json=payload, timeout=_TEST_OP_TIMEOUT)
            assert resp.status_code == 403, (
                f"{method} {path} as non-MEM.PROVIDER user: expected 403, got {resp.status_code}; body={resp.text[:500]!r}"
            )
            _assert_no_secret(resp)

        for method, path, payload in [
            ("POST", f"{_PROVIDER_BASE}/{provider_id}/test-search", {"query": "probe", "top_k": 3}),
            ("POST", f"{_PROVIDER_BASE}/{provider_id}/test-ingest", {"units": _test_units()}),
        ]:
            resp = await _call(admin.access_token, method, path, json=payload, timeout=_TEST_OP_TIMEOUT)
            assert resp.status_code not in (401, 403), (
                f"authorized {method} {path} was blocked: {resp.status_code}; body={resp.text[:500]!r}"
            )
    finally:
        try:
            await _call(admin.access_token, "DELETE", f"{_PROVIDER_BASE}/{provider_id}")
        except Exception:
            pass
