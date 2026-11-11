# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for the manifest-driven northbound exposure mechanism.

Covers the five acceptance groups of the design (§7.5): manifest parsing and
fail-fast validation, gateway route-table matching (including the wildcard
segment-count exemption and the 404 equivalence), service-side forward and
reverse reconciliation, exclusion semantics, and the two-state envelope on
the hand-written gates.
"""

import os
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient

from contracts.authentication import AuthenticatedIdentity, CredentialKind
from management.utils.northbound_manifest import (
    ManifestEntry,
    ManifestError,
    _parse_manifest,
    reconcile_northbound_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "deploy" / "northbound.yaml"

IDENTITY = AuthenticatedIdentity("user-1", "tenant-1", kind=CredentialKind.API_KEY, token_id=42)


def load_entries():
    import yaml

    document = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    return _parse_manifest(document)


# ── Manifest parsing and validation ────────────────────────────────────────


def test_manifest_file_parses_with_expected_shape():
    entries = load_entries()
    assert len(entries) >= 40  # 26 existing REST + 5 A2A + new + dark
    ids = [entry.id for entry in entries]
    assert len(ids) == len(set(ids))
    for entry in entries:
        assert entry.upstream
        assert entry.path.startswith("/nb/")
        assert entry.methods


def test_manifest_phase_one_capabilities_are_serving():
    entries = {entry.id: entry for entry in load_entries()}
    for capability_id in (
        "conversations.delete",
        "conversations.batch_delete",
        "automations.list",
        "automations.detail",
        "file.download",
    ):
        assert entries[capability_id].enabled, capability_id


def test_manifest_dark_action_capabilities_are_declared_not_serving():
    entries = {entry.id: entry for entry in load_entries()}
    for capability_id in ("automations.pause", "automations.resume", "automations.run", "automations.delete"):
        assert not entries[capability_id].enabled, capability_id
        assert entries[capability_id].audit


def test_manifest_existing_surface_stays_serving():
    entries = {entry.id: entry for entry in load_entries()}
    # Migration rule: every pre-existing northbound endpoint is listed enabled.
    for capability_id in ("chat.run", "chat.stop", "conversations.list", "knowledge.hybrid_search", "a2a.agent_card"):
        assert entries[capability_id].enabled, capability_id


def test_parse_rejects_duplicate_capability_ids():
    raw = {"northbound": [{"id": "a.b", "upstream": "management", "path": "/nb/v1/x", "methods": ["GET"]},
                          {"id": "a.b", "upstream": "management", "path": "/nb/v1/y", "methods": ["GET"]}]}
    with pytest.raises(ManifestError, match="Duplicate capability id"):
        _parse_manifest(raw)


def test_parse_rejects_duplicate_path_and_method():
    raw = {"northbound": [{"id": "a.b", "upstream": "management", "path": "/nb/v1/x", "methods": ["GET"]},
                          {"id": "c.d", "upstream": "management", "path": "/nb/v1/x", "methods": ["GET"]}]}
    with pytest.raises(ManifestError, match="Path conflict"):
        _parse_manifest(raw)


def test_parse_rejects_invalid_structure():
    with pytest.raises(ManifestError):
        _parse_manifest({"northbound": "nope"})
    with pytest.raises(ManifestError):
        _parse_manifest({})
    with pytest.raises(ManifestError):
        _parse_manifest({"northbound": [{"id": "no-dot", "upstream": "m", "path": "/nb/v1/x", "methods": ["GET"]}]})


# ── Gateway route table ────────────────────────────────────────────────────


def gateway_table(entries=None, excluded=()):
    import yaml

    from gateway.routing import RouteTable

    if entries is None:
        document = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
        entries = document["northbound"]
    return RouteTable.from_manifest(entries, excluded=excluded)


def test_route_table_serves_the_manifested_paths():
    table = gateway_table()
    assert table.select_upstream("POST", "/nb/v1/chat/run") == "management"
    assert table.select_upstream("DELETE", "/nb/v1/conversations/123") == "management"
    assert table.select_upstream("GET", "/nb/v1/automations") == "management"
    assert table.select_upstream("GET", "/nb/v1/automations/9") == "management"
    assert table.select_upstream("GET", "/nb/v1/file/download/reports/2026/x.pdf") == "management"


def test_route_table_unlisted_path_is_404_indistinguishable():
    table = gateway_table()
    assert table.select_upstream("GET", "/nb/v1/does-not-exist") is None
    # Wrong method on a listed path is also 404.
    assert table.select_upstream("GET", "/nb/v1/chat/run") is None


def test_route_table_dark_capability_returns_none():
    table = gateway_table()
    assert table.select_upstream("POST", "/nb/v1/automations/5/pause") is None


def test_route_table_excluded_capability_returns_none():
    table = gateway_table(excluded=("conversations.delete",))
    assert table.select_upstream("DELETE", "/nb/v1/conversations/123") is None
    assert table.select_upstream("GET", "/nb/v1/conversations") == "management"


def test_route_table_wildcard_absorbs_multi_segment_object_names():
    table = gateway_table()
    assert table.select_upstream("GET", "/nb/v1/file/download/a/b/c/d.pdf") == "management"
    assert table.select_upstream("GET", "/nb/v1/file/download") is None  # needs at least one segment


def test_route_table_bans_internal_segments_and_admits_known_prefixes():
    table = gateway_table()
    assert table.select_upstream("GET", "/nb/v1/internal/identity/resolve") is None
    assert table.select_upstream("GET", "/api/whatever") == "management"
    assert table.select_upstream("POST", "/api/agent/run") == "runtime"
    assert table.select_upstream("GET", "/elsewhere") is None


def test_route_table_a2a_colon_paths_match():
    table = gateway_table()
    assert table.select_upstream("POST", "/nb/a2a/ep7/message:send") == "management"
    assert table.select_upstream("GET", "/nb/a2a/ep7/.well-known/agent-card.json") == "management"


# ── Service-side reconciliation ────────────────────────────────────────────


def build_nb_app() -> FastAPI:
    """A small app with the manifest's routes, for reconciliation tests."""
    app = FastAPI()

    @app.get("/nb/v1/health")
    def health():
        return {"status": "ok"}

    @app.delete("/nb/v1/conversations/{conversation_id}")
    def delete_conversation(conversation_id: int):
        return {"deleted": True}

    @app.get("/nb/v1/file/download/{object_name:path}")
    def download(object_name: str):
        return {"object": object_name}

    return app


def test_reconcile_passes_when_manifest_and_routes_agree(tmp_path, monkeypatch):
    manifest = tmp_path / "northbound.yaml"
    manifest.write_text(
        """
northbound:
  - id: chat.health
    upstream: management
    path: /nb/v1/health
    methods: [GET]
    auth: public
  - id: conversations.delete
    upstream: management
    path: /nb/v1/conversations/{conversation_id}
    methods: [DELETE]
    audit: true
  - id: file.download
    upstream: management
    path: /nb/v1/file/download/{object_name:path}
    methods: [GET]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NORTHBOUND_MANIFEST_PATH", str(manifest))
    entries = reconcile_northbound_manifest(build_nb_app())
    assert {entry.id for entry in entries} == {"chat.health", "conversations.delete", "file.download"}


def test_reconcile_fails_fast_on_missing_route(tmp_path, monkeypatch):
    manifest = tmp_path / "northbound.yaml"
    manifest.write_text(
        """
northbound:
  - id: chat.health
    upstream: management
    path: /nb/v1/health
    methods: [GET]
  - id: conversations.rename
    upstream: management
    path: /nb/v1/conversations/{conversation_id}/title
    methods: [PUT]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NORTHBOUND_MANIFEST_PATH", str(manifest))
    with pytest.raises(ManifestError, match="conversations.rename"):
        reconcile_northbound_manifest(build_nb_app())


def test_reconcile_fails_fast_on_unlisted_route(tmp_path, monkeypatch):
    # Reverse reconciliation: an actual /nb route missing from the manifest.
    manifest = tmp_path / "northbound.yaml"
    manifest.write_text(
        """
northbound:
  - id: chat.health
    upstream: management
    path: /nb/v1/health
    methods: [GET]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NORTHBOUND_MANIFEST_PATH", str(manifest))
    with pytest.raises(ManifestError, match="not listed in the manifest"):
        reconcile_northbound_manifest(build_nb_app())


def test_reconcile_missing_manifest_is_silent_skip(tmp_path, monkeypatch):
    monkeypatch.setenv("NORTHBOUND_MANIFEST_PATH", str(tmp_path / "absent.yaml"))
    assert reconcile_northbound_manifest(build_nb_app()) == []


def test_reconcile_checks_dark_entries_too(tmp_path, monkeypatch):
    # enabled: false still requires the gate to exist (§5.6.3 rule 4).
    manifest = tmp_path / "northbound.yaml"
    manifest.write_text(
        """
northbound:
  - id: chat.health
    upstream: management
    path: /nb/v1/health
    methods: [GET]
  - id: automations.pause
    upstream: management
    path: /nb/v1/automations/{task_id}/pause
    methods: [POST]
    audit: true
    enabled: false
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NORTHBOUND_MANIFEST_PATH", str(manifest))
    with pytest.raises(ManifestError, match="automations.pause"):
        reconcile_northbound_manifest(build_nb_app())


# ── Gate behaviour: two-state envelope and policy dependencies ─────────────


def build_gate_app() -> FastAPI:
    """A minimal app exposing one gate through the shared policy stack."""
    from management.services.permission.identity.gate_policies import (
        audit_hook,
        northbound_envelope_factory,
    )

    app = FastAPI()

    async def identity_stub(request: Request) -> AuthenticatedIdentity:
        request.state.request_id = "req-fixed"
        return IDENTITY

    app.dependency_overrides[
        __import__(
            "management.services.permission.identity.gate_policies", fromlist=["unified_identity"]
        ).unified_identity
    ] = identity_stub

    nb_router = APIRouter(prefix="/nb/v1/conversations")

    @nb_router.delete("/{conversation_id}")
    async def nb_delete_conversation(
        conversation_id: int,
        ctx: AuthenticatedIdentity = Depends(identity_stub),
        envelope=Depends(northbound_envelope_factory),
        audit=Depends(audit_hook("conversations.delete")),
    ):
        audit("success", {"conversation_id": conversation_id})
        return envelope(True)

    app.include_router(nb_router)
    return app


def test_gate_returns_the_northbound_envelope():
    app = build_gate_app()
    client = TestClient(app)
    response = client.delete("/nb/v1/conversations/123")
    assert response.status_code == 200
    body = response.json()
    assert body == {"message": "success", "data": True, "requestId": "req-fixed"}


def test_gate_404_indistinguishable_when_not_exposed():
    # A dark capability has no route at all on the app; the response must be
    # identical to an unknown path (route-level equivalence).
    app = build_gate_app()
    client = TestClient(app)
    missing = client.post("/nb/v1/automations/5/pause")
    unknown = client.post("/nb/v1/never-existed")
    assert missing.status_code == 404
    assert unknown.status_code == 404
