import pytest
from consts.exceptions import TagManagementNotFoundError
from consts.model import TagAssignmentBulkTarget
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import (
    AuthenticatedCaller,
    CanonicalResourceIdentity,
    ResolvedTagResource,
    ResourceAdapterDependencies,
    ResourceCapabilities,
    ResourceOrigin,
    ResourceReference,
    ResourceType,
    TagResourceAdapterRegistry,
)

CALLER = AuthenticatedCaller("user-a", "tenant-a", "DEV")


class _Registry:
    def __init__(self, resolved):
        self.resolved = resolved

    async def resolve(self, reference, caller):
        return self.resolved


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case_name,resolved",
    [
        ("unknown", ResolvedTagResource.not_found()),
        ("cross_tenant", ResolvedTagResource.not_found()),
        (
            "non_editable",
            ResolvedTagResource(
                found=True,
                identity=CanonicalResourceIdentity(ResourceType.SKILL, "12", "tenant-a"),
                capabilities=ResourceCapabilities(can_read=True, can_edit=False),
            ),
        ),
    ],
)
async def test_unknown_cross_tenant_and_non_editable_resources_share_not_found_behavior(
    monkeypatch, case_name, resolved
):
    monkeypatch.setattr(TagManagementService, "resource_adapter_registry", _Registry(resolved))

    with pytest.raises(TagManagementNotFoundError, match="^Resource not found$") as error:
        await TagManagementService._resolve_assignment_resource(
            CALLER, "skill", "12", require_edit=True
        )

    assert str(error.value) == "Resource not found"


@pytest.mark.asyncio
async def test_bulk_assignment_reports_all_resolution_failures_as_not_found_or_forbidden(monkeypatch):
    resolved_by_id = {
        "unknown": ResolvedTagResource.not_found(),
        "cross-tenant": ResolvedTagResource.not_found(),
        "read-only": ResolvedTagResource(
            found=True,
            identity=CanonicalResourceIdentity(ResourceType.TOOL, "read-only", "tenant-a"),
            capabilities=ResourceCapabilities(can_read=True, can_edit=False),
        ),
    }

    class _BulkRegistry:
        async def resolve(self, reference, caller):
            return resolved_by_id[reference.resource_id]

    monkeypatch.setattr(TagManagementService, "resource_adapter_registry", _BulkRegistry())

    outcomes = await TagManagementService.replace_resource_assignments_bulk(
        CALLER,
        "tool",
        [TagAssignmentBulkTarget(resource_id=resource_id) for resource_id in resolved_by_id],
    )

    assert outcomes == [
        {"resource_id": resource_id, "outcome": "not_found_or_forbidden"}
        for resource_id in resolved_by_id
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("resource_type", [ResourceType.SKILL, ResourceType.TOOL])
@pytest.mark.parametrize("origin", [ResourceOrigin.COMMUNITY, ResourceOrigin.MARKETPLACE])
async def test_community_and_marketplace_skill_and_tool_references_are_unassignable(
    resource_type, origin
):
    registry = TagResourceAdapterRegistry(
        ResourceAdapterDependencies(
            get_skill=lambda *args: None,
            get_tools=lambda *args: [],
        )
    )

    resolved = await registry.resolve(
        ResourceReference(resource_type, "12", origin=origin), CALLER
    )

    assert resolved == ResolvedTagResource.not_found()
