# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Separate initialization/publication contracts; real SQL consolidation is proved in D5."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from contracts.agent import SystemAgentRef
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import WorkbenchAgentError
from management.services.agent import system_initialize as initialize
from management.services.agent import system_release as release


@pytest.fixture
def deployment(mocker):
    events = []
    session = MagicMock()

    @contextmanager
    def transaction():
        events.append("begin")
        try:
            yield session
        except Exception:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    for module in (release, initialize):
        mocker.patch.object(module, "get_db_session", transaction)
        mocker.patch.object(module, "lock_system_agent_release", side_effect=lambda db, key: events.append(key))
    return events, session


def test_publisher_only_reads_and_publishes_workbench(deployment, mocker):
    events, session = deployment
    load = mocker.patch.object(release, "load_system_agent", return_value={"agent_id": 77})
    publish = mocker.patch.object(release, "_publish_workbench", return_value=SystemAgentRef(ASSET_OWNER_TENANT_ID, "workbench_main", 77, 1))
    init = mocker.patch.object(initialize, "initialize_system_agents")
    assert release.release_system_agents() == {"workbench_main": 77, "workbench_version": 1}
    assert events == ["begin", "workbench_main", "commit"]
    load.assert_called_once_with(session, "workbench_main")
    publish.assert_called_once()
    init.assert_not_called()
    assert not hasattr(release, "consolidate_system_agent")
    assert not hasattr(release, "initialize_nl2agent_identity")


def test_publisher_rejects_missing_shared_draft(deployment, mocker):
    events, session = deployment
    mocker.patch.object(release, "load_system_agent", return_value=None)
    write = mocker.patch.object(release, "write_system_agent_release")
    with pytest.raises(WorkbenchAgentError, match="system_agent_not_ready"):
        release.release_system_agents()
    write.assert_not_called()
    assert events[-1] == "rollback"


@pytest.mark.parametrize("existing", [None, {"agent_id": 77}])
def test_initializer_creates_only_missing_shared_drafts(deployment, mocker, existing):
    events, session = deployment
    mocker.patch.object(initialize, "has_legacy_workbench_agents", return_value=False)
    prepare = mocker.patch.object(initialize, "prepare_shared_resources", return_value=([{"tool_id": 1}], [{"skill_id": 2}]))
    mocker.patch.object(initialize, "load_system_agent", return_value=existing)
    create = mocker.patch.object(initialize, "create_workbench_draft", return_value=77)
    bindings = mocker.patch.object(initialize, "replace_workbench_draft_bindings")
    publish = mocker.patch.object(release, "release_system_agents")
    assert initialize.initialize_system_agents() == {"workbench_main": 77}
    assert events == ["begin", "workbench_main", "commit"]
    prepare.assert_called_once()
    publish.assert_not_called()
    assert not hasattr(initialize, "initialize_nl2agent_identity")
    assert not hasattr(initialize, "initialize_nl2skill_identity")
    assert all(call.args[1] == "workbench_main" for call in initialize.load_system_agent.call_args_list)
    if existing:
        create.assert_not_called()
        bindings.assert_not_called()
    else:
        create.assert_called_once()
        bindings.assert_called_once_with(session, 77, [{"tool_id": 1}], [{"skill_id": 2}])


def test_initializer_rejects_unmigrated_tenant_data(deployment, mocker):
    events, _ = deployment
    mocker.patch.object(initialize, "has_legacy_workbench_agents", return_value=True)
    prepare = mocker.patch.object(initialize, "prepare_shared_resources")
    with pytest.raises(ValueError, match="SQL migration"):
        initialize.initialize_system_agents()
    prepare.assert_not_called()
    assert events[-1] == "rollback"


def test_failed_initialization_never_commits(deployment, mocker):
    events, _ = deployment
    mocker.patch.object(initialize, "has_legacy_workbench_agents", return_value=False)
    mocker.patch.object(initialize, "prepare_shared_resources", side_effect=RuntimeError("unavailable"))
    with pytest.raises(RuntimeError, match="unavailable"):
        initialize.initialize_system_agents()
    assert events[-1] == "rollback"
    assert "commit" not in events


def test_initialization_prepares_shared_local_catalog_and_official_files(mocker, tmp_path):
    from management.services.tool import configuration
    from management.services.skill import transfer, files
    from management.db.skill import repository as skill_repository
    from management.db.tool import repository

    manager = mocker.patch.object(files, "get_skill_manager").return_value
    manager.resolve_skill_dir.return_value = str(tmp_path / "pdf")
    mocker.patch.object(skill_repository, "list_skills", return_value=[])
    local_tools = [object()]
    scan = mocker.patch.object(configuration, "get_local_tools", return_value=local_tools)
    save = mocker.patch.object(repository, "update_tool_table_from_scan_tool_list")
    install = mocker.patch.object(transfer, "install_skills_from_zip_for_tenant")
    provider = MagicMock()
    provider.release_manifest.official_skill_names = ("pdf",)
    provider.get_workbench_default_skills.return_value = [{"skill_id": 1}]
    provider.get_workbench_default_tools.return_value = [{"tool_id": 2}]
    assert initialize.prepare_shared_resources(provider) == ([{"tool_id": 2}], [{"skill_id": 1}])
    scan.assert_called_once_with()
    save.assert_called_once_with(ASSET_OWNER_TENANT_ID, "system", local_tools)
    install.assert_called_once_with(skill_names=["pdf"], tenant_id=ASSET_OWNER_TENANT_ID, user_id="system")


def test_missing_migrated_skill_files_abort_initialization(mocker, tmp_path):
    from management.services.skill import transfer, files
    from management.services.tool import configuration
    from management.db.skill import repository as skill_repository
    from management.db.tool import repository as tool_repository
    mocker.patch.object(configuration, "get_local_tools", return_value=[])
    mocker.patch.object(tool_repository, "update_tool_table_from_scan_tool_list")
    mocker.patch.object(transfer, "install_skills_from_zip_for_tenant", return_value=[])
    manager = mocker.patch.object(files, "get_skill_manager").return_value
    manager.resolve_skill_dir.return_value = str(tmp_path / "missing")
    mocker.patch.object(skill_repository, "list_skills", return_value=[{"name": "pdf", "source": "official"}])
    provider = MagicMock()
    provider.release_manifest.official_skill_names = ("pdf",)
    with pytest.raises(ValueError, match="files are unavailable"):
        initialize.prepare_shared_resources(provider)
