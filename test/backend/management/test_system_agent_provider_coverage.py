from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from consts.exceptions import WorkbenchAgentError
from management.services.agent import system_agent_provider as module


def _provider():
    return module.SystemAgentProvider(app_version="2.5.3", aidp_enabled=False)


def _draft(provider, **updates):
    value = {
        "agent_id": 17,
        "current_version_no": 2,
        "system_revision": provider.release_manifest.system_revision,
        **provider._editable_fields(),
    }
    value.update(updates)
    return value


def test_provider_requires_non_blank_revision():
    with pytest.raises(ValueError, match="app_version is required"):
        module.SystemAgentProvider(app_version=" ")


def test_get_ref_requires_existing_draft(monkeypatch):
    monkeypatch.setattr(module, "search_system_agent", lambda *_args, **_kwargs: None)

    with pytest.raises(WorkbenchAgentError, match="system_agent_not_ready"):
        _provider().get_workbench_main_ref("tenant-a")


def test_ensure_requires_created_draft_to_be_visible(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(module, "search_system_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(provider, "_create_draft", MagicMock())

    with pytest.raises(WorkbenchAgentError, match="draft was not created"):
        provider.ensure_workbench_main("tenant-a")


def test_create_draft_reraises_unique_conflict_without_concurrent_row(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        module,
        "create_agent",
        MagicMock(side_effect=IntegrityError("insert", {}, RuntimeError("duplicate"))),
    )
    monkeypatch.setattr(module, "search_system_agent", lambda *_args, **_kwargs: None)

    with pytest.raises(IntegrityError):
        provider._create_draft("tenant-a", "user-a")


def test_prepare_official_skills_tolerates_import_failure_and_filters_sources(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        module,
        "install_skills_from_zip_for_tenant",
        MagicMock(side_effect=RuntimeError("archive unavailable")),
    )

    def lookup(name, _tenant):
        if name == "docx":
            return {"skill_id": 1, "skill_name": name, "source": "community"}
        if name == "pdf":
            return {"skill_id": 2, "skill_name": name, "source": "official"}
        return None

    monkeypatch.setattr(module.skill_db, "get_skill_by_name", lookup)

    assert provider._prepare_official_skills("tenant-a", "user-a") == [
        {"skill_id": 2, "skill_name": "pdf", "source": "official"}
    ]


def test_ensure_maps_unexpected_release_failure(monkeypatch):
    provider = _provider()
    existing = _draft(provider, current_version_no=1, system_revision="2.5.2")
    monkeypatch.setattr(module, "search_system_agent", MagicMock(return_value=existing))
    monkeypatch.setattr(
        provider, "_prepare_official_skills", MagicMock(side_effect=RuntimeError("broken"))
    )

    with pytest.raises(WorkbenchAgentError, match="broken") as caught:
        provider.ensure_workbench_main("tenant-a")
    assert caught.value.retryable is True


def test_ensure_preserves_specific_workbench_error(monkeypatch):
    provider = _provider()
    existing = _draft(provider, current_version_no=1, system_revision="2.5.2")
    expected = WorkbenchAgentError("official_skill_missing")
    monkeypatch.setattr(module, "search_system_agent", MagicMock(return_value=existing))
    monkeypatch.setattr(
        provider, "_prepare_official_skills", MagicMock(side_effect=expected)
    )

    with pytest.raises(WorkbenchAgentError) as caught:
        provider.ensure_workbench_main("tenant-a")
    assert caught.value is expected


def test_ensure_uses_publish_result_when_draft_version_is_stale(monkeypatch):
    provider = _provider()
    existing = _draft(provider, current_version_no=1, system_revision="2.5.2")
    resolved = _draft(provider, current_version_no=None)
    published = {"version_no": 5}
    search = MagicMock(side_effect=[existing, resolved, {**resolved, "current_version_no": 5}])
    monkeypatch.setattr(module, "search_system_agent", search)
    monkeypatch.setattr(provider, "_prepare_official_skills", MagicMock(return_value=[]))
    monkeypatch.setattr(provider, "_replace_release_capabilities", MagicMock())
    monkeypatch.setattr(module, "update_agent", MagicMock())
    monkeypatch.setattr(module, "publish_version_impl", MagicMock(return_value=published))
    monkeypatch.setattr(module, "update_system_agent_revision", MagicMock())

    ref = provider.ensure_workbench_main("tenant-a")

    assert ref.version_no == 5


def test_ensure_requires_resolved_draft_after_publish(monkeypatch):
    provider = _provider()
    existing = _draft(provider, current_version_no=1, system_revision="2.5.2")
    monkeypatch.setattr(module, "search_system_agent", MagicMock(side_effect=[existing, None]))
    monkeypatch.setattr(provider, "_prepare_official_skills", MagicMock(return_value=[]))
    monkeypatch.setattr(provider, "_replace_release_capabilities", MagicMock())
    monkeypatch.setattr(module, "update_agent", MagicMock())
    monkeypatch.setattr(module, "publish_version_impl", MagicMock(return_value={"version_no": 5}))
    monkeypatch.setattr(module, "update_system_agent_revision", MagicMock())

    with pytest.raises(WorkbenchAgentError, match="system_agent_not_ready"):
        provider.ensure_workbench_main("tenant-a")


def test_release_state_rejects_unexpected_tool_and_invalid_skills(monkeypatch):
    provider = _provider()
    existing = _draft(provider)
    monkeypatch.setattr(provider, "_find_available_tool", lambda *_args, **_kwargs: {"tool_id": 9})
    monkeypatch.setattr(
        module,
        "query_tool_instances_by_agent_id",
        lambda *_args, **_kwargs: [{"tool_id": 10, "enabled": True}],
    )
    assert provider._release_state_matches(existing, "tenant-a") is False

    monkeypatch.setattr(module, "query_tool_instances_by_agent_id", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        module.skill_db,
        "query_skill_instances_by_agent_id",
        lambda *_args, **_kwargs: [{"skill_id": 1, "enabled": True}],
    )
    monkeypatch.setattr(module.skill_db, "get_skill_by_id", lambda *_args: None)
    assert provider._release_state_matches(existing, "tenant-a") is False

    monkeypatch.setattr(
        module.skill_db,
        "get_skill_by_id",
        lambda *_args: {"source": "official", "name": "unknown"},
    )
    assert provider._release_state_matches(existing, "tenant-a") is False


def test_release_state_rejects_editable_field_drift():
    provider = _provider()
    existing = _draft(provider, display_name="Changed")

    assert provider._release_state_matches(existing, "tenant-a") is False


def test_official_skill_base_name_accepts_numeric_import_alias():
    assert _provider()._official_skill_base_name("docx_12") == "docx"


def test_find_available_tool_required_and_optional(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(module, "query_all_tools", lambda _tenant: [])

    assert provider._find_available_tool("missing", "tenant-a", required=False) is None
    with pytest.raises(WorkbenchAgentError, match="Required Tool is unavailable"):
        provider._find_available_tool("missing", "tenant-a")


@pytest.mark.parametrize(
    "draft",
    [
        {"agent_id": 17, "current_version_no": 0},
        {"agent_id": 17, "current_version_no": 2},
    ],
)
def test_resolve_published_ref_rejects_unready_snapshot(monkeypatch, draft):
    provider = _provider()
    monkeypatch.setattr(module, "search_system_agent", lambda *_args, **_kwargs: None)

    with pytest.raises(WorkbenchAgentError, match="system_agent_not_ready"):
        provider._resolve_published_ref("tenant-a", draft)


@pytest.mark.parametrize("tenant_id", ["", "   "])
def test_validate_tenant_rejects_blank_value(tenant_id):
    with pytest.raises(ValueError, match="tenant_id is required"):
        _provider()._validate_tenant_id(tenant_id)


def test_invalid_semantic_version_is_not_newer():
    assert _provider()._is_newer_release("not-a-version") is False


def test_convenience_entrypoint_delegates(monkeypatch):
    expected = module.SystemAgentRef("tenant-a", module.WORKBENCH_MAIN_SYSTEM_KEY, 17, 2)
    ensure = MagicMock(return_value=expected)
    monkeypatch.setattr(module.system_agent_provider, "ensure_workbench_main", ensure)

    assert module.ensure_workbench_main_agent("tenant-a", "user-a", "en") == expected
    ensure.assert_called_once_with("tenant-a", "user-a", locale="en")
