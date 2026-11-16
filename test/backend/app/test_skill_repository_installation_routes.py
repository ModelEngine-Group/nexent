# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill repository removal routes preserve scope and domain failure responses."""

import pytest
from contracts.errors.exceptions import (
    ForbiddenError,
    SkillException,
    UnauthorizedError,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from management.api.skill import skill_repository as api


@pytest.fixture
def client(mocker):
    mocker.patch.object(api, "get_current_user_id", return_value=("user", "tenant"))
    mocker.patch.object(api, "ensure_skill_repository_access")
    app = FastAPI()
    app.include_router(api.skill_repository_router)
    return TestClient(app)


@pytest.mark.parametrize("repository_id", [None, 42])
def test_delete_passes_only_authenticated_scope(client, mocker, repository_id):
    operation = mocker.patch("management.services.repository.skill_installations.uninstall_repository_copy")
    path = "/local/5" if repository_id is None else "/42/installations/5"
    response = client.delete("/repository/skill" + path)
    assert response.status_code == 200
    assert response.json() == {"success": True}
    operation.assert_called_once_with(repository_id, 5, "tenant", "user")
    api.ensure_skill_repository_access.assert_called_once_with("user")


@pytest.mark.parametrize("path", ["/local/5", "/42/installations/5"])
@pytest.mark.parametrize(
    "error,status",
    [
        (LookupError("missing"), 404),
        (ForbiddenError("readonly"), 403),
        (UnauthorizedError("denied"), 403),
        (ValueError("referenced"), 400),
        (SkillException("files unavailable"), 400),
    ],
)
def test_delete_maps_failures_without_reporting_success(client, mocker, path, error, status):
    mocker.patch("management.services.repository.skill_installations.uninstall_repository_copy", side_effect=error)
    response = client.delete("/repository/skill" + path)
    assert response.status_code == status
    assert response.json() == {"detail": str(error)}


def test_installation_listing_flags_reach_service(client, mocker):
    operation = mocker.patch.object(api, "list_skill_repository_listings_impl", return_value={"items": []})
    response = client.get("/repository/skill?include_installations=true&sort_by_published_time=true&tag=spreadsheet")
    assert response.status_code == 200
    assert operation.call_args.kwargs["include_installations"] is True
    assert operation.call_args.kwargs["sort_by_published_time"] is True
    assert operation.call_args.kwargs["tag"] == "spreadsheet"
