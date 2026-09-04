import pytest
from consts.exceptions import (
    TagManagementConflictError,
    TagManagementNotFoundError,
    ValidationError,
)
from consts.model import TagAssignmentBulkTarget
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import AuthenticatedCaller


@pytest.mark.asyncio
async def test_bulk_assignment_returns_explicit_mixed_target_outcomes(monkeypatch):
    async def replace(cls, caller, resource_type, resource_id, value_ids):
        assert caller.authenticated_tenant_id == "tenant-a"
        assert resource_type == "skill"
        if resource_id == "missing-or-community":
            raise TagManagementNotFoundError("Resource not found")
        if resource_id == "invalid":
            raise TagManagementConflictError(
                "Resource tag assignment capacity exceeded",
                {"limit": 100, "current_count": 101, "scope": "assignment"},
            )
        return {
            "resource_type": "skill",
            "resource_id": resource_id,
            "assignment_count": len(value_ids),
            "assignment_capacity": 100,
            "assignments": [],
        }

    monkeypatch.setattr(
        TagManagementService,
        "replace_resource_assignments",
        classmethod(replace),
    )

    outcomes = await TagManagementService.replace_resource_assignments_bulk(
        AuthenticatedCaller("user-a", "tenant-a", "DEV"),
        "skill",
        [
            TagAssignmentBulkTarget(resource_id="updated", value_ids=[7]),
            TagAssignmentBulkTarget(resource_id="missing-or-community", value_ids=[8]),
            TagAssignmentBulkTarget(resource_id="invalid", value_ids=[9]),
        ],
    )

    assert outcomes == [
        {
            "resource_id": "updated",
            "outcome": "updated",
            "assignment": {
                "resource_type": "skill",
                "resource_id": "updated",
                "assignment_count": 1,
                "assignment_capacity": 100,
                "assignments": [],
            },
        },
        {
            "resource_id": "missing-or-community",
            "outcome": "not_found_or_forbidden",
        },
        {
            "resource_id": "invalid",
            "outcome": "validation",
            "message": "Resource tag assignment capacity exceeded",
            "details": {"limit": 100, "current_count": 101, "scope": "assignment"},
        },
    ]


@pytest.mark.asyncio
async def test_bulk_assignment_reports_validation_without_stopping_later_targets(monkeypatch):
    async def replace(cls, caller, resource_type, resource_id, value_ids):
        if resource_id == "invalid":
            raise ValidationError("A single-select tag definition accepts only one assigned value")
        return {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "assignment_count": 0,
            "assignment_capacity": 100,
            "assignments": [],
        }

    monkeypatch.setattr(
        TagManagementService,
        "replace_resource_assignments",
        classmethod(replace),
    )

    outcomes = await TagManagementService.replace_resource_assignments_bulk(
        AuthenticatedCaller("user-a", "tenant-a", "DEV"),
        "skill",
        [
            TagAssignmentBulkTarget(resource_id="invalid", value_ids=[7, 8]),
            TagAssignmentBulkTarget(resource_id="later", value_ids=[]),
        ],
    )

    assert [outcome["outcome"] for outcome in outcomes] == ["validation", "updated"]
