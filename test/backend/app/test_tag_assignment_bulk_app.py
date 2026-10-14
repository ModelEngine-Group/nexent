import pytest
from apps import tag_management_app
from consts.model import TagAssignmentBulkReplaceRequest


@pytest.mark.asyncio
async def test_bulk_assignment_route_uses_authenticated_context_without_library_manage(
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
        lambda *args: pytest.fail("bulk assignment must not require library MANAGE"),
    )

    async def replace_bulk(caller, resource_type, targets):
        captured.update(caller=caller, resource_type=resource_type, targets=targets)
        return [
            {
                "resource_id": "1",
                "outcome": "updated",
                "assignment": {
                    "resource_type": "skill",
                    "resource_id": "1",
                    "assignment_count": 1,
                    "assignment_capacity": 100,
                    "assignments": [],
                },
            },
            {"resource_id": "2", "outcome": "not_found_or_forbidden"},
            {
                "resource_id": "3",
                "outcome": "validation",
                "message": "Resource tag assignment capacity exceeded",
                "details": {"limit": 100, "current_count": 101, "scope": "assignment"},
            },
        ]

    monkeypatch.setattr(
        tag_management_app.TagManagementService,
        "replace_resource_assignments_bulk",
        replace_bulk,
    )

    response = await tag_management_app.replace_resource_tag_assignments_bulk(
        "skill",
        TagAssignmentBulkReplaceRequest.model_validate(
            {
                "targets": [
                    {"resource_id": "1", "value_ids": [7]},
                    {"resource_id": "2", "value_ids": [8]},
                    {"resource_id": "3", "value_ids": [9]},
                ]
            }
        ),
        "Bearer token",
    )

    assert [outcome["outcome"] for outcome in response] == [
        "updated",
        "not_found_or_forbidden",
        "validation",
    ]
    assert captured["caller"].authenticated_tenant_id == "tenant-a"
    assert captured["caller"].role == "DEV"
    assert captured["resource_type"] == "skill"
    assert [target.resource_id for target in captured["targets"]] == ["1", "2", "3"]
