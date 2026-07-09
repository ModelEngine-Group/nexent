"""Unit tests for backend.apps.skill_repository_app module."""

import os
import sys
import types
from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)

sys.modules.setdefault("services.skill_repository_service", MagicMock())
sys.modules.setdefault("utils.auth_utils", MagicMock())

consts_model = types.ModuleType("consts.model")


class _SkillRepositoryListingCreateRequest(BaseModel):
    icon: Optional[str] = None
    downloads: Optional[int] = None
    tags: Optional[list[str]] = None
    category_id: Optional[int] = None


class _SkillRepositoryInstallRequest(BaseModel):
    target_name: Optional[str] = None


consts_model.SkillRepositoryListingCreateRequest = _SkillRepositoryListingCreateRequest
consts_model.SkillRepositoryInstallRequest = _SkillRepositoryInstallRequest
sys.modules["consts.model"] = consts_model

import consts.exceptions as exceptions_module


def _ensure_exception(name):
    exception = getattr(exceptions_module, name, None)
    if exception is None:
        exception = type(name, (Exception,), {})
        setattr(exceptions_module, name, exception)
    return exception


ForbiddenError = _ensure_exception("ForbiddenError")
SkillDuplicateError = getattr(exceptions_module, "SkillDuplicateError", None)
if SkillDuplicateError is None:
    class SkillDuplicateError(Exception):
        def __init__(self, duplicate_names):
            self.duplicate_names = duplicate_names
            super().__init__(str(duplicate_names))

    exceptions_module.SkillDuplicateError = SkillDuplicateError

from apps.skill_repository_app import skill_repository_router
import apps.skill_repository_app as app_module

app = FastAPI()
app.include_router(skill_repository_router)
client = TestClient(app)


@pytest.fixture
def mock_auth_header():
    return {"Authorization": "Bearer test_token"}


def test_list_skill_repository_listings_api_passes_filters(mocker, mock_auth_header):
    mock_get_user_id = mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mock_list = mocker.patch(
        "apps.skill_repository_app.list_skill_repository_listings_impl",
        return_value={"items": [], "pagination": {"total": 0}},
    )

    response = client.get(
        "/repository/skill?status=pending_review&skill_id=3&category_id=2"
        "&page=2&page_size=5&search=excel&sort_by_update_time=true",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_get_user_id.assert_called_once_with(mock_auth_header["Authorization"])
    mock_list.assert_called_once_with(
        "tenant-1",
        status="pending_review",
        skill_id=3,
        category_id=2,
        page=2,
        page_size=5,
        search="excel",
        sort_by_update_time=True,
    )


def test_list_my_editable_skills_api_passes_filters(mocker, mock_auth_header):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mock_list = mocker.patch(
        "apps.skill_repository_app.list_my_editable_skills_impl",
        return_value={"items": [], "counts": {}, "pagination": {"total": 0}},
    )

    response = client.get(
        "/repository/skill/mine?ownership=created&page=2&page_size=6"
        "&search=report&new_skill_padding=true",
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_list.assert_called_once_with(
        tenant_id="tenant-1",
        user_id="user-1",
        ownership="created",
        page=2,
        page_size=6,
        search="report",
        new_skill_padding=True,
    )


def test_create_skill_repository_listing_api_maps_forbidden(mocker, mock_auth_header):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch(
        "apps.skill_repository_app.create_skill_repository_listing_impl",
        side_effect=ForbiddenError("not allowed"),
    )

    response = client.post(
        "/repository/skill/11",
        json={"icon": "skill", "tags": ["tag"]},
        headers=mock_auth_header,
    )

    assert response.status_code == 403


def test_update_skill_repository_status_api_success(mocker, mock_auth_header):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mock_update = mocker.patch(
        "apps.skill_repository_app.update_skill_repository_status_impl",
        return_value={"skill_repository_id": 7, "status": "shared"},
    )

    response = client.patch(
        "/repository/skill/7/status",
        json={"status": "shared"},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    mock_update.assert_called_once_with(
        skill_repository_id=7,
        status="shared",
        user_id="user-1",
        tenant_id="tenant-1",
    )


def test_install_skill_from_repository_api_duplicate_returns_conflict(
    mocker,
    mock_auth_header,
):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch(
        "apps.skill_repository_app.install_skill_from_repository_impl",
        side_effect=SkillDuplicateError(["Skill A"]),
    )

    response = client.post(
        "/repository/skill/7/install",
        json={"target_name": "Skill A"},
        headers=mock_auth_header,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "type": "skill_duplicate",
        "duplicate_skills": ["Skill A"],
    }


def test_get_skill_repository_listing_detail_api_not_found(mocker, mock_auth_header):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch(
        "apps.skill_repository_app.get_skill_repository_listing_detail_impl",
        side_effect=ValueError("Repository listing not found"),
    )

    response = client.get("/repository/skill/404", headers=mock_auth_header)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("path", "service_name"),
    [
        ("/repository/skill", "list_skill_repository_listings_impl"),
        ("/repository/skill/mine", "list_my_editable_skills_impl"),
    ],
)
def test_list_apis_map_auth_errors(mocker, mock_auth_header, path, service_name):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        side_effect=app_module.UnauthorizedError("expired"),
    )
    service = mocker.patch(f"apps.skill_repository_app.{service_name}")

    response = client.get(path, headers=mock_auth_header)

    assert response.status_code == 401
    service.assert_not_called()


def test_list_repository_api_maps_invalid_filter(mocker, mock_auth_header):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch(
        "apps.skill_repository_app.list_skill_repository_listings_impl",
        side_effect=ValueError("invalid status"),
    )

    response = client.get(
        "/repository/skill?status=invalid",
        headers=mock_auth_header,
    )

    assert response.status_code == 400


def test_detail_api_success(mocker, mock_auth_header):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch(
        "apps.skill_repository_app.get_skill_repository_listing_detail_impl",
        return_value={"skill_repository_id": 7},
    )

    response = client.get("/repository/skill/7", headers=mock_auth_header)

    assert response.status_code == 200
    assert response.json()["skill_repository_id"] == 7


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (app_module.UnauthorizedError("expired"), 401),
        (ForbiddenError("forbidden"), 403),
        (ValueError("invalid transition"), 400),
    ],
)
def test_update_status_api_maps_errors(
    mocker,
    mock_auth_header,
    error,
    expected_status,
):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch(
        "apps.skill_repository_app.update_skill_repository_status_impl",
        side_effect=error,
    )

    response = client.patch(
        "/repository/skill/7/status",
        json={"status": "shared"},
        headers=mock_auth_header,
    )

    assert response.status_code == expected_status


def test_create_listing_api_success(mocker, mock_auth_header):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    create = mocker.patch(
        "apps.skill_repository_app.create_skill_repository_listing_impl",
        return_value={"skill_repository_id": 7},
    )

    response = client.post(
        "/repository/skill/11",
        json={"icon": "skill", "tags": ["tag"]},
        headers=mock_auth_header,
    )

    assert response.status_code == 200
    create.assert_called_once()


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (app_module.UnauthorizedError("expired"), 401),
        (ValueError("invalid payload"), 400),
    ],
)
def test_create_listing_api_maps_errors(
    mocker,
    mock_auth_header,
    error,
    expected_status,
):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch(
        "apps.skill_repository_app.create_skill_repository_listing_impl",
        side_effect=error,
    )

    response = client.post(
        "/repository/skill/11",
        json={},
        headers=mock_auth_header,
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (app_module.UnauthorizedError("expired"), 401),
        (ValueError("not found"), 404),
    ],
)
def test_install_api_maps_errors(
    mocker,
    mock_auth_header,
    error,
    expected_status,
):
    mocker.patch(
        "apps.skill_repository_app.get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch(
        "apps.skill_repository_app.install_skill_from_repository_impl",
        side_effect=error,
    )

    response = client.post(
        "/repository/skill/7/install",
        json={},
        headers=mock_auth_header,
    )

    assert response.status_code == expected_status
