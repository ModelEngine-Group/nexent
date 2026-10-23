import pytest
from consts.exceptions import TagManagementNotFoundError
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import (
    AuthenticatedCaller,
    CanonicalResourceIdentity,
    ResolvedTagResource,
    ResourceCapabilities,
    ResourceType,
)


class _Registry:
    def __init__(self, resource):
        self.resource = resource
        self.references = []

    async def resolve(self, reference, caller):
        self.references.append((reference, caller))
        return self.resource


@pytest.mark.asyncio
async def test_replace_requires_existing_resource_edit_permission(monkeypatch):
    resource = ResolvedTagResource(
        found=True,
        identity=CanonicalResourceIdentity(ResourceType.SKILL, "12", "tenant-a"),
        capabilities=ResourceCapabilities(can_read=True, can_edit=False),
    )
    registry = _Registry(resource)
    monkeypatch.setattr(TagManagementService, "resource_adapter_registry", registry)
    monkeypatch.setattr(
        TagManagementService,
        "replace_resource_assignments",
        TagManagementService.replace_resource_assignments,
    )

    with pytest.raises(TagManagementNotFoundError, match="Resource not found"):
        await TagManagementService._resolve_assignment_resource(
            AuthenticatedCaller("user-a", "tenant-a", "DEV"),
            "skill",
            "12",
            require_edit=True,
        )

    reference, caller = registry.references[0]
    assert reference.resource_type == "skill"
    assert reference.resource_id == "12"
    assert caller.authenticated_tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_replace_uses_canonical_identity_and_controlled_values(monkeypatch):
    resource = ResolvedTagResource(
        found=True,
        identity=CanonicalResourceIdentity(ResourceType.SKILL, "12", "tenant-a"),
        capabilities=ResourceCapabilities(can_read=True, can_edit=True),
    )
    registry = _Registry(resource)
    calls = []
    monkeypatch.setattr(TagManagementService, "resource_adapter_registry", registry)

    def replace(tenant_id, resource_type, resource_id, library_code, value_ids, actor_id):
        calls.append(
            (tenant_id, resource_type, resource_id, library_code, value_ids, actor_id)
        )
        return []

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.replace_resource_assignments", replace
    )

    result = await TagManagementService.replace_resource_assignments(
        AuthenticatedCaller("user-a", "tenant-a", "DEV"), "skill", "12", [7, 7, 8]
    )

    assert calls == [("tenant-a", "skill", "12", "default_resource", [7, 8], "user-a")]
    assert result["assignment_count"] == 0
    assert result["resource_id"] == "12"


@pytest.mark.asyncio
async def test_legacy_flat_tags_projection_is_bounded_sorted_and_deduplicated(monkeypatch):
    resource = ResolvedTagResource(
        found=True,
        identity=CanonicalResourceIdentity(ResourceType.SKILL, "12", "tenant-a"),
        capabilities=ResourceCapabilities(can_read=True, can_edit=False),
    )
    monkeypatch.setattr(TagManagementService, "resource_adapter_registry", _Registry(resource))

    def list_assignments(tenant_id, resource_type, resource_id, library_code):
        return [
            {"display_value": "zeta"},
            {"display_value": "alpha"},
            {"display_value": "alpha"},
            {"display_value": "beta"},
        ]

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.list_resource_assignments",
        list_assignments,
    )

    result = await TagManagementService.get_legacy_flat_tags_projection(
        AuthenticatedCaller("user-a", "tenant-a", "DEV"), "skill", "12"
    )

    assert result["tags"] == ["alpha", "beta", "zeta"]
    assert result["count"] == 3
    assert result["limit"] == 100
    assert result["deprecated"] is True


@pytest.mark.asyncio
async def test_legacy_flat_tags_projection_respects_bounded_limit(monkeypatch):
    resource = ResolvedTagResource(
        found=True,
        identity=CanonicalResourceIdentity(ResourceType.TOOL, "9", "tenant-a"),
        capabilities=ResourceCapabilities(can_read=True, can_edit=False),
    )
    monkeypatch.setattr(TagManagementService, "resource_adapter_registry", _Registry(resource))

    def list_assignments(tenant_id, resource_type, resource_id, library_code):
        return [
            {"display_value": f"tag-{index}"} for index in range(5)
        ]

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.list_resource_assignments",
        list_assignments,
    )

    result = await TagManagementService.get_legacy_flat_tags_projection(
        AuthenticatedCaller("user-a", "tenant-a", "DEV"), "tool", "9", limit=2
    )

    assert result["tags"] == ["tag-0", "tag-1"]
    assert result["limit"] == 2
