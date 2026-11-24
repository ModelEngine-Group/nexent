# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for the offline exposure snapshot generator and the emergency exclusion.

The generator is the only producer of the capability-gate section of the
Gateway snapshot; these tests pin its contract:

* deterministic route ids matching the hand-written row scheme;
* dark capabilities emit no row (404 indistinguishable from nonexistent);
* regeneration is idempotent and ``--check`` catches staleness;
* the emergency exclusion env removes rows at gateway load time and warns
  on unknown ids.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "generate_exposure_registry.py"
SNAPSHOT = REPO_ROOT / "backend" / "gateway" / "exposure" / "registry.json"

EXPECTED_ENABLED = {
    ("DELETE", "/nb/v1/conversations/{conversation_id}"): "conversations.delete",
    ("POST", "/nb/v1/conversations/batch-delete"): "conversations.batch_delete",
    ("GET", "/nb/v1/automations"): "automations.list",
    ("GET", "/nb/v1/automations/{task_id}"): "automations.detail",
    ("GET", "/nb/v1/file/download/{object_name:path}"): "file.download",
}
DARK_METHOD_PATHS = {
    ("POST", "/nb/v1/automations/{task_id}/pause"),
    ("POST", "/nb/v1/automations/{task_id}/resume"),
    ("POST", "/nb/v1/automations/{task_id}/run"),
    ("DELETE", "/nb/v1/automations/{task_id}"),
    ("GET", "/nb/v1/automations/{task_id}/runs"),
    ("POST", "/nb/v1/automations/runs/{run_id}/cancel"),
}


def _run(script_args=()):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *script_args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def _gate_rows(document):
    return [r for r in document["routes"] if "northbound_gates" in r.get("source", "")]


def test_committed_snapshot_matches_declarations():
    """--check over the committed snapshot must pass (CI contract)."""
    result = _run(("--check",))
    assert result.returncode == 0, result.stderr or result.stdout


def test_route_id_scheme_matches_legacy_rows():
    """Generated ids use the same sha256('METHOD PATH TRANSPORT')[:16] scheme."""
    import hashlib

    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    gate = _gate_rows(document)
    assert gate, "gate rows missing from snapshot"
    for row in gate:
        expected = hashlib.sha256(
            f"{row['method']} {row['path']} {row['transport']}".encode()
        ).hexdigest()[:16]
        assert row["route_id"] == f"route-{expected}"


def test_enabled_gates_present_dark_gates_absent():
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    by_key = {(r["method"], r["path"]): r for r in _gate_rows(document)}
    for (method, path), capability in EXPECTED_ENABLED.items():
        row = by_key.get((method, path))
        assert row is not None, f"enabled capability {capability} missing a snapshot row"
        assert row["capability_id"] == capability
        assert row["target"] == "management"  # real owning service
        assert row["credential_kinds"] == ["api_key"]
    for method, path in DARK_METHOD_PATHS:
        leaked = [r for r in document["routes"] if (r["method"], r["path"]) == (method, path)]
        assert not leaked, f"dark capability {method} {path} leaked into the snapshot"


def test_generator_regenerates_identically():
    """A second run must be a no-op (idempotency keeps the diff review clean)."""
    before = SNAPSHOT.read_text(encoding="utf-8")
    result = _run(())
    assert result.returncode == 0, result.stderr
    after = SNAPSHOT.read_text(encoding="utf-8")
    assert before == after


def test_legacy_northbound_rows_preserved():
    """Pre-existing northbound.py rows must survive regeneration untouched."""
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    legacy = [
        r
        for r in document["routes"]
        if r["path"].startswith("/nb/") and "northbound_gates" not in r.get("source", "")
    ]
    assert len(legacy) >= 30, f"legacy northbound rows were lost: {len(legacy)}"


def test_snapshot_loads_in_gateway_registry():
    """The generated snapshot must pass the Gateway's fail-fast loader."""
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    sys.path.insert(0, str(REPO_ROOT))
    from gateway.exposure.registry import ExposureRegistry

    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    registry = ExposureRegistry(document)
    match = registry.match("DELETE", "/nb/v1/conversations/123")
    assert match is not None and match.target == "management"
    dark = registry.match("POST", "/nb/v1/automations/7/pause")
    assert dark is None, "dark capability must not match"
    multi_segment = registry.match("GET", "/nb/v1/file/download/reports/2026/x.pdf")
    assert multi_segment is not None, "multi-segment object names must route"


def test_emergency_exclusion_removes_capability(monkeypatch):
    """GATEWAY_NB_EXCLUDED_CAPABILITIES drops rows at load time."""
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    sys.path.insert(0, str(REPO_ROOT))
    import gateway.configuration as configuration
    import gateway.exposure.registry as registry_module

    settings = configuration.load_settings(
        {**dict(GATEWAY_AUTH_ENABLED="true"), "GATEWAY_NB_EXCLUDED_CAPABILITIES": "conversations.delete"}
    )
    monkeypatch.setattr(configuration, "load_settings", lambda: settings)
    registry_module.default_registry.cache_clear()
    try:
        registry = registry_module.default_registry()
        assert registry.match("DELETE", "/nb/v1/conversations/123") is None
        assert registry.match("POST", "/nb/v1/conversations/batch-delete") is not None
    finally:
        registry_module.default_registry.cache_clear()


def test_emergency_exclusion_warns_on_unknown_id(monkeypatch, caplog):
    """An unknown id logs a warning with a spelling suggestion (fail-visible)."""
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    sys.path.insert(0, str(REPO_ROOT))
    import logging

    import gateway.configuration as configuration
    import gateway.exposure.registry as registry_module

    settings = configuration.load_settings(
        {**dict(GATEWAY_AUTH_ENABLED="true"), "GATEWAY_NB_EXCLUDED_CAPABILITIES": "conversations.delet"}
    )
    monkeypatch.setattr(configuration, "load_settings", lambda: settings)
    registry_module.default_registry.cache_clear()
    try:
        with caplog.at_level(logging.WARNING):
            registry_module.default_registry()
        assert any("matched nothing" in record.message for record in caplog.records)
        assert any("Did you mean" in record.message for record in caplog.records)
    finally:
        registry_module.default_registry.cache_clear()


def test_emergency_exclusion_by_raw_path_does_not_warn_unknown(monkeypatch, caplog):
    """Regression: gate rows may be excluded by raw path without a false warning.

    The known-identifier set must include raw paths as well as capability ids,
    otherwise a successful path-based exclusion is reported as unknown.
    """
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    sys.path.insert(0, str(REPO_ROOT))
    import logging

    import gateway.configuration as configuration
    import gateway.exposure.registry as registry_module

    settings = configuration.load_settings(
        {**dict(GATEWAY_AUTH_ENABLED="true"),
         "GATEWAY_NB_EXCLUDED_CAPABILITIES": "/nb/v1/conversations/{conversation_id}"}
    )
    monkeypatch.setattr(configuration, "load_settings", lambda: settings)
    registry_module.default_registry.cache_clear()
    try:
        with caplog.at_level(logging.WARNING):
            registry = registry_module.default_registry()
        assert registry.match("DELETE", "/nb/v1/conversations/123") is None
        assert not any("matched nothing" in record.message for record in caplog.records)
    finally:
        registry_module.default_registry.cache_clear()


@pytest.mark.asyncio
async def test_gateway_app_honors_injected_exclusion_settings():
    """create_gateway_app must apply the injected settings, not only process env."""
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    sys.path.insert(0, str(REPO_ROOT))
    import httpx

    from gateway.application import create_gateway_app
    from gateway.configuration import GatewaySettings

    seen = []

    def upstream(request):
        seen.append(request.url.path)
        return httpx.Response(200, stream=httpx.ByteStream(b'{"ok": true}'),
                              headers={"content-type": "application/json"})

    settings = GatewaySettings(jwt_secret="fixture", nb_excluded_capabilities=("conversations.delete",))
    app = create_gateway_app(settings=settings, authentication=False, transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            assert (await client.delete("/nb/v1/conversations/123")).status_code == 404
            assert (await client.post("/nb/v1/conversations/batch-delete")).status_code == 200
    assert seen == ["/nb/v1/conversations/batch-delete"]
