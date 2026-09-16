from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError

from apps import tag_management_app as tag_app
from consts.exceptions import (
    TagManagementConflictError,
    TagManagementNotFoundError,
    ValidationError,
)
from consts.model import (
    TagDefinitionCreateRequest,
    TagDefinitionUpdateRequest,
    TagHTTPConflictResponse,
    TagOrderUpdateRequest,
    TagStatusUpdateRequest,
    TagValueCreateRequest,
    TagValueUpdateRequest,
)

AUTHORIZATION = "Bearer auth-token"


def install_auth(monkeypatch, *, allowed=True, tenant_id="tenant-from-auth"):
    monkeypatch.setattr(
        tag_app,
        "get_current_user_context",
        lambda authorization: ("user-from-auth", tenant_id, "ADMIN"),
    )
    monkeypatch.setattr(tag_app, "check_role_permission", lambda *args: allowed)


def definition_payload():
    return {
        "definition_id": 9,
        "bucket_id": 1,
        "definition_key": "color",
        "definition_name": "Color",
        "selection_mode": "single_select",
        "sort_order": 2,
        "status": "active",
        "active_value_count": 1,
        "value_capacity": 1000,
        "values": [],
    }


def value_payload():
    return {
        "value_id": 11,
        "display_value": "Red",
        "normalized_value": "red",
        "sort_order": 0,
        "status": "active",
    }


def test_management_permission_is_derived_from_auth_and_tenant_cannot_be_overridden(monkeypatch):
    install_auth(monkeypatch, allowed=True, tenant_id="tenant-from-auth")
    result = {"definition_id": 9}
    service = MagicMock(return_value=result)
    monkeypatch.setattr(tag_app.TagManagementService, "create_definition", service)
    request = TagDefinitionCreateRequest(
        definition_key="color",
        definition_name="Color",
        selection_mode="single_select",
        initial_values=["Red"],
    )

    assert tag_app.create_tag_definition(999, request, AUTHORIZATION) == result
    service.assert_called_once_with("tenant-from-auth", 999, request, "user-from-auth")

    install_auth(monkeypatch, allowed=False)
    with pytest.raises(HTTPException) as error:
        tag_app.list_tag_libraries(AUTHORIZATION)
    assert error.value.status_code == 403
    assert error.value.detail == "Tag library management permission is required"


def test_tag_definition_requires_at_least_one_initial_value_with_clear_message():
    with pytest.raises(
        PydanticValidationError, match="At least one tag value is required"
    ):
        TagDefinitionCreateRequest(
            definition_key="color",
            definition_name="Color",
            selection_mode="single_select",
            initial_values=[],
        )


def test_no_value_tag_definition_accepts_an_empty_value_list_and_rejects_values():
    request = TagDefinitionCreateRequest(
        definition_name="Featured",
        selection_mode="no_value",
    )
    assert request.definition_key is None
    assert request.initial_values == []

    with pytest.raises(
        PydanticValidationError,
        match="no-value tag definition cannot contain tag values",
    ):
        TagDefinitionCreateRequest(
            definition_name="Featured",
            selection_mode="no_value",
            initial_values=["ignored"],
        )


def test_create_definition_maps_not_found_validation_and_conflict_to_http_schemas(monkeypatch):
    install_auth(monkeypatch)
    request = TagDefinitionCreateRequest(
        definition_key="color", definition_name="Color", selection_mode="single_select", initial_values=["Red"]
    )

    monkeypatch.setattr(
        tag_app.TagManagementService,
        "create_definition",
        lambda *args: (_ for _ in ()).throw(TagManagementNotFoundError("Tag value not found")),
    )
    with pytest.raises(HTTPException) as not_found:
        tag_app.create_tag_definition(1, request, AUTHORIZATION)
    assert not_found.value.status_code == 404
    assert not_found.value.detail == "Tag value not found"

    monkeypatch.setattr(
        tag_app.TagManagementService,
        "create_definition",
        lambda *args: (_ for _ in ()).throw(ValidationError("invalid request")),
    )
    with pytest.raises(HTTPException) as bad_request:
        tag_app.create_tag_definition(1, request, AUTHORIZATION)
    assert bad_request.value.status_code == 400
    assert bad_request.value.detail == "invalid request"

    conflict = TagManagementConflictError(
        "Tag value capacity exceeded",
        {"limit": 1000, "current_count": 1000, "scope": "value"},
    )
    monkeypatch.setattr(
        tag_app.TagManagementService,
        "create_definition",
        lambda *args: (_ for _ in ()).throw(conflict),
    )
    with pytest.raises(HTTPException) as conflict_error:
        tag_app.create_tag_definition(1, request, AUTHORIZATION)
    assert conflict_error.value.status_code == 409
    assert conflict_error.value.detail == {
        "message": "Tag value capacity exceeded",
        "details": {"limit": 1000, "current_count": 1000, "scope": "value"},
    }
    response = TagHTTPConflictResponse.model_validate({"detail": conflict_error.value.detail})
    assert response.detail.details.limit == 1000
    assert response.detail.details.current_count == 1000
    assert response.detail.details.scope == "value"


def test_all_management_endpoints_forward_auth_tenant_and_audit_ready_responses(monkeypatch):
    install_auth(monkeypatch)
    service = tag_app.TagManagementService
    libraries = [{"bucket_id": 1, "bucket_key": "default_resource", "bucket_name": "Resources", "status": "active", "resource_types": [], "definition_count": 0, "definition_capacity": 100}]
    definition = definition_payload()
    value = value_payload()

    monkeypatch.setattr(service, "list_libraries", lambda tenant_id: libraries)
    assert tag_app.list_tag_libraries(AUTHORIZATION) == libraries

    monkeypatch.setattr(service, "list_definitions", lambda tenant_id, bucket_id: [definition])
    assert tag_app.list_tag_definitions(1, AUTHORIZATION) == [definition]

    create_definition = MagicMock(return_value=definition)
    monkeypatch.setattr(service, "create_definition", create_definition)
    create_request = TagDefinitionCreateRequest(
        definition_key="color", definition_name="Color", selection_mode="single_select", initial_values=["Red"]
    )
    assert tag_app.create_tag_definition(1, create_request, AUTHORIZATION) == definition
    create_definition.assert_called_once_with("tenant-from-auth", 1, create_request, "user-from-auth")

    update_definition = MagicMock(return_value=definition)
    monkeypatch.setattr(service, "update_definition", update_definition)
    update_request = TagDefinitionUpdateRequest(definition_name="New")
    assert tag_app.update_tag_definition(1, 9, update_request, AUTHORIZATION) == definition
    update_definition.assert_called_once_with("tenant-from-auth", 1, 9, update_request, "user-from-auth")

    monkeypatch.setattr(service, "set_definition_status", lambda *args: definition | {"status": "disabled"})
    assert tag_app.update_tag_definition_status(1, 9, TagStatusUpdateRequest(status="disabled"), AUTHORIZATION)["status"] == "disabled"
    monkeypatch.setattr(service, "set_definition_order", lambda *args: definition | {"sort_order": 8})
    assert tag_app.update_tag_definition_order(1, 9, TagOrderUpdateRequest(sort_order=8), AUTHORIZATION)["sort_order"] == 8
    move_definition_to_top = MagicMock(return_value=definition | {"sort_order": 0})
    monkeypatch.setattr(service, "move_definition_to_top", move_definition_to_top)
    assert tag_app.move_tag_definition_to_top(1, 9, AUTHORIZATION)["sort_order"] == 0
    move_definition_to_top.assert_called_once_with("tenant-from-auth", 1, 9, "user-from-auth")
    monkeypatch.setattr(service, "get_definition_usage", lambda *args: {"definition_id": 9, "active_value_count": 1, "active_usage_count": 0, "value_capacity": 1000})
    assert tag_app.get_tag_definition_usage(1, 9, AUTHORIZATION)["definition_id"] == 9
    monkeypatch.setattr(service, "delete_definition", lambda *args: None)
    assert tag_app.delete_tag_definition(1, 9, AUTHORIZATION) == {"success": True}

    create_value = MagicMock(return_value=value)
    monkeypatch.setattr(service, "create_value", create_value)
    value_request = TagValueCreateRequest(display_value="Red", sort_order=0)
    assert tag_app.create_tag_value(1, 9, value_request, AUTHORIZATION) == value
    create_value.assert_called_once_with("tenant-from-auth", 1, 9, value_request, "user-from-auth")

    update_value = MagicMock(return_value=value)
    monkeypatch.setattr(service, "update_value", update_value)
    value_update_request = TagValueUpdateRequest(display_value="Blue")
    assert tag_app.update_tag_value(1, 9, 11, value_update_request, AUTHORIZATION) == value
    update_value.assert_called_once_with("tenant-from-auth", 1, 9, 11, value_update_request, "user-from-auth")

    monkeypatch.setattr(service, "set_value_status", lambda *args: value | {"status": "disabled"})
    assert tag_app.update_tag_value_status(1, 9, 11, TagStatusUpdateRequest(status="disabled"), AUTHORIZATION)["status"] == "disabled"
    monkeypatch.setattr(service, "set_value_order", lambda *args: value | {"sort_order": 7})
    assert tag_app.update_tag_value_order(1, 9, 11, TagOrderUpdateRequest(sort_order=7), AUTHORIZATION)["sort_order"] == 7
    monkeypatch.setattr(service, "get_value_usage", lambda *args: {"value_id": 11, "active_usage_count": 0})
    assert tag_app.get_tag_value_usage(1, 9, 11, AUTHORIZATION)["value_id"] == 11
    monkeypatch.setattr(service, "delete_value", lambda *args: None)
    assert tag_app.delete_tag_value(1, 9, 11, AUTHORIZATION) == {"success": True}


def test_capacity_conflict_from_create_endpoint_keeps_409_wrapper_and_details(monkeypatch):
    install_auth(monkeypatch)
    conflict = TagManagementConflictError(
        "Tag definition capacity exceeded",
        {"limit": 100, "current_count": 100, "scope": "definition"},
    )
    monkeypatch.setattr(
        tag_app.TagManagementService,
        "create_definition",
        lambda *args: (_ for _ in ()).throw(conflict),
    )
    request = TagDefinitionCreateRequest(
        definition_key="color", definition_name="Color", selection_mode="single_select", initial_values=["Red"]
    )
    with pytest.raises(HTTPException) as error:
        tag_app.create_tag_definition(1, request, AUTHORIZATION)
    assert error.value.status_code == 409
    assert error.value.detail == {
        "message": "Tag definition capacity exceeded",
        "details": {"limit": 100, "current_count": 100, "scope": "definition"},
    }
