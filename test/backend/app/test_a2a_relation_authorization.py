"""HTTP errors and mutation suppression for A2A relationship writes."""

import pytest

from test.backend.app import test_a2a_client_app as legacy
from apps import a2a_client_app as app
from consts.exceptions import AgentNotFoundError, ForbiddenError


@pytest.mark.parametrize("method", ["post", "delete"])
@pytest.mark.parametrize("error, status", [(AgentNotFoundError, 404), (ForbiddenError, 403)])
def test_unauthorized_relationship_never_reaches_persistence(mocker, method, error, status):
    guard = mocker.patch.object(app, "require_external_relation_edit", side_effect=error("denied"))
    add = mocker.patch.object(app.a2a_agent_db, "add_external_agent_relation")
    remove = mocker.patch.object(app.a2a_agent_db, "remove_external_agent_relation")
    mocker.patch.object(app, "get_current_user_info", return_value=("user", "tenant", "en"))
    pair = {"local_agent_id": 1, "external_agent_id": 2}
    response = getattr(legacy.client, method)(
        "/a2a/client/relations", **({"json": pair} if method == "post" else {"params": pair}))
    assert response.status_code == status
    guard.assert_called_once_with(1, "tenant", "user")
    add.assert_not_called()
    remove.assert_not_called()


@pytest.mark.parametrize("error, status", [(AgentNotFoundError, 404), (ValueError, 409), (RuntimeError, 500)])
def test_binding_persistence_error_mapping(mocker, error, status):
    mocker.patch.object(app, "require_external_relation_edit")
    mocker.patch.object(app.a2a_agent_db, "add_external_agent_relation", side_effect=error("failed"))
    assert legacy.client.post("/a2a/client/relations", json={
        "local_agent_id": 1, "external_agent_id": 2}).status_code == status


def test_owned_relationship_success(mocker):
    mocker.patch.object(app, "require_external_relation_edit")
    result = {"id": 3, "local_agent_id": 1, "external_agent_id": 2, "is_enabled": True}
    mocker.patch.object(app.a2a_agent_db, "add_external_agent_relation", return_value=result)
    response = legacy.client.post("/a2a/client/relations", json={"local_agent_id": 1, "external_agent_id": 2})
    assert response.status_code == 200
    assert response.json() == {"status": "success", "data": result}
