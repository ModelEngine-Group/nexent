# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit exposure preserves registered APIs and denies accidental publication."""

import json
from pathlib import Path

import httpx
import pytest

from gateway.application import create_gateway_app
from gateway.configuration import GatewaySettings
from gateway.exposure.registry import ExposureRegistry, default_registry
from gateway.routing import select_upstream


def document():
    return {"version": 1, "revision": "test-v1", "routes": [
        {"route_id": "models", "method": "GET", "path": "/api/models/{model_id}",
         "transport": "http", "target": "management", "credential_kinds": ["session"]}]}


@pytest.mark.parametrize("update", [
    {"method": "get"}, {"method": []}, {"target": "http://evil"}, {"path": "/api/*"},
    {"path": "/api/internal/secret"}, {"credential_kinds": []}, {"credential_kinds": [{}]},
    {"credential_kinds": ["session", "session"]}, {"transport": "tcp"},
    {"credential_kinds": ["anonymous"]}, {"credential_kinds": ["api_key"]},
    {"method": "POST", "transport": "websocket"}, {"path": "/api/{rest:path}"},
    {"upstream_url": "http://evil"},
])
def test_invalid_entries_fail_closed(update):
    data = document()
    data["routes"][0].update(update)
    with pytest.raises(ValueError):
        ExposureRegistry(data)


def test_duplicate_and_equivalent_parameter_templates_fail_closed():
    for path in ("/api/models/{model_id}", "/api/models/{other}"):
        data = document()
        data["routes"].append({**data["routes"][0], "route_id": "other", "path": path})
        with pytest.raises(ValueError):
            ExposureRegistry(data)


@pytest.mark.parametrize("update", [{"version": True}, {"revision": ""}, {"routes": []}])
def test_invalid_document_fails_at_startup(update):
    data = document()
    data.update(update)
    with pytest.raises(ValueError):
        ExposureRegistry(data)


def test_snapshot_keeps_all_original_northbound_contracts():
    baseline = json.loads((Path(__file__).parents[1] / "management/gateway_route_baseline.json").read_text())
    registry = default_registry()
    public = [row for row in baseline if "internal" not in row[1].split("/")]
    assert len(public) == 30
    for method, path, _ in public:
        route = registry.match(method, path)
        assert route and route.target == "northbound", (method, path)


@pytest.mark.parametrize("method,path,target", [
    ("GET", "/api/model/list", "management"), ("POST", "/api/users/list", "management"),
    ("POST", "/api/agent/run", "runtime"), ("GET", "/api/conversation/list", "runtime"),
    ("POST", "/api/file/storage", "runtime"), ("GET", "/api/file/storage", "management"),
    ("POST", "/nb/v1/chat/run", "northbound"), ("GET", "/nb/v1/chat/run", None),
    ("HEAD", "/api/model/list", None), ("GET", "/api/not-registered", None),
])
def test_regular_backend_and_northbound_have_explicit_targets(method, path, target):
    assert select_upstream(method, path) == target


def test_http_and_websocket_do_not_share_an_implicit_get_grant():
    assert select_upstream("GET", "/api/voice/stt/ws") is None
    assert select_upstream("GET", "/api/voice/stt/ws", transport="websocket") == "runtime"
    assert select_upstream("GET", "/api/model/list", transport="websocket") is None


@pytest.mark.parametrize("path,raw", [
    ("/api/internal/thread-capacity", None), ("/api/../models/x", None),
    ("/api//models/x", None), ("/api/models\\x", None),
    ("/api/models/x", b"/api/models/a%2fb"), ("/api/models/%2f", b"/api/models/%252f"),
])
def test_ambiguous_paths_never_match(path, raw):
    assert ExposureRegistry(document()).match("GET", path, raw_path=raw) is None


def test_literal_route_wins_over_parameter_route_independent_of_order():
    data = document()
    data["routes"].append({**data["routes"][0], "route_id": "list", "path": "/api/models/list", "target": "runtime"})
    assert ExposureRegistry(data).match("GET", "/api/models/list").target == "runtime"


def test_existing_numeric_and_name_routes_keep_deterministic_converter_priority():
    data = document()
    data["routes"].append({**data["routes"][0], "route_id": "numeric", "path": "/api/models/{id:int}"})
    registry = ExposureRegistry(data)
    assert registry.match("GET", "/api/models/12").route_id == "numeric"
    assert registry.match("GET", "/api/models/name").route_id == "models"


@pytest.mark.asyncio
async def test_denial_happens_before_credentials_upstream_and_cors(monkeypatch):
    calls = []

    async def forbidden(*args, **kwargs):
        pytest.fail("Unregistered request reached credential lookup")

    monkeypatch.setattr("gateway.application.resolve_identity", forbidden)
    app = create_gateway_app(authentication=True, transport=httpx.MockTransport(lambda request: calls.append(request)),
                             settings=GatewaySettings(jwt_secret="fixture"))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            for method, path in [("GET", "/api/not-registered"), ("GET", "/nb/v1/chat/run"),
                                 ("GET", "/api/internal/thread-capacity"), ("GET", "/api/voice/stt/ws")]:
                response = await client.request(method, path, headers={"Authorization": "Bearer forged"})
                assert response.status_code == 404
            headers = {"Origin": "https://frontend.test", "Access-Control-Request-Method": "POST"}
            assert (await client.options("/api/not-registered", headers=headers)).status_code == 404
            assert (await client.options("/api/user/signin", headers=headers)).status_code == 200
    assert calls == []


def test_registry_cannot_be_changed_by_mutating_its_input():
    data = document()
    registry = ExposureRegistry(data)
    data["routes"][0]["credential_kinds"].append("api_key")
    data["routes"].clear()
    assert registry.match("GET", "/api/models/test").credential_kinds == ("session",)
