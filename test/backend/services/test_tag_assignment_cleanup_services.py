import pytest
from consts.exceptions import McpNotFoundError
from management.services.agent import management as agent_service
from management.services.skill.service import SkillService
from services import remote_mcp_service
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import _encode_document_resource_id


@pytest.mark.asyncio
async def test_agent_delete_cleans_up_only_a_proven_tenant_owned_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        agent_service,
        "search_agent_info_by_agent_id",
        lambda agent_id, tenant_id: {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    monkeypatch.setattr(
        agent_service, "delete_agent_by_id", lambda *args: calls.append("agent")
    )
    monkeypatch.setattr(
        agent_service, "delete_agent_relationship", lambda *args: calls.append("relationship")
    )
    monkeypatch.setattr(
        agent_service, "delete_tools_by_agent_id", lambda *args: calls.append("tools")
    )
    monkeypatch.setattr(
        agent_service.skill_db, "delete_skills_by_agent_id", lambda *args: calls.append("skills")
    )
    monkeypatch.setattr(
        TagManagementService,
        "cleanup_resource_assignments",
        lambda *args: calls.append(args),
    )

    await agent_service.delete_agent_impl(7, "tenant-a", "user-a")

    assert calls[-1] == ("tenant-a", "agent", "7", "user-a")


@pytest.mark.asyncio
async def test_agent_delete_does_not_clean_assignments_for_another_tenant(monkeypatch):
    monkeypatch.setattr(
        agent_service,
        "search_agent_info_by_agent_id",
        lambda agent_id, tenant_id: {"agent_id": agent_id, "tenant_id": "other-tenant"},
    )
    monkeypatch.setattr(agent_service, "delete_agent_by_id", lambda *args: None)
    monkeypatch.setattr(agent_service, "delete_agent_relationship", lambda *args: None)
    monkeypatch.setattr(agent_service, "delete_tools_by_agent_id", lambda *args: None)
    monkeypatch.setattr(agent_service.skill_db, "delete_skills_by_agent_id", lambda *args: None)
    cleanup_calls = []
    monkeypatch.setattr(
        TagManagementService,
        "cleanup_resource_assignments",
        lambda *args: cleanup_calls.append(args),
    )

    await agent_service.delete_agent_impl(7, "tenant-a", "user-a")

    assert cleanup_calls == []


def test_skill_delete_cleans_up_the_tenant_scoped_stable_skill_id(monkeypatch):
    service = object.__new__(SkillService)
    service.tenant_id = "tenant-a"
    monkeypatch.setattr(SkillService, "_local_skills_dir", lambda *args: "/tmp/skills")
    monkeypatch.setattr("management.services.skill.service.os.path.exists", lambda path: False)
    monkeypatch.setattr(
        "management.services.skill.service.skill_db.get_skill_by_name",
        lambda skill_name, tenant_id: {"skill_id": 11, "tenant_id": tenant_id},
    )
    monkeypatch.setattr(
        "management.services.skill.service.skill_db.delete_skill", lambda *args, **kwargs: True
    )
    cleanup_calls = []
    monkeypatch.setattr(
        TagManagementService,
        "cleanup_resource_assignments",
        lambda *args: cleanup_calls.append(args),
    )

    assert service.delete_skill("summarize", tenant_id="tenant-a", user_id="user-a") is True
    assert cleanup_calls == [("tenant-a", "skill", "11", "user-a")]


def test_skill_delete_without_a_same_tenant_record_does_not_clean_up(monkeypatch):
    service = object.__new__(SkillService)
    service.tenant_id = "tenant-a"
    monkeypatch.setattr(SkillService, "_local_skills_dir", lambda *args: "/tmp/skills")
    monkeypatch.setattr("management.services.skill.service.os.path.exists", lambda path: False)
    monkeypatch.setattr("management.services.skill.service.skill_db.get_skill_by_name", lambda *args: None)
    monkeypatch.setattr(
        "management.services.skill.service.skill_db.delete_skill", lambda *args, **kwargs: False
    )
    cleanup_calls = []
    monkeypatch.setattr(
        TagManagementService,
        "cleanup_resource_assignments",
        lambda *args: cleanup_calls.append(args),
    )

    assert service.delete_skill("summarize", tenant_id="tenant-a", user_id="user-a") is False
    assert cleanup_calls == []


@pytest.mark.asyncio
async def test_mcp_delete_cleans_up_after_the_local_tenant_record_is_deleted(monkeypatch):
    calls = []
    monkeypatch.setattr(
        remote_mcp_service,
        "get_mcp_record_by_id_and_tenant",
        lambda **kwargs: {"mcp_id": 13, "tenant_id": kwargs["tenant_id"], "container_id": None},
    )
    monkeypatch.setattr(remote_mcp_service, "set_mcp_tools_unavailable", lambda **kwargs: None)
    monkeypatch.setattr(
        remote_mcp_service, "delete_mcp_record_by_id", lambda **kwargs: calls.append("delete")
    )
    monkeypatch.setattr(
        TagManagementService,
        "cleanup_resource_assignments",
        lambda *args: calls.append(args),
    )

    await remote_mcp_service.delete_mcp_service(tenant_id="tenant-a", user_id="user-a", mcp_id=13)

    assert calls == ["delete", ("tenant-a", "mcp_service", "13", "user-a")]


@pytest.mark.asyncio
async def test_mcp_delete_does_not_clean_up_when_the_tenant_record_is_absent(monkeypatch):
    monkeypatch.setattr(
        remote_mcp_service, "get_mcp_record_by_id_and_tenant", lambda **kwargs: None
    )
    cleanup_calls = []
    monkeypatch.setattr(
        TagManagementService,
        "cleanup_resource_assignments",
        lambda *args: cleanup_calls.append(args),
    )

    with pytest.raises(McpNotFoundError):
        await remote_mcp_service.delete_mcp_service(
            tenant_id="tenant-a", user_id="user-a", mcp_id=13
        )

    assert cleanup_calls == []


@pytest.mark.asyncio
async def test_container_mcp_delete_cleans_up_the_resolved_local_record(monkeypatch):
    calls = []
    monkeypatch.setattr(
        remote_mcp_service,
        "get_mcp_records_by_tenant",
        lambda **_kwargs: [{"mcp_id": 13, "container_id": "container-1", "mcp_name": "Demo"}],
    )
    monkeypatch.setattr(remote_mcp_service, "set_mcp_tools_unavailable", lambda **_kwargs: None)
    monkeypatch.setattr(
        remote_mcp_service, "delete_mcp_record_by_container_id", lambda **_kwargs: calls.append("delete")
    )
    monkeypatch.setattr(
        TagManagementService,
        "cleanup_resource_assignments",
        lambda *args: calls.append(args),
    )

    await remote_mcp_service.delete_mcp_by_container_id("tenant-a", "user-a", "container-1")

    assert calls == ["delete", ("tenant-a", "mcp_service", "13", "user-a")]


def test_document_cleanup_uses_the_canonical_provider_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(
        TagManagementService,
        "cleanup_resource_assignments",
        lambda *args: calls.append(args) or 1,
    )

    result = TagManagementService.cleanup_document_assignments(
        "tenant-a", "aidp", "kb-1", "file-7", "user-a"
    )

    assert result == 1
    assert calls == [
        (
            "tenant-a",
            "knowledge_document",
            _encode_document_resource_id("aidp", "kb-1", "file-7"),
            "user-a",
        )
    ]


def test_knowledge_base_document_cleanup_delegates_to_tenant_scoped_database_operation(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.soft_delete_document_assignments_for_knowledge_base",
        lambda *args: calls.append(args) or 2,
    )

    result = TagManagementService.cleanup_document_assignments_for_knowledge_base(
        "tenant-a", "local", "kb-1", "user-a"
    )

    assert result == 2
    assert calls == [("tenant-a", "local", "kb-1", "user-a")]
