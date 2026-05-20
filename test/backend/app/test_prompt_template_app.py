import importlib
import os
import sys
import types
from http import HTTPStatus

import pytest


BACKEND_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)


@pytest.fixture(autouse=True)
def _reset_prompt_template_app_modules():
    yield
    sys.modules.pop("apps.prompt_template_app", None)
    sys.modules.pop("services.prompt_template_service", None)
    sys.modules.pop("utils.auth_utils", None)


@pytest.fixture
def prompt_template_app_module(monkeypatch):
    if BACKEND_PATH not in sys.path:
        sys.path.insert(0, BACKEND_PATH)

    service_module = types.ModuleType("services.prompt_template_service")
    for name in [
        "create_prompt_template_impl",
        "delete_prompt_template_impl",
        "get_prompt_template_detail_impl",
        "list_prompt_templates_impl",
        "update_prompt_template_impl",
    ]:
        setattr(service_module, name, lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "services.prompt_template_service", service_module)

    auth_module = types.ModuleType("utils.auth_utils")
    auth_module.get_current_user_id = lambda authorization: ("user-1", "tenant-1")
    monkeypatch.setitem(sys.modules, "utils.auth_utils", auth_module)

    sys.modules.pop("apps.prompt_template_app", None)
    module = importlib.import_module("apps.prompt_template_app")
    return importlib.reload(module)


@pytest.fixture
def prompt_template_exceptions():
    if BACKEND_PATH not in sys.path:
        sys.path.insert(0, BACKEND_PATH)
    return importlib.import_module("consts.exceptions")


@pytest.fixture
def prompt_template_client(prompt_template_app_module):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(prompt_template_app_module.router)
    return TestClient(app)


@pytest.fixture
def prompt_template_payload():
    return {
        "template_name": "template-a",
        "description": "template description",
        "template_type": "agent_generate",
        "template_content_zh": {
            "duty_system_prompt": "zh-duty",
            "constraint_system_prompt": "zh-constraint",
            "few_shots_system_prompt": "zh-few-shots",
            "agent_variable_name_system_prompt": "zh-agent-name",
            "agent_display_name_system_prompt": "zh-display-name",
            "agent_description_system_prompt": "zh-description",
            "user_prompt": "zh-user",
            "agent_name_regenerate_system_prompt": "zh-regen-name-system",
            "agent_name_regenerate_user_prompt": "zh-regen-name-user",
            "agent_display_name_regenerate_system_prompt": "zh-regen-display-system",
            "agent_display_name_regenerate_user_prompt": "zh-regen-display-user",
        },
        "template_content_en": {
            "duty_system_prompt": "en-duty",
            "constraint_system_prompt": "en-constraint",
            "few_shots_system_prompt": "en-few-shots",
            "agent_variable_name_system_prompt": "en-agent-name",
            "agent_display_name_system_prompt": "en-display-name",
            "agent_description_system_prompt": "en-description",
            "user_prompt": "en-user",
            "agent_name_regenerate_system_prompt": "en-regen-name-system",
            "agent_name_regenerate_user_prompt": "en-regen-name-user",
            "agent_display_name_regenerate_system_prompt": "en-regen-display-system",
            "agent_display_name_regenerate_user_prompt": "en-regen-display-user",
        },
    }


def test_list_prompt_templates_api_success(
    mocker, prompt_template_app_module, prompt_template_client
):
    auth_mock = mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    list_mock = mocker.patch.object(
        prompt_template_app_module,
        "list_prompt_templates_impl",
        return_value=[{"template_id": 0, "template_name": "system_default"}],
    )

    response = prompt_template_client.get(
        "/prompt_templates",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == [{"template_id": 0, "template_name": "system_default"}]
    auth_mock.assert_called_once_with("Bearer token")
    list_mock.assert_called_once_with(tenant_id="tenant-1", user_id="user-1")


def test_list_prompt_templates_api_returns_internal_error_on_unexpected_exception(
    mocker, prompt_template_app_module, prompt_template_client
):
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch.object(
        prompt_template_app_module,
        "list_prompt_templates_impl",
        side_effect=Exception("db error"),
    )

    response = prompt_template_client.get("/prompt_templates")

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json()["detail"] == "Prompt template list error."


def test_get_prompt_template_api_success(
    mocker, prompt_template_app_module, prompt_template_client
):
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    detail_mock = mocker.patch.object(
        prompt_template_app_module,
        "get_prompt_template_detail_impl",
        return_value={"template_id": 1, "template_name": "template-a"},
    )

    response = prompt_template_client.get("/prompt_templates/1")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"template_id": 1, "template_name": "template-a"}
    detail_mock.assert_called_once_with(template_id=1, tenant_id="tenant-1", user_id="user-1")


@pytest.mark.parametrize(
    ("side_effect", "expected_status", "expected_detail"),
    [
        pytest.param("not_found", HTTPStatus.NOT_FOUND, "Prompt template not found", id="not-found"),
        (Exception("unexpected"), HTTPStatus.INTERNAL_SERVER_ERROR, "Prompt template detail error."),
    ],
)
def test_get_prompt_template_api_error_mapping(
    mocker,
    prompt_template_app_module,
    prompt_template_client,
    prompt_template_exceptions,
    side_effect,
    expected_status,
    expected_detail,
):
    if side_effect == "not_found":
        side_effect = prompt_template_exceptions.NotFoundException(
            "Prompt template not found"
        )
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch.object(
        prompt_template_app_module,
        "get_prompt_template_detail_impl",
        side_effect=side_effect,
    )

    response = prompt_template_client.get("/prompt_templates/3")

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


def test_create_prompt_template_api_success(
    mocker, prompt_template_app_module, prompt_template_client, prompt_template_payload
):
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    create_mock = mocker.patch.object(
        prompt_template_app_module,
        "create_prompt_template_impl",
        return_value={"template_id": 9, "template_name": "template-a"},
    )

    response = prompt_template_client.post("/prompt_templates", json=prompt_template_payload)

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"template_id": 9, "template_name": "template-a"}
    assert create_mock.call_args.kwargs["tenant_id"] == "tenant-1"
    assert create_mock.call_args.kwargs["user_id"] == "user-1"


@pytest.mark.parametrize(
    ("side_effect", "expected_status", "expected_detail"),
    [
        pytest.param("duplicate", HTTPStatus.BAD_REQUEST, "Prompt template name already exists", id="duplicate"),
        pytest.param("validation", HTTPStatus.BAD_REQUEST, "template_content_zh is required", id="validation"),
        (Exception("unexpected"), HTTPStatus.INTERNAL_SERVER_ERROR, "Prompt template create error."),
    ],
)
def test_create_prompt_template_api_error_mapping(
    mocker,
    prompt_template_app_module,
    prompt_template_client,
    prompt_template_exceptions,
    prompt_template_payload,
    side_effect,
    expected_status,
    expected_detail,
):
    if side_effect == "duplicate":
        side_effect = prompt_template_exceptions.DuplicateError(
            "Prompt template name already exists"
        )
    elif side_effect == "validation":
        side_effect = prompt_template_exceptions.ValidationError(
            "template_content_zh is required"
        )
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch.object(
        prompt_template_app_module,
        "create_prompt_template_impl",
        side_effect=side_effect,
    )

    response = prompt_template_client.post("/prompt_templates", json=prompt_template_payload)

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


def test_update_prompt_template_api_success(
    mocker, prompt_template_app_module, prompt_template_client, prompt_template_payload
):
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    update_mock = mocker.patch.object(
        prompt_template_app_module,
        "update_prompt_template_impl",
        return_value={"template_id": 4, "template_name": "template-a"},
    )

    response = prompt_template_client.put("/prompt_templates/4", json=prompt_template_payload)

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"template_id": 4, "template_name": "template-a"}
    assert update_mock.call_args.kwargs["template_id"] == 4


@pytest.mark.parametrize(
    ("side_effect", "expected_status", "expected_detail"),
    [
        pytest.param("not_found", HTTPStatus.NOT_FOUND, "Prompt template not found", id="not-found"),
        pytest.param("duplicate", HTTPStatus.BAD_REQUEST, "Prompt template name already exists", id="duplicate"),
        pytest.param("validation", HTTPStatus.BAD_REQUEST, "System default prompt template cannot be updated", id="validation"),
        (Exception("unexpected"), HTTPStatus.INTERNAL_SERVER_ERROR, "Prompt template update error."),
    ],
)
def test_update_prompt_template_api_error_mapping(
    mocker,
    prompt_template_app_module,
    prompt_template_client,
    prompt_template_exceptions,
    prompt_template_payload,
    side_effect,
    expected_status,
    expected_detail,
):
    if side_effect == "not_found":
        side_effect = prompt_template_exceptions.NotFoundException(
            "Prompt template not found"
        )
    elif side_effect == "duplicate":
        side_effect = prompt_template_exceptions.DuplicateError(
            "Prompt template name already exists"
        )
    elif side_effect == "validation":
        side_effect = prompt_template_exceptions.ValidationError(
            "System default prompt template cannot be updated"
        )
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch.object(
        prompt_template_app_module,
        "update_prompt_template_impl",
        side_effect=side_effect,
    )

    response = prompt_template_client.put("/prompt_templates/7", json=prompt_template_payload)

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


def test_delete_prompt_template_api_success(
    mocker, prompt_template_app_module, prompt_template_client
):
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    delete_mock = mocker.patch.object(
        prompt_template_app_module,
        "delete_prompt_template_impl",
        return_value={"template_id": 8, "deleted": True},
    )

    response = prompt_template_client.delete("/prompt_templates/8")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"template_id": 8, "deleted": True}
    delete_mock.assert_called_once_with(template_id=8, tenant_id="tenant-1", user_id="user-1")


@pytest.mark.parametrize(
    ("side_effect", "expected_status", "expected_detail"),
    [
        pytest.param("not_found", HTTPStatus.NOT_FOUND, "Prompt template not found", id="not-found"),
        pytest.param("validation", HTTPStatus.BAD_REQUEST, "System default prompt template cannot be deleted", id="validation"),
        (Exception("unexpected"), HTTPStatus.INTERNAL_SERVER_ERROR, "Prompt template delete error."),
    ],
)
def test_delete_prompt_template_api_error_mapping(
    mocker,
    prompt_template_app_module,
    prompt_template_client,
    prompt_template_exceptions,
    side_effect,
    expected_status,
    expected_detail,
):
    if side_effect == "not_found":
        side_effect = prompt_template_exceptions.NotFoundException(
            "Prompt template not found"
        )
    elif side_effect == "validation":
        side_effect = prompt_template_exceptions.ValidationError(
            "System default prompt template cannot be deleted"
        )
    mocker.patch.object(
        prompt_template_app_module,
        "get_current_user_id",
        return_value=("user-1", "tenant-1"),
    )
    mocker.patch.object(
        prompt_template_app_module,
        "delete_prompt_template_impl",
        side_effect=side_effect,
    )

    response = prompt_template_client.delete("/prompt_templates/11")

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail
