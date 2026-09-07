"""Unit tests for the protected intelligent-workbench system Agent."""

from dataclasses import FrozenInstanceError

import pytest
from sqlalchemy.exc import IntegrityError

from consts.model import AgentInfoRequest
from management.services.agent.system_agent_provider import (
    WORKBENCH_MAIN_SYSTEM_KEY,
    WORKBENCH_OFFICIAL_SKILL_NAMES,
    SystemAgentProvider,
    SystemAgentRef,
    WorkbenchAgentError,
)


def _agent(provider: SystemAgentProvider, **overrides):
    value = {
        "agent_id": 17,
        "tenant_id": "tenant-a",
        "system_key": WORKBENCH_MAIN_SYSTEM_KEY,
        "agent_origin": "SYSTEM",
        "current_version_no": 2,
        "system_revision": provider.release_manifest.system_revision,
        **provider._editable_fields(),
    }
    value.update(overrides)
    return value


def _published(provider: SystemAgentProvider, version_no: int = 2):
    return {
        "agent_id": 17,
        "tenant_id": "tenant-a",
        "system_key": WORKBENCH_MAIN_SYSTEM_KEY,
        "agent_origin": "SYSTEM",
        "version_no": version_no,
        "enabled": True,
        "system_revision": provider.release_manifest.system_revision,
    }


def test_wma_001_ref_is_immutable_and_published():
    """UT-BE-WMA-001."""
    ref = SystemAgentRef(
        tenant_id="tenant-a",
        system_key=WORKBENCH_MAIN_SYSTEM_KEY,
        agent_id=17,
        version_no=2,
    )

    with pytest.raises(FrozenInstanceError):
        ref.version_no = 3


def test_wma_002_get_ref_is_tenant_scoped(mocker):
    """UT-BE-WMA-002."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    draft = _agent(provider)
    search = mocker.patch(
        "management.services.agent.system_agent_provider.search_system_agent",
        side_effect=[draft, _published(provider)],
    )

    ref = provider.get_workbench_main_ref("tenant-a")

    assert ref == SystemAgentRef("tenant-a", WORKBENCH_MAIN_SYSTEM_KEY, 17, 2)
    assert search.call_args_list[0].args == ("tenant-a", WORKBENCH_MAIN_SYSTEM_KEY)
    assert search.call_args_list[1].kwargs["version_no"] == 2


def test_wma_004_prompt_is_localized():
    """UT-BE-WMA-004."""
    provider = SystemAgentProvider()

    assert "general-purpose workbench assistant" in provider.get_system_prompt("en")
    assert "通用智能工作台助手" in provider.get_system_prompt("zh")


def test_wma_005_unknown_locale_has_deterministic_fallback():
    """UT-BE-WMA-005: unsupported locales deterministically use Chinese."""
    provider = SystemAgentProvider()

    assert provider.get_system_prompt("") == provider.get_system_prompt("unknown")
    assert provider.get_system_prompt("unknown") == provider.get_system_prompt("zh")


def test_sal_002_ordinary_request_cannot_assign_system_identity():
    """UT-BE-SAL-002 and UT-BE-SAL-013: clients cannot set system controls."""
    assert "system_key" not in AgentInfoRequest.model_fields
    assert "agent_origin" not in AgentInfoRequest.model_fields
    assert "system_revision" not in AgentInfoRequest.model_fields


@pytest.mark.parametrize("language", ["en", "zh"])
def test_wma_011_014_prompt_reserves_runtime_orchestration_boundary(language):
    """UT-BE-WMA-011, UT-BE-WMA-012, UT-BE-WMA-013, UT-BE-WMA-014."""
    prompt = SystemAgentProvider.get_system_prompt(language)

    assert "managed Agent" in prompt or "子智能体" in prompt
    assert "independent" in prompt or "彼此独立" in prompt
    assert "duplicate" in prompt or "重复委派" in prompt
    assert "dedicated creation workflow" in prompt or "专用创建流程" in prompt
    assert "NL2Skill" not in prompt
    assert "NL2Agent" not in prompt


def test_wma_009_010_provider_contract_has_no_runtime_mount_inputs():
    """UT-BE-WMA-009 and UT-BE-WMA-010: mounts remain outside persistence."""
    import inspect

    parameters = inspect.signature(SystemAgentProvider.ensure_workbench_main).parameters

    assert set(parameters) == {"self", "tenant_id", "user_id", "locale"}


@pytest.mark.parametrize(
    ("aidp_enabled", "expected", "excluded"),
    [
        (True, "aidp_search", "knowledge_base_search"),
        (False, "knowledge_base_search", "aidp_search"),
    ],
)
def test_wma_006_007_manifest_selects_one_knowledge_tool(
    aidp_enabled, expected, excluded
):
    """UT-BE-WMA-006 and UT-BE-WMA-007."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=aidp_enabled)

    assert provider.release_manifest.persistent_tool_names == (expected,)
    assert excluded not in provider.release_manifest.persistent_tool_names


def test_wma_008_manifest_persists_no_runtime_injected_tools():
    """UT-BE-WMA-008."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)

    assert provider.release_manifest.persistent_tool_names == (
        "knowledge_base_search",
    )
    assert "analyze_image" not in provider.release_manifest.persistent_tool_names
    assert "upload_to_s3" not in provider.release_manifest.persistent_tool_names
    assert "download_from_s3" not in provider.release_manifest.persistent_tool_names


def test_wma_015_release_installs_exact_official_skills(mocker):
    """UT-BE-WMA-015."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    installer = mocker.patch(
        "management.services.agent.system_agent_provider.install_skills_from_zip_for_tenant",
        return_value=list(WORKBENCH_OFFICIAL_SKILL_NAMES),
    )
    mocker.patch(
        "management.services.agent.system_agent_provider.skill_db.get_skill_by_name",
        side_effect=lambda name, tenant_id: {
            "skill_id": WORKBENCH_OFFICIAL_SKILL_NAMES.index(name) + 1,
            "skill_name": name,
            "source": "official",
        },
    )

    skills = provider._prepare_official_skills("tenant-a", "system")

    assert tuple(skill["skill_name"] for skill in skills) == (
        WORKBENCH_OFFICIAL_SKILL_NAMES
    )
    installer.assert_called_once_with(
        skill_names=list(WORKBENCH_OFFICIAL_SKILL_NAMES),
        tenant_id="tenant-a",
        user_id="system",
    )


def test_wma_016_release_rejects_same_name_custom_skill(mocker):
    """UT-BE-WMA-016 and UT-BE-WMA-017."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    mocker.patch(
        "management.services.agent.system_agent_provider.install_skills_from_zip_for_tenant",
        return_value=list(WORKBENCH_OFFICIAL_SKILL_NAMES),
    )
    mocker.patch(
        "management.services.agent.system_agent_provider.skill_db.get_skill_by_name",
        side_effect=lambda name, tenant_id: {
            "skill_id": 1,
            "skill_name": name,
            "source": "custom" if name == "docx" else "official",
        },
    )

    with pytest.raises(WorkbenchAgentError) as exc_info:
        provider._prepare_official_skills("tenant-a", "system")

    assert exc_info.value.code == "official_skill_name_conflict"


def test_wma_006_016_replace_binds_exact_tool_and_six_skills(mocker):
    """UT-BE-WMA-003, UT-BE-WMA-006, UT-BE-WMA-008, UT-BE-WMA-016."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=True)
    mocker.patch(
        "management.services.agent.system_agent_provider.query_all_tools",
        return_value=[
            {"tool_id": 11, "name": "aidp_search", "is_available": True},
            {
                "tool_id": 12,
                "name": "knowledge_base_search",
                "is_available": True,
            },
            {"tool_id": 13, "name": "analyze_image", "is_available": True},
        ],
    )
    delete_tools = mocker.patch(
        "management.services.agent.system_agent_provider.delete_tools_by_agent_id"
    )
    bind_tool = mocker.patch(
        "management.services.agent.system_agent_provider.create_or_update_tool_by_tool_info"
    )
    delete_skills = mocker.patch(
        "management.services.agent.system_agent_provider.delete_skills_by_agent_id"
    )
    bind_skill = mocker.patch(
        "management.services.agent.system_agent_provider.skill_db.create_or_update_skill_by_skill_info"
    )
    skills = [
        {"skill_id": index + 1, "skill_name": name, "source": "official"}
        for index, name in enumerate(WORKBENCH_OFFICIAL_SKILL_NAMES)
    ]

    provider._replace_release_capabilities(
        agent_id=17,
        tenant_id="tenant-a",
        actor="system",
        official_skills=skills,
    )

    delete_tools.assert_called_once_with(
        17,
        "tenant-a",
        "system",
        version_no=0,
        allow_system=True,
    )
    assert bind_tool.call_count == 1
    assert bind_tool.call_args.args[0].tool_id == 11
    delete_skills.assert_called_once_with(
        17,
        "tenant-a",
        "system",
        version_no=0,
        allow_system=True,
    )
    assert [
        call.args[0]["skill_id"] for call in bind_skill.call_args_list
    ] == [1, 2, 3, 4, 5, 6]


def test_wma_017_missing_official_package_blocks_release(mocker):
    """UT-BE-WMA-017."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    mocker.patch(
        "management.services.agent.system_agent_provider.install_skills_from_zip_for_tenant",
        return_value=[
            name for name in WORKBENCH_OFFICIAL_SKILL_NAMES if name != "pdf"
        ],
    )
    resolve = mocker.patch(
        "management.services.agent.system_agent_provider.skill_db.get_skill_by_name"
    )

    with pytest.raises(WorkbenchAgentError) as exc_info:
        provider._prepare_official_skills("tenant-a", "system")

    assert exc_info.value.code == "official_skill_install_failed"
    assert exc_info.value.retryable is True
    resolve.assert_not_called()


def test_sal_004_initializes_release_and_returns_published_ref(mocker):
    """UT-BE-SAL-001, UT-BE-SAL-004, UT-BE-SAL-006."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    created = _agent(
        provider,
        current_version_no=None,
        system_revision=None,
    )
    search = mocker.patch(
        "management.services.agent.system_agent_provider.search_system_agent",
        side_effect=[None, created, {**created, "current_version_no": 1}, _published(provider, 1)],
    )
    create = mocker.patch(
        "management.services.agent.system_agent_provider.create_agent",
        return_value=created,
    )
    mocker.patch("management.services.agent.system_agent_provider.clear_agent_new_mark")
    prepare = mocker.patch.object(
        provider,
        "_prepare_official_skills",
        return_value=[
            {"skill_id": index + 1, "skill_name": name, "source": "official"}
            for index, name in enumerate(WORKBENCH_OFFICIAL_SKILL_NAMES)
        ],
    )
    sync = mocker.patch.object(provider, "_replace_release_capabilities")
    mocker.patch("management.services.agent.system_agent_provider.update_agent")
    publish = mocker.patch(
        "management.services.agent.system_agent_provider.publish_version_impl",
        return_value={"version_no": 1},
    )
    mark = mocker.patch("management.services.agent.system_agent_provider.update_system_agent_revision")

    ref = provider.ensure_workbench_main("tenant-a", "user-a", locale="zh")

    assert ref == SystemAgentRef("tenant-a", WORKBENCH_MAIN_SYSTEM_KEY, 17, 1)
    assert search.call_count == 4
    assert create.call_args.args[0]["system_revision"] is None
    assert "通用智能工作台助手" in create.call_args.args[0]["duty_prompt"]
    prepare.assert_called_once_with("tenant-a", "user-a")
    sync.assert_called_once()
    publish.assert_called_once()
    mark.assert_called_once_with(
        agent_id=17,
        tenant_id="tenant-a",
        system_revision="2.5.1",
        user_id="user-a",
    )


def test_sal_003_unique_conflict_reuses_concurrent_system_agent(mocker):
    """UT-BE-SAL-003: concurrent bootstrap converges on one system identity."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    concurrent = _agent(provider)
    mocker.patch(
        "management.services.agent.system_agent_provider.create_agent",
        side_effect=IntegrityError("insert", {}, RuntimeError("unique")),
    )
    search = mocker.patch(
        "management.services.agent.system_agent_provider.search_system_agent",
        return_value=concurrent,
    )
    clear = mocker.patch("management.services.agent.system_agent_provider.clear_agent_new_mark")

    result = provider._create_draft("tenant-a", "system")

    assert result is concurrent
    search.assert_called_once_with(
        "tenant-a",
        WORKBENCH_MAIN_SYSTEM_KEY,
        version_no=0,
    )
    clear.assert_not_called()


def test_sal_005_same_revision_ready_ensure_is_read_only(mocker):
    """UT-BE-SAL-005."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    existing = _agent(provider)
    mocker.patch(
        "management.services.agent.system_agent_provider.search_system_agent",
        side_effect=[existing, _published(provider)],
    )
    mocker.patch.object(provider, "_release_state_matches", return_value=True)
    prepare = mocker.patch.object(provider, "_prepare_official_skills")
    replace = mocker.patch.object(provider, "_replace_release_capabilities")
    update = mocker.patch("management.services.agent.system_agent_provider.update_agent")
    publish = mocker.patch("management.services.agent.system_agent_provider.publish_version_impl")
    mark = mocker.patch("management.services.agent.system_agent_provider.update_system_agent_revision")

    ref = provider.ensure_workbench_main("tenant-a")

    assert ref.version_no == 2
    prepare.assert_not_called()
    replace.assert_not_called()
    update.assert_not_called()
    publish.assert_not_called()
    mark.assert_not_called()


def test_sal_007_same_revision_drift_does_not_mutate(mocker):
    """UT-BE-SAL-007."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    mocker.patch(
        "management.services.agent.system_agent_provider.search_system_agent",
        return_value=_agent(provider, duty_prompt="drift"),
    )
    mocker.patch.object(provider, "_release_state_matches", return_value=False)
    prepare = mocker.patch.object(provider, "_prepare_official_skills")
    update = mocker.patch("management.services.agent.system_agent_provider.update_agent")
    publish = mocker.patch("management.services.agent.system_agent_provider.publish_version_impl")

    with pytest.raises(WorkbenchAgentError) as exc_info:
        provider.ensure_workbench_main("tenant-a")

    assert exc_info.value.code == "system_agent_drift_detected"
    prepare.assert_not_called()
    update.assert_not_called()
    publish.assert_not_called()


def test_sal_008_new_revision_upgrades_once(mocker):
    """UT-BE-SAL-008."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=True)
    old = _agent(provider, system_revision="2.5.0", current_version_no=2)
    upgraded = _agent(provider, system_revision="2.5.1", current_version_no=3)
    mocker.patch(
        "management.services.agent.system_agent_provider.search_system_agent",
        side_effect=[old, upgraded, _published(provider, 3)],
    )
    mocker.patch.object(
        provider,
        "_prepare_official_skills",
        return_value=[
            {"skill_id": index + 1, "skill_name": name, "source": "official"}
            for index, name in enumerate(WORKBENCH_OFFICIAL_SKILL_NAMES)
        ],
    )
    replace = mocker.patch.object(provider, "_replace_release_capabilities")
    update = mocker.patch("management.services.agent.system_agent_provider.update_agent")
    publish = mocker.patch(
        "management.services.agent.system_agent_provider.publish_version_impl",
        return_value={"version_no": 3},
    )
    mark = mocker.patch("management.services.agent.system_agent_provider.update_system_agent_revision")

    ref = provider.ensure_workbench_main("tenant-a", "system")

    assert ref.version_no == 3
    replace.assert_called_once()
    update.assert_called_once()
    publish.assert_called_once()
    mark.assert_called_once()


def test_sal_008_older_runtime_cannot_downgrade_system_agent(mocker):
    """UT-BE-SAL-008 boundary."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    existing = _agent(
        provider,
        system_revision="2.6.0",
        current_version_no=3,
    )
    mocker.patch(
        "management.services.agent.system_agent_provider.search_system_agent",
        return_value=existing,
    )
    prepare = mocker.patch.object(provider, "_prepare_official_skills")
    publish = mocker.patch("management.services.agent.system_agent_provider.publish_version_impl")

    with pytest.raises(WorkbenchAgentError) as exc_info:
        provider.ensure_workbench_main("tenant-a")

    assert exc_info.value.code == "system_agent_revision_ahead"
    prepare.assert_not_called()
    publish.assert_not_called()


def test_sal_016_publish_failure_does_not_advance_revision(mocker):
    """UT-BE-SAL-015 and UT-BE-SAL-016: failure returns no draft."""
    provider = SystemAgentProvider(app_version="2.5.1", aidp_enabled=False)
    old = _agent(provider, system_revision="2.5.0", current_version_no=2)
    mocker.patch(
        "management.services.agent.system_agent_provider.search_system_agent",
        return_value=old,
    )
    mocker.patch.object(
        provider,
        "_prepare_official_skills",
        return_value=[
            {"skill_id": index + 1, "skill_name": name, "source": "official"}
            for index, name in enumerate(WORKBENCH_OFFICIAL_SKILL_NAMES)
        ],
    )
    mocker.patch.object(provider, "_replace_release_capabilities")
    mocker.patch("management.services.agent.system_agent_provider.update_agent")
    mocker.patch(
        "management.services.agent.system_agent_provider.publish_version_impl",
        side_effect=RuntimeError("publish failed"),
    )
    mark = mocker.patch("management.services.agent.system_agent_provider.update_system_agent_revision")

    with pytest.raises(WorkbenchAgentError) as exc_info:
        provider.ensure_workbench_main("tenant-a")

    assert exc_info.value.code == "system_agent_not_ready"
    mark.assert_not_called()


def test_sal_014_migration_contains_nullable_system_revision():
    """UT-BE-SAL-014."""
    migration = (
        "deploy/sql/migrations/v2.5.2_0902_agent_workbench_system_agents.sql"
    )

    with open(migration, encoding="utf-8") as file:
        sql = file.read()

    assert "ADD COLUMN IF NOT EXISTS system_revision" in sql
    assert "system_revision VARCHAR" in sql
    assert "INSERT INTO nexent.ag_tenant_agent_t" not in sql
    assert "required_grants (role_permission_id" in sql
    assert "(1701, 'SU'" in sql
    assert "(1710, 'SPEED'" in sql
    assert "INSERT INTO nexent.role_permission_t" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "'USER', 'RESOURCE', 'SKILL', 'CREATE'" not in sql
