# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio

import httpx
import pytest

from management.db.identity.casdoor_roles import CasdoorRoleBinding
from management.services.permission.identity import casdoor, casdoor_roles


def test_role_mapping_requires_explicit_tenant_roles():
    assert casdoor_roles.parse_role_map('{"editor":"DEV"}') == {"editor": "DEV"}
    for invalid in ('{}', '[]', '{"owner":"SU"}', '{"other/org":"ADMIN"}', '{"":"USER"}'):
        with pytest.raises(ValueError):
            casdoor_roles.parse_role_map(invalid)


@pytest.fixture
def bound_user(monkeypatch):
    monkeypatch.setattr(casdoor.settings, "CASDOOR_ENDPOINT", "https://door.example.test")
    return CasdoorRoleBinding("local-id", "tenant", "USER", casdoor.subject_key("stable-sub"), "member")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, "ADMIN"),
        ({"roles": []}, "USER"),
        ({"roles": [{"owner": "other", "name": "admin", "isEnabled": True}]}, "USER"),
        ({"roles": [{"owner": "business", "name": "admin", "isEnabled": False}]}, "USER"),
        ({"roles": None}, None),
        ({"id": "different-user"}, None),
        ({"owner": "different-org"}, None),
    ],
)
async def test_read_role_validates_subject_and_owner(bound_user, changes, expected):
    user = {"id": "stable-sub", "owner": "business", "name": "member", "roles": [
        {"owner": "business", "name": "developer", "isEnabled": True},
        {"owner": "business", "name": "admin", "isEnabled": True},
    ], **changes}

    def respond(request):
        assert request.url.params["id"] == "business/member"
        return httpx.Response(200, json={"status": "ok", "data": user})

    async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as client:
        verified = await casdoor_roles._read_bound_user(client, "business", bound_user)
        roles = casdoor_roles.active_roles(verified["roles"], "business") if verified else None
        role = casdoor_roles.mapped_tenant_role(roles, {"admin": "ADMIN", "developer": "DEV"}) if roles is not None else None
        assert role == expected


@pytest.mark.asyncio
async def test_provider_failure_has_no_authoritative_role(bound_user):
    def unavailable(request):
        return httpx.Response(503, json={"status": "error"})

    async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(unavailable)) as client:
        assert await casdoor_roles._read_bound_user(client, "business", bound_user) is None


def test_custom_assigned_roles_do_not_need_a_mapping():
    roles = casdoor_roles.active_roles([
        {"name": "reviewer", "displayName": " Quality reviewer ", "owner": "business", "isEnabled": True},
        {"name": "analyst", "owner": "business", "isEnabled": True},
        {"name": "reviewer", "owner": "other", "isEnabled": True},
        {"name": "disabled", "owner": "business", "isEnabled": False},
        {"name": "other/admin", "owner": "business", "isEnabled": True},
    ], "business")
    assert roles == [
        {"name": "analyst", "display_name": "analyst"},
        {"name": "reviewer", "display_name": "Quality reviewer"},
    ]
    assert casdoor_roles.mapped_tenant_role(roles, {"tenant-admin": "ADMIN"}) == "USER"
    assert casdoor_roles.active_roles([None], "business") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_subject,expected", [("stable-sub", True), ("replacement", False)])
async def test_initial_assignment_is_idempotent_and_subject_bound(bound_user, provider_subject, expected):
    pending = bound_user._replace(initial_role="DEV")
    requests = []

    def respond(request):
        requests.append(request.method)
        if request.url.path.endswith("get-user"):
            data = {"id": provider_subject, "owner": "business", "name": "member"}
        else:
            data = {"owner": "business", "name": "nexent-developer", "isEnabled": True, "users": ["business/member"]}
        return httpx.Response(200, json={"status": "ok", "data": data})

    async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as client:
        assert await casdoor_roles.provision_initial_role(client, "business", {"nexent-developer": "DEV"}, pending) is expected
    assert requests == (["GET", "GET"] if expected else ["GET"])


@pytest.mark.asyncio
async def test_periodic_worker_repeats_and_closes_its_client(monkeypatch):
    settings = casdoor.settings
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "http://door.example.test")
    monkeypatch.setattr(settings, "CASDOOR_BACKEND_ENDPOINT", "")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "CASDOOR_ROLE_SYNC_ORGANIZATION", "business")
    monkeypatch.setattr(settings, "CASDOOR_ROLE_MAP_JSON", '{"editor":"DEV"}')
    monkeypatch.setattr(casdoor_roles, "_INTERVAL_SECONDS", 0.01)
    clients = []
    repeated = asyncio.Event()

    async def reconcile(client, organization, mapping, manager):
        assert organization == "business"
        assert mapping == {"editor": "DEV"}
        clients.append(client)
        if len(clients) == 2:
            repeated.set()
        return 0

    monkeypatch.setattr(casdoor_roles, "reconcile_roles", reconcile)
    async with casdoor_roles.periodic_role_sync(None):
        await asyncio.wait_for(repeated.wait(), timeout=2)
    assert clients[0] is clients[1]
    assert clients[0].is_closed
