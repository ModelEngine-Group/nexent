# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json

import httpx
import pytest

from management.services.permission.identity import casdoor_feature_sync
from permissions import casdoor_policy


@pytest.fixture
def policy_config(monkeypatch):
    settings = casdoor_policy.settings
    monkeypatch.setattr(settings, "CASDOOR_ENDPOINT", "https://door.example.test")
    monkeypatch.setattr(settings, "CASDOOR_ROLE_SYNC_ORGANIZATION", "business")
    monkeypatch.setattr(settings, "CASDOOR_PERMISSION_MODEL", "features")
    monkeypatch.setattr(settings, "is_casdoor_role_sync_configured", lambda: True)


def test_managed_snapshot_grants_and_revokes_independent_actions(policy_config):
    source = {"auth_provider": "casdoor"}
    assert casdoor_policy.managed_grants(source, "USER", now=100) == set()
    source["casdoor_feature_grants"] = casdoor_policy.make_snapshot("USER", {"skill.repository:read"}, 100)
    assert casdoor_policy.managed_grants(source, "USER", now=110) == {"skill.repository:read"}
    assert casdoor_policy.managed_grants(source, "USER", now=200) == set()
    assert casdoor_policy.managed_grants(source, "DEV", now=110) == set()
    assert casdoor_policy.managed_grants({}, "USER", now=110) is None
    assert casdoor_policy.managed_grants(source, "SU", now=110) is None


@pytest.mark.asyncio
async def test_only_current_enabled_policy_actions_are_evaluated(policy_config):
    read = casdoor_policy.SKILL_READ
    install = casdoor_policy.SKILL_INSTALL
    rule = {
        "owner": "business", "name": "ordinary", "model": "business/features",
        "resourceType": "Custom", "resources": ["nexent"], "isEnabled": True,
        "state": "Approved", "effect": "Allow", "actions": [install, read, "unknown"],
    }
    excluded = [
        {"name": "disabled", "isEnabled": False},
        {"name": "other-org", "owner": "other"},
        {"name": "other-model", "model": "business/other"},
        {"name": "expired", "expireTime": "2020-01-01T00:00:00Z"},
        {"name": "unapproved", "state": "Pending"},
        {"name": "other-resource", "resources": ["other"]},
        {"name": "deny", "effect": "Deny"},
    ]
    valid_response = [[False, True, True, False]]

    def respond(request):
        if request.url.path == "/api/get-permissions":
            assert request.url.params["owner"] == "business"
            data = [rule, *[dict(rule, **fields) for fields in excluded]]
        else:
            assert request.url.path == "/api/batch-enforce"
            assert request.url.params["permissionId"] == "business/ordinary"
            assert json.loads(request.content) == [
                [f"business/{name}", "nexent", action]
                for name in ("first", "second") for action in (install, read)
            ]
            data = valid_response
        return httpx.Response(200, json={"status": "ok", "data": data})

    async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as client:
        policies = await casdoor_feature_sync.read_policies(client, "business")
        assert policies == [casdoor_feature_sync.Policy("business/ordinary", (("nexent", install), ("nexent", read)))]
        assert await casdoor_feature_sync.evaluate_permissions(client, "business", policies, ["first", "second"]) == [
            {read}, {install},
        ]
        valid_response[0][0] = "false"
        assert await casdoor_feature_sync.evaluate_permissions(client, "business", policies, ["first", "second"]) is None


@pytest.mark.asyncio
async def test_classified_actions_are_enforced_only_under_their_registered_resource(policy_config):
    skill_read = casdoor_policy.SKILL_READ
    model_read = "model:read"
    base = {"owner": "business", "model": "business/features", "resourceType": "Custom",
            "isEnabled": True, "state": "Approved", "effect": "Allow"}
    skill_resource = "nexent:skill-repository"
    model_resource = "nexent:model"

    def respond(request):
        if request.url.path == "/api/get-permissions":
            data = [
                dict(base, name="classified", resources=[skill_resource, model_resource],
                     actions=[skill_read, model_read, "agent:read", "unknown"]),
                dict(base, name="mismatched", resources=[model_resource], actions=[skill_read]),
                dict(base, name="catalog", model="business/catalog", resources=[skill_resource], actions=[skill_read]),
            ]
        else:
            assert request.url.path == "/api/batch-enforce"
            assert request.url.params["permissionId"] == "business/classified"
            assert json.loads(request.content) == [["business/member", model_resource, model_read],
                                                   ["business/member", skill_resource, skill_read]]
            data = [[True, False]]
        return httpx.Response(200, json={"status": "ok", "data": data})

    async with httpx.AsyncClient(base_url="https://door.example.test", transport=httpx.MockTransport(respond)) as client:
        policies = await casdoor_feature_sync.read_policies(client, "business")
        assert policies == [casdoor_feature_sync.Policy("business/classified", ((model_resource, model_read),
                                                                               (skill_resource, skill_read)))]
        assert await casdoor_feature_sync.evaluate_permissions(client, "business", policies, ["member"]) == [{model_read}]


def test_feature_snapshot_applies_to_routes_and_preserves_unrelated_permissions():
    data = {"permissions": ["model:read", "skill:create"], "accessibleRoutes": ["/models", "/chat"]}
    casdoor_policy.overlay_user_permissions(data, {casdoor_policy.SKILL_PUBLISH, "menu:models"})
    assert data["permissions"] == ["menu:models", "skill.repository:publish", "skill:create"]
    assert data["accessibleRoutes"] == ["/chat", "/resource-space", "/skill-space"]

    casdoor_policy.overlay_user_permissions(data, {"menu:models", "model:read"})
    assert "/models" in data["accessibleRoutes"]


def test_review_and_submission_grants_preserve_tenant_and_skill_ownership(monkeypatch):
    from contracts.errors.exceptions import ForbiddenError
    from services import skill_repository_service as repository

    grants = {casdoor_policy.SKILL_REVIEW, casdoor_policy.SKILL_PUBLISH}
    monkeypatch.setattr(repository, "permission_override", lambda user_id, role, action: action in grants)
    monkeypatch.setattr(repository, "_get_user_role", lambda user_id: "USER")
    repository._validate_create_listing_permission(user_id="u", skill_info={"created_by": "u"})
    with pytest.raises(ForbiddenError):
        repository._validate_create_listing_permission(user_id="u", skill_info={"created_by": "another"})
    review = {"user_role": "USER", "current_status": "pending_review", "new_status": "shared",
              "record": {"publisher_tenant_id": "t"}, "user_id": "u", "tenant_id": "t"}
    assert repository._validate_repository_status_transition(**review) is None
    with pytest.raises(ForbiddenError):
        repository._validate_repository_status_transition(**{**review, "tenant_id": "another"})
    grants.remove(casdoor_policy.SKILL_REVIEW)
    with pytest.raises(ForbiddenError):
        repository._validate_repository_status_transition(**review)
