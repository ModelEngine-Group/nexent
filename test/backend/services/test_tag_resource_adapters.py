import asyncio
import base64
import json
from unittest.mock import MagicMock

import pytest
from services.tag_resource_adapters import (
    AIDP_DOCUMENT_PROVIDER,
    AgentTagResourceAdapter,
    AuthenticatedCaller,
    DocumentTagResourceAdapter,
    KnowledgeBaseTagResourceAdapter,
    McpServiceTagResourceAdapter,
    ResolvedTagResource,
    ResourceAdapterDependencies,
    ResourceOrigin,
    ResourceReference,
    ResourceType,
    SkillTagResourceAdapter,
    TagResourceAdapterRegistry,
    ToolTagResourceAdapter,
    _encode_document_resource_id,
)


def caller(*, tenant_id="tenant-a", role="USER"):
    return AuthenticatedCaller(
        user_id="user-1",
        authenticated_tenant_id=tenant_id,
        role=role,
    )


def caller_with_group(group_id):
    return AuthenticatedCaller(
        user_id="user-1",
        authenticated_tenant_id="tenant-a",
        role="USER",
        group_ids=(group_id,),
    )


def resolve(registry, resource_type, resource_id, origin=ResourceOrigin.CANONICAL, *, tenant_id="tenant-a", role="USER"):
    return asyncio.run(
        registry.resolve(
            ResourceReference(resource_type, resource_id, origin),
            caller(tenant_id=tenant_id, role=role),
        )
    )


def test_unknown_and_cross_tenant_resources_return_the_same_not_found_result():
    dependencies = ResourceAdapterDependencies(
        get_skill=lambda *_args: {"skill_id": 7, "tenant_id": "tenant-other", "skill_name": "Hidden"},
        get_tools=lambda *_args: [],
    )
    registry = TagResourceAdapterRegistry(dependencies)

    unknown = resolve(registry, ResourceType.TOOL, 404)
    cross_tenant = resolve(registry, ResourceType.SKILL, 7)

    assert unknown == ResolvedTagResource.not_found()
    assert cross_tenant == ResolvedTagResource.not_found()
    assert unknown == cross_tenant


def test_tool_author_tenant_match_does_not_grant_edit_without_injected_resolver():
    tools = [{"tool_id": 12, "author": "tenant-a", "tool_name": "Tenant Tool"}]
    dependencies = ResourceAdapterDependencies(get_tools=lambda _tenant_id: tools)
    adapter = ToolTagResourceAdapter(dependencies)

    result = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.TOOL, 12),
            caller(role="RESOURCE_MANAGER"),
        )
    )

    assert result.found is True
    assert result.capabilities.can_read is True
    assert result.capabilities.can_edit is False


@pytest.mark.parametrize(
    ("role", "created_by", "expected_can_edit"),
    [
        ("ADMIN", None, True),
        ("USER", "user-1", True),
        ("USER", "another-user", False),
        ("USER", None, False),
    ],
)
def test_local_tool_default_edit_permission_is_admin_or_creator(role, created_by, expected_can_edit):
    adapter = ToolTagResourceAdapter(
        ResourceAdapterDependencies(
            get_tools=lambda _tenant_id: [
                {
                    "tool_id": 12,
                    "author": "tenant-a",
                    "created_by": created_by,
                    "tool_name": "Tenant Tool",
                }
            ]
        )
    )

    result = asyncio.run(adapter.resolve(ResourceReference(ResourceType.TOOL, 12), caller(role=role)))

    assert result.found is True
    assert result.capabilities.can_edit is expected_can_edit


def test_community_tool_is_not_found_without_listing_local_tools():
    get_tools = MagicMock()
    adapter = ToolTagResourceAdapter(ResourceAdapterDependencies(get_tools=get_tools))

    result = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.TOOL, 12, ResourceOrigin.COMMUNITY),
            caller(role="ADMIN"),
        )
    )

    assert result == ResolvedTagResource.not_found()
    get_tools.assert_not_called()


def test_injected_tool_edit_resolver_is_required_for_can_edit():
    resolver = MagicMock(return_value=True)
    dependencies = ResourceAdapterDependencies(
        get_tools=lambda _tenant_id: [{"tool_id": 12, "author": "tenant-a", "tool_name": "Tenant Tool"}],
        resolve_tool_edit_permission=resolver,
    )
    adapter = ToolTagResourceAdapter(dependencies)

    result = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.TOOL, 12),
            caller(role="RESOURCE_MANAGER"),
        )
    )

    assert result.capabilities.can_edit is True
    resolver.assert_called_once()
    assert resolver.call_args.args[0]["author"] == "tenant-a"


def test_mcp_marketplace_resolves_local_source_and_uses_bare_string_source_id():
    get_market = MagicMock(
        return_value={"market_id": 99, "tenant_id": "tenant-a", "source_mcp_id": 42}
    )
    get_local = MagicMock(
        return_value={"mcp_id": 42, "tenant_id": "tenant-a", "mcp_name": "Local MCP"}
    )
    list_local = MagicMock(
        return_value=[{"mcp_id": 42, "permission": "READ", "mcp_name": "Local MCP"}]
    )
    dependencies = ResourceAdapterDependencies(
        get_market_mcp=get_market,
        get_local_mcp=get_local,
        list_local_mcps=list_local,
    )
    adapter = McpServiceTagResourceAdapter(dependencies)

    result = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.MCP_SERVICE, 99, ResourceOrigin.MARKETPLACE),
            caller(),
        )
    )

    assert result.found is True
    assert result.identity.resource_id == "42"
    assert result.identity.publisher_tenant_id == "tenant-a"
    get_market.assert_called_once_with(99)
    get_local.assert_called_once_with(42, "tenant-a")
    list_local.assert_called_once_with(
        tenant_id="tenant-a",
        user_id="user-1",
        is_need_auth=False,
    )


def test_mcp_community_reference_resolves_the_publisher_source():
    get_market = MagicMock(return_value={"tenant_id": "tenant-a", "source_mcp_id": "12"})
    get_local = MagicMock(return_value={"tenant_id": "tenant-a", "mcp_name": "Publisher MCP"})
    list_local = MagicMock(return_value=[{"mcp_id": 12, "permission": "EDIT"}])
    dependencies = ResourceAdapterDependencies(
        get_market_mcp=get_market,
        get_local_mcp=get_local,
        list_local_mcps=list_local,
    )
    adapter = McpServiceTagResourceAdapter(dependencies)

    result = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.MCP_SERVICE, 99, ResourceOrigin.COMMUNITY),
            caller(),
        )
    )

    assert result.found is True
    assert result.identity is not None
    assert result.identity.resource_id == "12"
    assert result.identity.publisher_tenant_id == "tenant-a"
    assert result.capabilities.can_edit is True
    get_market.assert_called_once_with(99)
    get_local.assert_called_once_with(12, "tenant-a")
    list_local.assert_called_once_with(tenant_id="tenant-a", user_id="user-1", is_need_auth=False)


def test_agent_marketplace_uses_publisher_tenant_and_resource_manager_role_is_not_edit():
    get_repository = MagicMock(
        return_value={
            "agent_id": 21,
            "publisher_tenant_id": "tenant-a",
        }
    )
    get_agent = MagicMock(
        return_value={
            "agent_id": 21,
            "tenant_id": "tenant-a",
            "created_by": "another-user",
            "display_name": "Published Agent",
        }
    )
    resolve_permission = MagicMock(return_value="READ")
    dependencies = ResourceAdapterDependencies(
        get_agent=get_agent,
        get_agent_repository=get_repository,
        resolve_agent_permission=resolve_permission,
    )
    registry = TagResourceAdapterRegistry(dependencies)

    result = resolve(
        registry,
        ResourceType.AGENT,
        99,
        ResourceOrigin.MARKETPLACE,
        role="RESOURCE_MANAGER",
    )

    assert result.found is True
    assert result.identity.resource_id == "21"
    assert result.identity.publisher_tenant_id == "tenant-a"
    assert result.capabilities.can_edit is False
    get_repository.assert_called_once_with(99, "tenant-a")
    get_agent.assert_called_once_with(21, "tenant-a")
    resolve_permission.assert_called_once_with(
        "RESOURCE_MANAGER",
        get_agent.return_value,
        "user-1",
        False,
    )


def document_reference(
    *,
    resource_id="doc-7",
    origin=ResourceOrigin.CANONICAL,
    provider="aidp",
    knowledge_base_id="kb-1",
):
    return ResourceReference(
        ResourceType.KNOWLEDGE_DOCUMENT,
        resource_id,
        origin,
        provider=provider,
        knowledge_base_id=knowledge_base_id,
    )


def document_dependencies(**overrides):
    defaults = {
        "resolve_document": lambda **_kwargs: {
            "tenant_id": "tenant-a",
            "provider": "aidp",
            "knowledge_base_id": "kb-1",
            "provider_document_id": "doc-7",
        },
        "get_document_knowledge_base": lambda **_kwargs: {"tenant_id": "tenant-a"},
        "resolve_document_permission": lambda **_kwargs: "EDIT",
        "require_document_edit_permission": lambda **_kwargs: None,
    }
    defaults.update(overrides)
    return ResourceAdapterDependencies(**defaults)


@pytest.mark.parametrize(
    ("reference", "dependencies"),
    [
        (document_reference(origin=ResourceOrigin.MARKETPLACE), ResourceAdapterDependencies()),
        (document_reference(provider=""), ResourceAdapterDependencies()),
        (document_reference(knowledge_base_id=""), ResourceAdapterDependencies()),
        (document_reference(resource_id=""), ResourceAdapterDependencies()),
    ],
)
def test_document_requires_a_canonical_reference_with_all_explicit_identity_parts(reference, dependencies):
    resolver = MagicMock()
    dependencies.resolve_document = resolver
    adapter = DocumentTagResourceAdapter(dependencies)

    result = asyncio.run(adapter.resolve(reference, caller()))

    assert result == ResolvedTagResource.not_found()
    resolver.assert_not_called()


def test_document_without_a_tenant_scoped_parent_is_not_found():
    get_parent = MagicMock(return_value=None)
    resolver = MagicMock()
    adapter = DocumentTagResourceAdapter(
        document_dependencies(get_document_knowledge_base=get_parent, resolve_document=resolver)
    )

    result = asyncio.run(adapter.resolve(document_reference(), caller()))

    assert result == ResolvedTagResource.not_found()
    resolver.assert_not_called()
    get_parent.assert_called_once_with(provider="aidp", knowledge_base_id="kb-1", tenant_id="tenant-a")


def test_document_resource_id_is_reversible_and_avoids_delimiter_collisions():
    first = _encode_document_resource_id("aidp:archive", "kb-1", "doc-7")
    second = _encode_document_resource_id("aidp", "archive:kb-1", "doc-7")

    assert first != second
    assert json.loads(base64.urlsafe_b64decode(first).decode("utf-8")) == [
        "aidp:archive",
        "kb-1",
        "doc-7",
    ]
    assert json.loads(base64.urlsafe_b64decode(second).decode("utf-8")) == [
        "aidp",
        "archive:kb-1",
        "doc-7",
    ]


@pytest.mark.parametrize(
    "document",
    [
        {"tenant_id": "tenant-other", "provider": "aidp", "knowledge_base_id": "kb-1", "provider_document_id": "doc-7"},
        {"tenant_id": "tenant-a", "provider": "other", "knowledge_base_id": "kb-1", "provider_document_id": "doc-7"},
        {"tenant_id": "tenant-a", "provider": "aidp", "knowledge_base_id": "other", "provider_document_id": "doc-7"},
        {"tenant_id": "tenant-a", "provider": "aidp", "knowledge_base_id": "kb-1", "provider_document_id": "other"},
    ],
)
def test_document_source_must_prove_the_exact_tenant_scoped_identity(document):
    resolver = MagicMock(return_value=document)
    adapter = DocumentTagResourceAdapter(
        document_dependencies(
            resolve_document=resolver,
        )
    )

    result = asyncio.run(adapter.resolve(document_reference(), caller()))

    assert result == ResolvedTagResource.not_found()
    resolver.assert_called_once_with(
        provider="aidp",
        knowledge_base_id="kb-1",
        provider_document_id="doc-7",
        tenant_id="tenant-a",
    )


def test_document_source_lookup_failure_is_not_found():
    adapter = DocumentTagResourceAdapter(
        document_dependencies(resolve_document=MagicMock(side_effect=LookupError))
    )

    result = asyncio.run(adapter.resolve(document_reference(), caller()))

    assert result == ResolvedTagResource.not_found()


def test_document_requires_a_tenant_scoped_parent_knowledge_base():
    resolver = MagicMock(
        return_value={
            "tenant_id": "tenant-a",
            "provider": "aidp",
            "knowledge_base_id": "kb-1",
            "provider_document_id": "doc-7",
        }
    )
    resolve_permission = MagicMock()
    adapter = DocumentTagResourceAdapter(
        document_dependencies(
            resolve_document=resolver,
            get_document_knowledge_base=MagicMock(return_value={"tenant_id": "tenant-other"}),
            resolve_document_permission=resolve_permission,
        )
    )

    result = asyncio.run(adapter.resolve(document_reference(), caller()))

    assert result == ResolvedTagResource.not_found()
    resolve_permission.assert_not_called()


def test_document_read_permission_error_is_not_found():
    adapter = DocumentTagResourceAdapter(
        document_dependencies(
            resolve_document=lambda **_kwargs: {
                "tenant_id": "tenant-a",
                "provider": "aidp",
                "knowledge_base_id": "kb-1",
                "provider_document_id": "doc-7",
            },
            resolve_document_permission=MagicMock(side_effect=ValueError),
        )
    )

    result = asyncio.run(adapter.resolve(document_reference(), caller()))

    assert result == ResolvedTagResource.not_found()


def test_document_inherits_read_only_parent_knowledge_base_permission():
    require_edit = MagicMock(side_effect=PermissionError)
    adapter = DocumentTagResourceAdapter(
        document_dependencies(
            resolve_document=lambda **_kwargs: {
                "tenant_id": "tenant-a",
                "provider": "aidp",
                "knowledge_base_id": "kb-1",
                "provider_document_id": "doc-7",
                "file_name": "source.pdf",
            },
            resolve_document_permission=lambda **_kwargs: "READ_ONLY",
            require_document_edit_permission=require_edit,
        )
    )

    result = asyncio.run(adapter.resolve(document_reference(), caller()))

    assert result.found is True
    assert result.capabilities.can_read is True
    assert result.capabilities.can_edit is False
    require_edit.assert_called_once_with(
        provider="aidp", knowledge_base_id="kb-1", user_id="user-1", tenant_id="tenant-a"
    )


def test_document_resolves_only_after_source_and_parent_edit_permission_are_proven():
    resolver = MagicMock(
        return_value={
            "tenant_id": "tenant-a",
            "provider": "aidp",
            "knowledge_base_id": "kb-1",
            "provider_document_id": "doc-7",
            "document_name": "Source document",
        }
    )
    require_edit = MagicMock(return_value="EDIT")
    adapter = DocumentTagResourceAdapter(
        document_dependencies(
            resolve_document=resolver,
            resolve_document_permission=lambda **_kwargs: "EDIT",
            require_document_edit_permission=require_edit,
        )
    )

    result = asyncio.run(adapter.resolve(document_reference(), caller()))

    assert result.found is True
    assert result.display.name == "Source document"
    assert result.capabilities.can_read is True
    assert result.capabilities.can_edit is True
    assert result.identity.tenant_id == "tenant-a"
    assert result.identity.resource_type is ResourceType.KNOWLEDGE_DOCUMENT
    assert result.identity.library_code == "knowledge_content"
    assert result.identity.provider == "aidp"
    assert result.identity.knowledge_base_id == "kb-1"
    assert result.identity.provider_document_id == "doc-7"
    assert json.loads(base64.urlsafe_b64decode(result.identity.resource_id).decode("utf-8")) == [
        "aidp",
        "kb-1",
        "doc-7",
    ]
    assert result.identity.key == f"knowledge_document:{result.identity.resource_id}"
    require_edit.assert_called_once_with(
        provider="aidp", knowledge_base_id="kb-1", user_id="user-1", tenant_id="tenant-a"
    )


def test_local_document_uses_path_or_url_with_its_provider_scoped_parent():
    resolver = MagicMock(
        return_value={
            "tenant_id": "tenant-a",
            "provider": "local",
            "knowledge_base_id": "local-index",
            "provider_document_id": "knowledge_base/manual.pdf",
            "file_name": "manual.pdf",
        }
    )
    get_parent = MagicMock(return_value={"tenant_id": "tenant-a"})
    adapter = DocumentTagResourceAdapter(
        document_dependencies(
            resolve_document=resolver,
            get_document_knowledge_base=get_parent,
        )
    )

    result = asyncio.run(
        adapter.resolve(
            document_reference(
                resource_id="knowledge_base/manual.pdf",
                provider="local",
                knowledge_base_id="local-index",
            ),
            caller(),
        )
    )

    assert result.found is True
    assert result.identity.provider == "local"
    assert result.identity.provider_document_id == "knowledge_base/manual.pdf"
    get_parent.assert_called_once_with(
        provider="local", knowledge_base_id="local-index", tenant_id="tenant-a"
    )
    resolver.assert_called_once_with(
        provider="local",
        knowledge_base_id="local-index",
        provider_document_id="knowledge_base/manual.pdf",
        tenant_id="tenant-a",
    )

# ---------- pure helpers ----------

def test_tenant_matches_requires_explicit_match():
    from services.tag_resource_adapters import _tenant_matches

    assert _tenant_matches({"tenant_id": "tenant-a"}, "tenant-a") is True
    assert _tenant_matches({"tenant_id": "tenant-a"}, "tenant-b") is False
    assert _tenant_matches(None, "tenant-a") is False
    assert _tenant_matches({}, "tenant-a") is False
    assert _tenant_matches({"tenant_id": ""}, "tenant-a") is False
    assert _tenant_matches({"publisher_tenant_id": "tenant-a"}, "tenant-a", "publisher_tenant_id") is True


def test_permission_capabilities_matrix():
    from services.tag_resource_adapters import _permission_capabilities

    edit = _permission_capabilities("EDIT")
    assert (edit.can_read, edit.can_edit) == (True, True)
    read = _permission_capabilities("READ")
    assert (read.can_read, read.can_edit) == (False, False)
    read_only = _permission_capabilities("READ_ONLY")
    assert (read_only.can_read, read_only.can_edit) == (True, False)
    none = _permission_capabilities("")
    assert (none.can_read, none.can_edit) == (False, False)
    creator = _permission_capabilities("CREATOR", creator_is_edit=True)
    assert (creator.can_read, creator.can_edit) == (True, True)
    creator_no_flag = _permission_capabilities("CREATOR")
    assert (creator_no_flag.can_read, creator_no_flag.can_edit) == (True, False)


def test_display_prefers_first_present_field():
    from services.tag_resource_adapters import _display

    record = {
        "display_name": "Agent A",
        "name": "Agent A2",
        "description": "desc",
        "knowledge_describe": "kb desc",
        "source": "local",
    }
    display = _display(record, "display_name", "name")
    assert display.name == "Agent A"
    assert display.description == "desc"
    assert display.source == "local"
    assert _display(record, "missing").name == ""
    assert _display({"knowledge_describe": "only kb"}, "missing").description == "only kb"


def test_group_ids_handles_none_string_and_collection():
    from services.tag_resource_adapters import _group_ids

    assert _group_ids(None) == frozenset()
    assert _group_ids("g1, g2,,g3") == frozenset({"g1", "g2", "g3"})
    assert _group_ids(["g1", "g2"]) == frozenset({"g1", "g2"})
    assert _group_ids(42) == frozenset()


def test_tenant_scoped_capabilities_variants():
    from services.tag_resource_adapters import _tenant_scoped_capabilities

    admin = caller(role="ADMIN")
    # can_edit_all path
    admin_caps = _tenant_scoped_capabilities({"created_by": "someone"}, admin)
    assert (admin_caps.can_read, admin_caps.can_edit) == (True, True)

    regular = caller()
    # owner path
    owner_caps = _tenant_scoped_capabilities({"created_by": "user-1"}, regular)
    assert (owner_caps.can_read, owner_caps.can_edit) == (True, True)
    # no groups -> allow
    no_groups = _tenant_scoped_capabilities({"created_by": "x", "group_ids": None}, regular)
    assert (no_groups.can_read, no_groups.can_edit) == (True, True)
    # group intersection empty -> deny
    denied = _tenant_scoped_capabilities({"group_ids": ["other-group"]}, regular)
    assert (denied.can_read, denied.can_edit) == (False, False)
    # group intersection present, ingroup_permission READ -> read-only
    read_only = _tenant_scoped_capabilities(
        {"group_ids": ["g1"], "ingroup_permission": "READ_ONLY"},
        caller_with_group("g1"),
    )
    assert (read_only.can_read, read_only.can_edit) == (True, False)
    # group intersection present, ingroup_permission EDIT -> editable
    editable = _tenant_scoped_capabilities(
        {"group_ids": ["g1"], "ingroup_permission": "EDIT"},
        caller_with_group("g1"),
    )
    assert (editable.can_read, editable.can_edit) == (True, True)


# ---------- agent adapter ----------

def test_agent_invalid_id_or_origin_is_not_found():
    adapter = AgentTagResourceAdapter(ResourceAdapterDependencies())

    invalid_id = asyncio.run(adapter.resolve(ResourceReference(ResourceType.AGENT, "abc"), caller()))
    assert invalid_id == ResolvedTagResource.not_found()

    community = asyncio.run(
        adapter.resolve(ResourceReference(ResourceType.AGENT, 5, ResourceOrigin.COMMUNITY), caller())
    )
    assert community == ResolvedTagResource.not_found()


def test_agent_repository_missing_or_tenant_mismatch_is_not_found():
    dependencies = ResourceAdapterDependencies(
        get_agent_repository=lambda *_args: None,
        get_agent=lambda *_args: {"agent_id": 1, "tenant_id": "tenant-a"},
    )
    adapter = AgentTagResourceAdapter(dependencies)
    result = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.AGENT, 99, ResourceOrigin.MARKETPLACE),
            caller(),
        )
    )
    assert result == ResolvedTagResource.not_found()

    dependencies2 = ResourceAdapterDependencies(
        get_agent_repository=lambda *_args: {
            "agent_id": 1,
            "publisher_tenant_id": "tenant-other",
        },
        get_agent=lambda *_args: {"agent_id": 1, "tenant_id": "tenant-a"},
    )
    adapter2 = AgentTagResourceAdapter(dependencies2)
    result2 = asyncio.run(
        adapter2.resolve(
            ResourceReference(ResourceType.AGENT, 99, ResourceOrigin.MARKETPLACE),
            caller(),
        )
    )
    assert result2 == ResolvedTagResource.not_found()


def test_agent_repository_without_source_agent_id_is_not_found():
    dependencies = ResourceAdapterDependencies(
        get_agent_repository=lambda *_args: {"publisher_tenant_id": "tenant-a", "agent_id": None},
        get_agent=lambda *_args: {"agent_id": 1, "tenant_id": "tenant-a"},
    )
    adapter = AgentTagResourceAdapter(dependencies)
    result = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.AGENT, 99, ResourceOrigin.MARKETPLACE),
            caller(),
        )
    )
    assert result == ResolvedTagResource.not_found()


def test_agent_lookup_error_or_tenant_mismatch_is_not_found():
    adapter = AgentTagResourceAdapter(
        ResourceAdapterDependencies(
            get_agent=lambda *_args: (_ for _ in ()).throw(ValueError("boom"))
        )
    )
    result = asyncio.run(adapter.resolve(ResourceReference(ResourceType.AGENT, 5), caller()))
    assert result == ResolvedTagResource.not_found()

    adapter2 = AgentTagResourceAdapter(
        ResourceAdapterDependencies(
            get_agent=lambda *_args: {"agent_id": 5, "tenant_id": "tenant-other"}
        )
    )
    result2 = asyncio.run(adapter2.resolve(ResourceReference(ResourceType.AGENT, 5), caller()))
    assert result2 == ResolvedTagResource.not_found()


def test_agent_resolves_and_uses_display_and_permission():
    resolve_permission = MagicMock(return_value=None)
    dependencies = ResourceAdapterDependencies(
        get_agent=lambda *_args: {
            "agent_id": 5,
            "tenant_id": "tenant-a",
            "display_name": "My Agent",
            "description": "desc",
        },
        resolve_agent_permission=resolve_permission,
    )
    adapter = AgentTagResourceAdapter(dependencies)

    result = asyncio.run(adapter.resolve(ResourceReference(ResourceType.AGENT, 5), caller()))

    assert result.found is True
    assert result.identity.resource_id == "5"
    assert result.display.name == "My Agent"
    assert (result.capabilities.can_read, result.capabilities.can_edit) == (False, False)
    resolve_permission.assert_called_once_with(
        "USER",
        {"agent_id": 5, "tenant_id": "tenant-a", "display_name": "My Agent", "description": "desc"},
        "user-1",
        False,
    )


# ---------- skill adapter ----------

def test_skill_invalid_id_or_non_canonical_is_not_found():
    adapter = SkillTagResourceAdapter(ResourceAdapterDependencies())
    invalid = asyncio.run(adapter.resolve(ResourceReference(ResourceType.SKILL, "abc"), caller()))
    assert invalid == ResolvedTagResource.not_found()
    community = asyncio.run(
        adapter.resolve(ResourceReference(ResourceType.SKILL, 7, ResourceOrigin.COMMUNITY), caller())
    )
    assert community == ResolvedTagResource.not_found()


def test_skill_missing_or_cross_tenant_is_not_found():
    adapter = SkillTagResourceAdapter(
        ResourceAdapterDependencies(get_skill=lambda *_args: None)
    )
    result = asyncio.run(adapter.resolve(ResourceReference(ResourceType.SKILL, 7), caller()))
    assert result == ResolvedTagResource.not_found()

    adapter2 = SkillTagResourceAdapter(
        ResourceAdapterDependencies(
            get_skill=lambda *_args: {"skill_id": 7, "tenant_id": "tenant-other", "skill_name": "Hidden"}
        )
    )
    result2 = asyncio.run(adapter2.resolve(ResourceReference(ResourceType.SKILL, 7), caller()))
    assert result2 == ResolvedTagResource.not_found()


def test_skill_resolves_name_and_owner_capabilities():
    dependencies = ResourceAdapterDependencies(
        get_skill=lambda *_args: {
            "skill_id": 7,
            "tenant_id": "tenant-a",
            "skill_name": "Skill A",
            "created_by": "user-1",
        }
    )
    adapter = SkillTagResourceAdapter(dependencies)

    result = asyncio.run(adapter.resolve(ResourceReference(ResourceType.SKILL, 7), caller()))

    assert result.found is True
    assert result.display.name == "Skill A"
    assert (result.capabilities.can_read, result.capabilities.can_edit) == (True, True)
    assert result.identity.resource_id == "7"


# ---------- MCP adapter ----------

def test_mcp_invalid_id_or_unknown_origin_is_not_found():
    adapter = McpServiceTagResourceAdapter(ResourceAdapterDependencies())
    invalid = asyncio.run(adapter.resolve(ResourceReference(ResourceType.MCP_SERVICE, "abc"), caller()))
    assert invalid == ResolvedTagResource.not_found()
    unknown = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.MCP_SERVICE, 1, "mystery-origin"),
            caller(),
        )
    )
    assert unknown == ResolvedTagResource.not_found()


def test_mcp_local_missing_requires_listable_visibility():
    get_local = MagicMock(return_value=None)
    adapter = McpServiceTagResourceAdapter(
        ResourceAdapterDependencies(get_local_mcp=get_local, list_local_mcps=lambda **_kwargs: [])
    )
    result = asyncio.run(adapter.resolve(ResourceReference(ResourceType.MCP_SERVICE, 42), caller()))
    assert result == ResolvedTagResource.not_found()

    get_local2 = MagicMock(return_value={"mcp_id": 42, "tenant_id": "tenant-a"})
    adapter2 = McpServiceTagResourceAdapter(
        ResourceAdapterDependencies(
            get_local_mcp=get_local2,
            list_local_mcps=lambda **_kwargs: [{"mcp_id": 99, "permission": "READ"}],
        )
    )
    result2 = asyncio.run(adapter2.resolve(ResourceReference(ResourceType.MCP_SERVICE, 42), caller()))
    assert result2 == ResolvedTagResource.not_found()


def test_mcp_marketplace_missing_source_id_is_not_found():
    get_market = MagicMock(return_value={"tenant_id": "tenant-a", "source_mcp_id": None})
    adapter = McpServiceTagResourceAdapter(
        ResourceAdapterDependencies(get_market_mcp=get_market)
    )
    result = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.MCP_SERVICE, 99, ResourceOrigin.MARKETPLACE),
            caller(),
        )
    )
    assert result == ResolvedTagResource.not_found()


def test_mcp_local_resolves_with_visibility_and_permission():
    get_local = MagicMock(
        return_value={"mcp_id": 42, "tenant_id": "tenant-a", "mcp_name": "Local MCP", "description": "d"}
    )
    list_local = MagicMock(return_value=[{"mcp_id": 42, "permission": "EDIT"}])
    adapter = McpServiceTagResourceAdapter(
        ResourceAdapterDependencies(get_local_mcp=get_local, list_local_mcps=list_local)
    )

    result = asyncio.run(adapter.resolve(ResourceReference(ResourceType.MCP_SERVICE, 42), caller()))

    assert result.found is True
    assert result.display.name == "Local MCP"
    assert (result.capabilities.can_read, result.capabilities.can_edit) == (True, True)
    assert result.identity.resource_id == "42"


# ---------- knowledge base adapter ----------

def test_knowledge_base_non_canonical_or_empty_index_is_not_found():
    adapter = KnowledgeBaseTagResourceAdapter(ResourceAdapterDependencies())
    non_canonical = asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.KNOWLEDGE_BASE, "kb-1", ResourceOrigin.MARKETPLACE),
            caller(),
        )
    )
    assert non_canonical == ResolvedTagResource.not_found()
    empty = asyncio.run(
        adapter.resolve(ResourceReference(ResourceType.KNOWLEDGE_BASE, ""), caller())
    )
    assert empty == ResolvedTagResource.not_found()


def test_knowledge_base_missing_or_cross_tenant_is_not_found():
    adapter = KnowledgeBaseTagResourceAdapter(
        ResourceAdapterDependencies(get_knowledge_base=lambda *_args: None)
    )
    result = asyncio.run(
        adapter.resolve(ResourceReference(ResourceType.KNOWLEDGE_BASE, "kb-1"), caller())
    )
    assert result == ResolvedTagResource.not_found()

    adapter2 = KnowledgeBaseTagResourceAdapter(
        ResourceAdapterDependencies(
            get_knowledge_base=lambda *_args: {"tenant_id": "tenant-other", "index_name": "kb-1"}
        )
    )
    result2 = asyncio.run(
        adapter2.resolve(ResourceReference(ResourceType.KNOWLEDGE_BASE, "kb-1"), caller())
    )
    assert result2 == ResolvedTagResource.not_found()


def test_knowledge_base_permission_error_is_not_found():
    adapter = KnowledgeBaseTagResourceAdapter(
        ResourceAdapterDependencies(
            get_knowledge_base=lambda *_args: {"tenant_id": "tenant-a", "index_name": "kb-1"},
            resolve_knowledge_permission=lambda *_args: (_ for _ in ()).throw(ValueError()),
        )
    )
    result = asyncio.run(
        adapter.resolve(ResourceReference(ResourceType.KNOWLEDGE_BASE, "kb-1"), caller())
    )
    assert result == ResolvedTagResource.not_found()


def test_knowledge_base_resolves_read_only_when_edit_denied():
    dependencies = ResourceAdapterDependencies(
        get_knowledge_base=lambda *_args: {
            "tenant_id": "tenant-a",
            "index_name": "kb-1",
            "knowledge_name": "My KB",
            "description": "desc",
        },
        resolve_knowledge_permission=lambda *_args: "READ_ONLY",
        require_knowledge_edit_permission=lambda *_args: (_ for _ in ()).throw(PermissionError()),
    )
    adapter = KnowledgeBaseTagResourceAdapter(dependencies)
    result = asyncio.run(
        adapter.resolve(ResourceReference(ResourceType.KNOWLEDGE_BASE, "kb-1"), caller())
    )
    assert result.found is True
    assert result.display.name == "My KB"
    assert (result.capabilities.can_read, result.capabilities.can_edit) == (True, False)


def test_knowledge_base_resolves_creator_with_edit():
    dependencies = ResourceAdapterDependencies(
        get_knowledge_base=lambda *_args: {"tenant_id": "tenant-a", "index_name": "kb-1"},
        resolve_knowledge_permission=lambda *_args: "CREATOR",
        require_knowledge_edit_permission=lambda *_args: "ok",
    )
    adapter = KnowledgeBaseTagResourceAdapter(dependencies)
    result = asyncio.run(
        adapter.resolve(ResourceReference(ResourceType.KNOWLEDGE_BASE, "kb-1"), caller())
    )
    assert result.found is True
    assert (result.capabilities.can_read, result.capabilities.can_edit) == (True, True)
    assert result.identity.resource_id == "kb-1"


# ---------- registry / extra document branches ----------

def test_registry_unknown_type_or_missing_tenant_is_not_found():
    registry = TagResourceAdapterRegistry()
    unknown_type = asyncio.run(
        registry.resolve(
            ResourceReference(ResourceType.TOOL, 12),
            AuthenticatedCaller(user_id="u", authenticated_tenant_id="", role="USER"),
        )
    )
    assert unknown_type == ResolvedTagResource.not_found()


def test_adapter_helper_paths_cover_invalid_references_and_async_callbacks(monkeypatch):
    from services import tag_resource_adapters as adapters

    invalid = ResourceReference("unknown", "resource", "unknown")
    assert invalid.normalized_type() is None
    assert invalid.normalized_origin() is None

    sync_calls = []
    asyncio.run(adapters.run_tag_assignment_cleanup(object(), lambda descriptor: sync_calls.append(descriptor)))

    async def async_cleanup(descriptor):
        sync_calls.append(descriptor)

    async def async_value():
        return "completed"

    asyncio.run(adapters.run_tag_assignment_cleanup(object(), async_cleanup))
    assert asyncio.run(adapters._call(lambda: async_value())) == "completed"
    assert len(sync_calls) == 2

    assert adapters._tenant_scoped_capabilities(
        {}, AuthenticatedCaller(user_id="user", authenticated_tenant_id="tenant", can_edit_all=True)
    ).can_edit is True

    registry = TagResourceAdapterRegistry()
    registry._adapters.pop(ResourceType.TOOL)
    assert asyncio.run(
        registry.resolve(ResourceReference(ResourceType.TOOL, 1), caller())
    ) == ResolvedTagResource.not_found()

    tool_adapter = ToolTagResourceAdapter(
        ResourceAdapterDependencies(
            get_tools=lambda _tenant_id: [{"tool_id": 1, "author": "tenant-a", "tool_name": "Tool"}],
            resolve_tool_edit_permission=lambda *_args: (_ for _ in ()).throw(LookupError()),
        )
    )
    assert asyncio.run(
        tool_adapter.resolve(ResourceReference(ResourceType.TOOL, 1), caller())
    ).capabilities.can_edit is False


def test_aidp_permission_and_marketplace_error_paths(monkeypatch):
    from ext_components.aidp.consts.aidp_exceptions import (
        AidpKbNotFoundError,
        AidpKbPermissionDeniedError,
    )
    from services.tag_resource_adapters import (
        _require_provider_document_edit_permission,
        _resolve_provider_document_permission,
    )

    def raise_not_found(*_args):
        raise AidpKbNotFoundError("kb", "tenant-a")

    monkeypatch.setattr(
        "ext_components.aidp.services.aidp_permission_service.require_permission",
        raise_not_found,
    )
    with pytest.raises(ValueError, match="unavailable"):
        _resolve_provider_document_permission(
            provider=AIDP_DOCUMENT_PROVIDER,
            knowledge_base_id="kb",
            user_id="user-1",
            tenant_id="tenant-a",
        )
    with pytest.raises(ValueError, match="unavailable"):
        _require_provider_document_edit_permission(
            provider=AIDP_DOCUMENT_PROVIDER,
            knowledge_base_id="kb",
            user_id="user-1",
            tenant_id="tenant-a",
        )

    def raise_permission_denied(*_args):
        raise AidpKbPermissionDeniedError("kb", "user-1", "EDIT")

    monkeypatch.setattr(
        "ext_components.aidp.services.aidp_permission_service.require_permission",
        raise_permission_denied,
    )
    with pytest.raises(PermissionError, match="read-only"):
        _require_provider_document_edit_permission(
            provider=AIDP_DOCUMENT_PROVIDER,
            knowledge_base_id="kb",
            user_id="user-1",
            tenant_id="tenant-a",
        )

    adapter = McpServiceTagResourceAdapter(
        ResourceAdapterDependencies(get_market_mcp=lambda _market_id: {"tenant_id": "other"})
    )
    assert asyncio.run(
        adapter.resolve(
            ResourceReference(ResourceType.MCP_SERVICE, 9, ResourceOrigin.MARKETPLACE),
            caller(),
        )
    ) == ResolvedTagResource.not_found()


def test_document_edit_require_raises_lookup_or_value_error_is_not_found():
    for error_class in (LookupError, ValueError):
        adapter = DocumentTagResourceAdapter(
            document_dependencies(
                resolve_document=lambda **_kwargs: {
                    "tenant_id": "tenant-a",
                    "provider": "aidp",
                    "knowledge_base_id": "kb-1",
                    "provider_document_id": "doc-7",
                },
                require_document_edit_permission=lambda **_kwargs: (_ for _ in ()).throw(error_class()),
            )
        )
        result = asyncio.run(adapter.resolve(document_reference(), caller()))
        assert result == ResolvedTagResource.not_found()


def test_provider_document_helpers_for_local_and_aidp_providers(monkeypatch):
    from services.tag_resource_adapters import (
        _get_provider_knowledge_base,
        _require_provider_document_edit_permission,
        _resolve_provider_document,
        _resolve_provider_document_permission,
    )

    # unsupported provider -> error paths
    assert _get_provider_knowledge_base(provider="unknown", knowledge_base_id="kb", tenant_id="t") is None
    with pytest.raises(ValueError, match="Unsupported document provider"):
        _resolve_provider_document_permission(provider="unknown", knowledge_base_id="kb", user_id="u", tenant_id="t")
    with pytest.raises(ValueError, match="Unsupported document provider"):
        _require_provider_document_edit_permission(provider="unknown", knowledge_base_id="kb", user_id="u", tenant_id="t")
    assert asyncio.run(
        _resolve_provider_document(provider="unknown", knowledge_base_id="kb", provider_document_id="d", tenant_id="t")
    ) is None

    # local provider uses get_knowledge_record + ES file listing
    monkeypatch.setattr(
        "services.tag_resource_adapters.get_knowledge_record",
        lambda *_args, **_kwargs: {"index_name": "kb", "tenant_id": "t"},
    )
    assert _get_provider_knowledge_base(provider="local", knowledge_base_id="kb", tenant_id="t") == {
        "index_name": "kb",
        "tenant_id": "t",
    }

    async def fake_list_files(*args, **kwargs):
        return {
            "files": [
                {"path_or_url": "docs/a.pdf", "file": "a.pdf"},
                {"path_or_url": "docs/b.pdf", "file": "b.pdf"},
            ]
        }

    es_service = MagicMock()
    es_service.list_files.side_effect = fake_list_files
    es_service.resolve_knowledge_base_permission.return_value = "READ"
    es_service.require_knowledge_base_edit_permission.return_value = None
    monkeypatch.setattr(
        "services.tag_resource_adapters.ElasticSearchService",
        es_service,
    )
    doc = asyncio.run(
        _resolve_provider_document(
            provider="local", knowledge_base_id="kb", provider_document_id="docs/b.pdf", tenant_id="t"
        )
    )
    assert doc is not None
    assert doc["document_name"] == "b.pdf"
    assert (
        _resolve_provider_document_permission(provider="local", knowledge_base_id="kb", user_id="u", tenant_id="t")
        == "READ"
    )
    _require_provider_document_edit_permission(provider="local", knowledge_base_id="kb", user_id="u", tenant_id="t")

    # aidp provider
    monkeypatch.setattr(
        "consts.const.AIDP_SERVER_URL",
        "http://aidp",
    )
    monkeypatch.setattr(
        "consts.const.AIDP_API_KEY",
        "key",
    )
    aidp_list = MagicMock(
        return_value={
            "value": [{"file_ino_no": "f-1", "file_name": "one.pdf"}],
            "next_link": None,
        }
    )
    monkeypatch.setattr(
        "ext_components.aidp.services.aidp_service.list_aidp_docs_impl",
        aidp_list,
    )
    aidp_kb = {"kb_id": "kb", "tenant_id": "t"}
    monkeypatch.setattr(
        "ext_components.aidp.database.aidp_permission_db.get_permission_by_kb_id",
        lambda kb_id=None, tenant_id=None: aidp_kb,
    )
    assert _get_provider_knowledge_base(provider="aidp", knowledge_base_id="kb", tenant_id="t") == aidp_kb
    aidp_doc = asyncio.run(
        _resolve_provider_document(
            provider="aidp", knowledge_base_id="kb", provider_document_id="f-1", tenant_id="t"
        )
    )
    assert aidp_doc is not None
    assert aidp_doc["document_name"] == "one.pdf"

    # aidp permission resolution via require_permission
    from services.tag_resource_adapters import AIDP_DOCUMENT_PROVIDER

    def fake_require_permission(kb_id, user_id, tenant_id, required):
        class Perm:
            permission = "EDIT"
        return Perm()

    monkeypatch.setattr(
        "ext_components.aidp.services.aidp_permission_service.require_permission",
        fake_require_permission,
    )
    assert (
        _resolve_provider_document_permission(provider="aidp", knowledge_base_id="kb", user_id="u", tenant_id="t")
        == "EDIT"
    )
    _require_provider_document_edit_permission(provider="aidp", knowledge_base_id="kb", user_id="u", tenant_id="t")
