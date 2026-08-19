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


def test_detail_returns_empty_object_when_not_installed(client, market_service):
    market_service.get_market_skill_detail.return_value = {}

    response = client.get(
        "/skills/market/detail",
        params={"skill_id": "@owner/missing", "source": "modelscope"},
    )

    assert response.status_code == 200
    assert response.json() == {}
    market_service.get_market_skill_detail.assert_called_once_with(
        skill_id="@owner/missing",
        source="modelscope",
        user_id="user-a",
        tenant_id="tenant-a",
    )
    market_service.get_upstream_last_modified.assert_not_called()


def test_detail_returns_installed_skill_record(client, market_service):
    market_service.get_market_skill_detail.return_value = {
        "skill_id": 12,
        "name": "local-demo",
        "source": "modelscope",
        "unique_id": "@owner/demo",
    }
    market_service.get_upstream_last_modified.return_value = "2026-08-07T06:37:46Z"

    response = client.get(
        "/skills/market/detail",
        params={
            "skill_id": "@owner/demo",
            "source": "modelscope",
            "include_upstream_last_modified": "true",
        },
    )

    assert response.json()["skill_id"] == 12
    assert response.json()["name"] == "local-demo"
    assert response.json()["upstream_last_modified"] == "2026-08-07T06:37:46Z"
    market_service.get_upstream_last_modified.assert_called_once_with("@owner/demo")


def test_detail_skips_upstream_last_modified_by_default(client, market_service):
    market_service.get_market_skill_detail.return_value = {
        "skill_id": 12,
        "name": "local-demo",
        "source": "modelscope",
        "unique_id": "@owner/demo",
    }

    response = client.get(
        "/skills/market/detail",
        params={"skill_id": "@owner/demo", "source": "modelscope"},
    )

    assert response.status_code == 200
    assert "upstream_last_modified" not in response.json()
    market_service.get_upstream_last_modified.assert_not_called()


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
