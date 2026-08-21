from unittest.mock import MagicMock

import pytest
from apps import skill_app
from consts.exceptions import (
    ModelScopeSkillError,
    ModelScopeSkillNotFoundError,
    SkillException,
    UnauthorizedError,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(skill_app.router)
    return TestClient(app)


@pytest.fixture
def market_service(monkeypatch):
    service = MagicMock()
    monkeypatch.setattr(skill_app, "ModelScopeSkillService", lambda: service)
    monkeypatch.setattr(
        skill_app, "get_current_user_id", MagicMock(return_value=("user-a", "tenant-a"))
    )
    return service


def test_list_market_skills_passes_search_and_pagination(client, market_service):
    market_service.list_skills.return_value = {
        "items": [{"skill_id": "@owner/demo"}],
        "total_count": 1,
        "page_number": 2,
        "page_size": 8,
        "has_next": False,
    }

    response = client.get(
        "/skills/market/list?search=demo&page_number=2&page_size=8",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["skill_id"] == "@owner/demo"
    market_service.list_skills.assert_called_once_with(
        search="demo", page_number=2, page_size=8
    )


def test_list_market_skills_maps_provider_failure_to_bad_gateway(client, market_service):
    market_service.list_skills.side_effect = ModelScopeSkillError("market unavailable")

    response = client.get("/skills/market/list")

    assert response.status_code == 502
    assert response.json()["detail"] == "market unavailable"


def test_hub_detail_returns_upstream_metadata(client, market_service):
    market_service.get_skill.return_value = {
        "skill_id": "@owner/demo",
        "name": "demo",
        "description": "Hub description",
        "tags": ["demo"],
        "category": "tools",
        "downloads": 10,
        "likes": 2,
        "license": "MIT",
        "last_modified": "2026-08-07T06:37:46Z",
        "private": False,
    }

    response = client.get(
        "/skills/market/hub-detail",
        params={"unique_id": "@owner/demo"},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["skill_id"] == "@owner/demo"
    assert response.json()["name"] == "demo"
    market_service.get_skill.assert_called_once_with("@owner/demo")


def test_hub_detail_maps_not_found_to_404(client, market_service):
    market_service.get_skill.side_effect = ModelScopeSkillNotFoundError(
        "ModelScope Skill not found: @owner/missing"
    )

    response = client.get(
        "/skills/market/hub-detail",
        params={"unique_id": "@owner/missing"},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_hub_detail_maps_provider_failure_to_bad_gateway(client, market_service):
    market_service.get_skill.side_effect = ModelScopeSkillError("hub unavailable")

    response = client.get(
        "/skills/market/hub-detail",
        params={"unique_id": "@owner/demo"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "hub unavailable"


def test_hub_detail_rejects_missing_unique_id(client, market_service):
    response = client.get("/skills/market/hub-detail")

    assert response.status_code == 422
    market_service.get_skill.assert_not_called()


def test_hub_detail_requires_authentication(client, market_service, monkeypatch):
    monkeypatch.setattr(
        skill_app,
        "get_current_user_id",
        MagicMock(side_effect=UnauthorizedError("No authorization header provided")),
    )

    response = client.get(
        "/skills/market/hub-detail",
        params={"unique_id": "@owner/demo"},
    )

    assert response.status_code == 401
    market_service.get_skill.assert_not_called()


def test_detail_returns_empty_object_when_not_installed(client, market_service):
    market_service.get_market_skill_detail.return_value = {}

    response = client.get(
        "/skills/market/detail",
        params={"unique_id": "@owner/missing", "source": "modelscope"},
    )

    assert response.status_code == 200
    assert response.json() == {}
    market_service.get_market_skill_detail.assert_called_once_with(
        unique_id="@owner/missing",
        source="modelscope",
        user_id="user-a",
        tenant_id="tenant-a",
    )


def test_detail_returns_installed_skill_record(client, market_service):
    market_service.get_market_skill_detail.return_value = {
        "skill_id": 12,
        "name": "local-demo",
        "source": "modelscope",
        "unique_id": "@owner/demo",
    }

    response = client.get(
        "/skills/market/detail",
        params={"unique_id": "@owner/demo", "source": "modelscope"},
    )

    assert response.status_code == 200
    assert response.json()["skill_id"] == 12
    assert response.json()["name"] == "local-demo"
    assert "upstream_last_modified" not in response.json()


def test_detail_rejects_legacy_skill_id_query_param(client, market_service):
    response = client.get(
        "/skills/market/detail",
        params={"skill_id": "@owner/demo", "source": "modelscope"},
    )

    assert response.status_code == 422
    market_service.get_market_skill_detail.assert_not_called()


def test_detail_requires_authentication(client, market_service, monkeypatch):
    monkeypatch.setattr(
        skill_app,
        "get_current_user_id",
        MagicMock(side_effect=UnauthorizedError("Authentication required")),
    )

    response = client.get(
        "/skills/market/detail",
        params={"unique_id": "@owner/demo", "source": "modelscope"},
    )

    assert response.status_code == 401
    market_service.get_market_skill_detail.assert_not_called()


def test_modelscope_error_mapper_preserves_unknown_exception():
    error = RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected") as exc_info:
        skill_app._raise_modelscope_http_error(error)

    assert exc_info.value is error


def test_install_market_skill_uses_authenticated_identity(client, market_service):
    market_service.install_skill.return_value = {
        "skill_id": 12,
        "name": "local-demo",
        "source": "modelscope",
    }
    payload = {
        "unique_id": "@owner/demo",
        "name": " local-demo ",
        "description": "Editable description",
        "tags": [" demo "],
        "group_ids": [3],
        "ingroup_permission": "EDIT",
    }

    response = client.post("/skills/market/install", json=payload)

    assert response.status_code == 201
    market_service.install_skill.assert_called_once_with(
        skill_id="@owner/demo",
        name="local-demo",
        description="Editable description",
        tags=["demo"],
        group_ids=[3],
        ingroup_permission="EDIT",
        tenant_id="tenant-a",
        user_id="user-a",
    )


def test_install_market_skill_maps_name_conflict(client, market_service):
    market_service.install_skill.side_effect = SkillException(
        "Skill 'local-demo' already exists"
    )

    response = client.post(
        "/skills/market/install",
        json={
            "unique_id": "@owner/demo",
            "name": "local-demo",
            "description": "",
            "tags": [],
        },
    )

    assert response.status_code == 409


def test_update_market_skill_uses_authenticated_identity(client, market_service):
    market_service.update_skill.return_value = {
        "skill_id": 12,
        "name": "local-demo",
        "source": "modelscope",
    }

    response = client.post(
        "/skills/market/update",
        json={"skill_id": 12, "unique_id": "@owner/demo"},
    )

    assert response.status_code == 200
    market_service.update_skill.assert_called_once_with(
        skill_id=12,
        unique_id="@owner/demo",
        tenant_id="tenant-a",
        user_id="user-a",
    )


def test_market_rejects_invalid_pagination_before_service(client, market_service):
    response = client.get("/skills/market/list?page_size=51")

    assert response.status_code == 422
    market_service.list_skills.assert_not_called()


def test_market_requires_authentication(client, market_service, monkeypatch):
    monkeypatch.setattr(
        skill_app,
        "get_current_user_id",
        MagicMock(side_effect=UnauthorizedError("No authorization header provided")),
    )

    response = client.get("/skills/market/list")

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "service_method", "request_kwargs"),
    [
        ("GET", "/skills/market/list", "list_skills", {}),
        (
            "GET",
            "/skills/market/hub-detail",
            "get_skill",
            {"params": {"unique_id": "@owner/demo"}},
        ),
        (
            "GET",
            "/skills/market/detail",
            "get_market_skill_detail",
            {"params": {"unique_id": "@owner/demo", "source": "modelscope"}},
        ),
        (
            "POST",
            "/skills/market/install",
            "install_skill",
            {
                "json": {
                    "unique_id": "@owner/demo",
                    "name": "local-demo",
                    "description": "",
                    "tags": [],
                }
            },
        ),
        (
            "POST",
            "/skills/market/update",
            "update_skill",
            {"json": {"skill_id": 12, "unique_id": "@owner/demo"}},
        ),
    ],
)
def test_market_endpoints_map_unexpected_errors_to_500(
    client, market_service, method, path, service_method, request_kwargs
):
    getattr(market_service, service_method).side_effect = RuntimeError("unexpected")

    response = client.request(method, path, **request_kwargs)

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


def test_update_market_skill_maps_invalid_local_record_to_bad_request(
    client, market_service
):
    market_service.update_skill.side_effect = SkillException(
        "Skill unique_id does not match installed record"
    )

    response = client.post(
        "/skills/market/update",
        json={"skill_id": 12, "unique_id": "@owner/demo"},
    )

    assert response.status_code == 400
    assert "unique_id" in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/skills/market/install",
            {
                "unique_id": " ",
                "name": "local-demo",
                "description": "",
                "tags": [],
            },
        ),
        (
            "/skills/market/install",
            {
                "unique_id": "@owner/demo",
                "name": " ",
                "description": "",
                "tags": [],
            },
        ),
        (
            "/skills/market/install",
            {
                "unique_id": "@owner/demo",
                "name": "local-demo",
                "description": "",
                "tags": ["x" * 101],
            },
        ),
        (
            "/skills/market/update",
            {"skill_id": 12, "unique_id": " "},
        ),
    ],
)
def test_market_requests_reject_invalid_normalized_fields(
    client, market_service, path, payload
):
    response = client.post(path, json=payload)

    assert response.status_code == 422
    market_service.install_skill.assert_not_called()
    market_service.update_skill.assert_not_called()
