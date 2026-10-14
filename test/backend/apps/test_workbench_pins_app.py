"""HTTP input/error mappings with controlled service boundaries."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps import workbench_pins_app as routes
from consts.exceptions import ConversationNotFoundError, TokenExpiredError, UnauthorizedError


@pytest.fixture
def client(mocker):
    mocker.patch.object(routes, "get_current_user_id", return_value=("u", "t"))
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    return TestClient(app)


def test_list_identity_and_response(client, mocker):
    get = mocker.patch.object(routes, "get_workbench_pins", return_value={"items": []})
    response = client.get("/api/conversation/workbench_pins")
    assert response.status_code == 200
    assert response.json() == {"code": 0, "message": "success", "data": {"items": []}}
    get.assert_called_once_with("u", "t")


@pytest.mark.parametrize("pinned", [True, False])
def test_save_identity_and_response(client, mocker, pinned):
    save = mocker.patch.object(routes, "update_workbench_pin", return_value={"items": []})
    response = client.put("/api/conversation/42/workbench_pin", json={"pinned": pinned})
    assert response.status_code == 200
    save.assert_called_once_with(42, pinned, "u", "t")


@pytest.mark.parametrize("id,body", [(0, {"pinned": True}), (-1, {"pinned": True}), (2147483648, {"pinned": True}), (42, {}), (42, {"pinned": 1}), (42, {"pinned": "true"}), (42, {"pinned": None})])
def test_invalid_body_never_calls_service(client, mocker, id, body):
    save = mocker.patch.object(routes, "update_workbench_pin")
    assert client.put(f"/api/conversation/{id}/workbench_pin", json=body).status_code == 422
    save.assert_not_called()


@pytest.mark.parametrize("error,status", [(ConversationNotFoundError("foreign"), 404), (UnauthorizedError("bad"), 401), (RuntimeError("secret db message"), 500)])
def test_service_errors_mapped_without_internal_leak(client, mocker, error, status):
    mocker.patch.object(routes, "update_workbench_pin", side_effect=error)
    response = client.put("/api/conversation/42/workbench_pin", json={"pinned": True})
    assert response.status_code == status
    assert "secret" not in response.text


def test_expired_authentication_does_not_call_service(client, mocker):
    mocker.patch.object(routes, "get_current_user_id", side_effect=TokenExpiredError("expired"))
    get = mocker.patch.object(routes, "get_workbench_pins")
    assert client.get("/api/conversation/workbench_pins").status_code == 401
    get.assert_not_called()
