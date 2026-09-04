import pytest
from apps import tag_management_app
from consts.exceptions import TagManagementNotFoundError
from consts.model import (
    TagAssignmentBulkTarget,
    TagAssignmentReplaceRequest,
)
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.routing import Match


@pytest.mark.asyncio
async def test_assignment_route_uses_authenticated_context_not_library_manage_permission(
    monkeypatch,
):
    captured = {}
    monkeypatch.setattr(
        tag_management_app,
        "get_current_user_context",
        lambda authorization: ("user-a", "tenant-a", "DEV"),
    )
    monkeypatch.setattr(
        tag_management_app,
        "check_role_permission",
        lambda *args: pytest.fail("assignment route must not require library MANAGE"),
    )

    async def replace(caller, resource_type, resource_id, value_ids, **kwargs):
        captured.update(
            caller=caller,
            resource_type=resource_type,
            resource_id=resource_id,
            value_ids=value_ids,
            document_context=kwargs,
        )
        return {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "assignment_count": 1,
            "assignment_capacity": 100,
            "assignments": [],
        }

    monkeypatch.setattr(
        tag_management_app.TagManagementService, "replace_resource_assignments", replace
    )

    response = await tag_management_app.replace_resource_tag_assignments(
        "skill", "12", TagAssignmentReplaceRequest(value_ids=[7, 7]), "Bearer token"
    )

    assert response["assignment_count"] == 1
    assert captured["caller"].authenticated_tenant_id == "tenant-a"
    assert captured["caller"].role == "DEV"
    assert captured["caller"].can_edit_all is False
    assert captured["value_ids"] == [7]
    assert captured["document_context"] == {"provider": None, "knowledge_base_id": None}


def test_assignment_caller_preserves_admin_edit_capability(monkeypatch):
    monkeypatch.setattr(
        tag_management_app,
        "get_current_user_context",
        lambda authorization: ("admin-a", "tenant-a", "ADMIN"),
    )

    caller = tag_management_app._assignment_caller("Bearer token")

    assert caller.role == "ADMIN"
    assert caller.can_edit_all is True


@pytest.mark.asyncio
async def test_assignment_route_hides_missing_or_forbidden_resource(monkeypatch):
    monkeypatch.setattr(
        tag_management_app,
        "get_current_user_context",
        lambda authorization: ("user-a", "tenant-a", "USER"),
    )

    async def get_assignments(*args, **kwargs):
        raise TagManagementNotFoundError("Resource not found")

    monkeypatch.setattr(
        tag_management_app.TagManagementService,
        "get_resource_assignments",
        get_assignments,
    )

    with pytest.raises(HTTPException) as error:
        await tag_management_app.get_resource_tag_assignments(
            "skill", "12", "Bearer token"
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Resource not found"


@pytest.mark.asyncio
async def test_document_assignment_route_forwards_provider_identity(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        tag_management_app,
        "get_current_user_context",
        lambda authorization: ("user-a", "tenant-a", "DEV"),
    )

    async def replace(*args, **kwargs):
        captured.update(kwargs)
        return {
            "resource_type": "knowledge_document",
            "resource_id": "file-7",
            "assignment_count": 0,
            "assignment_capacity": 100,
            "assignments": [],
        }

    monkeypatch.setattr(
        tag_management_app.TagManagementService, "replace_resource_assignments", replace
    )

    response = await tag_management_app.replace_resource_tag_assignments(
        "knowledge_document",
        "file-7",
        TagAssignmentReplaceRequest(value_ids=[]),
        "Bearer token",
        provider="aidp",
        knowledge_base_id="kb-1",
    )

    assert response["resource_type"] == "knowledge_document"
    assert captured == {"provider": "aidp", "knowledge_base_id": "kb-1"}


def test_document_assignment_routes_accept_slash_containing_resource_ids():
    request_scope = {
        "type": "http",
        "method": "GET",
        "path": "/tag-libraries/assignments/knowledge_document/knowledge_base/file.pdf",
        "headers": [],
        "query_string": b"",
    }
    assignment_route = next(
        route
        for route in tag_management_app.router.routes
        if route.path == "/tag-libraries/assignments/{resource_type}/{resource_id:path}"
        and "GET" in route.methods
    )

    match, child_scope = assignment_route.matches(request_scope)

    assert match is Match.FULL
    assert child_scope["path_params"] == {
        "resource_type": "knowledge_document",
        "resource_id": "knowledge_base/file.pdf",
    }


@pytest.mark.asyncio
async def test_legacy_flat_tags_projection_endpoint_marks_deprecated(monkeypatch):
    monkeypatch.setattr(
        tag_management_app,
        "get_current_user_context",
        lambda authorization: ("user-a", "tenant-a", "DEV"),
    )

    async def projection(caller, resource_type, resource_id, **kwargs):
        return {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "tags": ["alpha", "beta"],
            "count": 2,
            "limit": 100,
            "deprecated": True,
        }

    monkeypatch.setattr(
        tag_management_app.TagManagementService,
        "get_legacy_flat_tags_projection",
        projection,
    )

    response = await tag_management_app.get_resource_legacy_flat_tags_projection(
        "skill", "12", "Bearer token"
    )

    assert response["deprecated"] is True
    assert response["tags"] == ["alpha", "beta"]
    assert response["count"] == 2


def test_legacy_flat_tag_fields_are_rejected_on_structured_writes():
    with pytest.raises(ValidationError) as error:
        TagAssignmentReplaceRequest.model_validate({"value_ids": [1], "tags": ["red"]})
    message = str(error.value)
    assert "Legacy flat tag fields are rejected" in message
    assert "value_ids" in message

    with pytest.raises(ValidationError) as bulk_error:
        TagAssignmentBulkTarget.model_validate(
            {"resource_id": "12", "value_ids": [1], "labels": ["red"]}
        )
    assert "Legacy flat tag fields are rejected" in str(bulk_error.value)
