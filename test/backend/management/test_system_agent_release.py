# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Publication gates reject drift and downgrade, and retain explicit snapshot selection."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from contracts.agent import SystemAgentRef
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.errors.exceptions import WorkbenchAgentError
from management.services.agent import system_release as service


@pytest.fixture
def release(mocker):
    session = MagicMock()
    provider = MagicMock()
    provider.release_manifest = SimpleNamespace(system_revision="2.8.2")
    provider._editable_fields.return_value = {"name": "Workbench", "enabled": True}
    provider._is_newer_release.return_value = True
    latest = mocker.patch.object(service, "latest_workbench_release")
    next_version = mocker.patch.object(service, "next_workbench_version", return_value=4)
    write = mocker.patch.object(service, "write_system_agent_release")
    return SimpleNamespace(session=session, provider=provider, latest=latest, next=next_version, write=write)


def test_same_revision_reuses_published_snapshot_without_new_version(release):
    release.latest.return_value = {"name": "Workbench", "enabled": True}
    result = service._publish_workbench(release.session, release.provider, {
        "agent_id": 77, "system_revision": "2.8.2", "current_version_no": 3,
    })
    assert result == SystemAgentRef(ASSET_OWNER_TENANT_ID, "workbench_main", 77, 3)
    release.latest.assert_called_once_with(release.session, 77, "2.8.2")
    release.next.assert_not_called()
    release.write.assert_not_called()


@pytest.mark.parametrize("published", [None, {"name": "tampered", "enabled": True}, {"name": "Workbench", "enabled": False}])
def test_same_revision_rejects_missing_or_drifted_snapshot(release, published):
    release.latest.return_value = published
    with pytest.raises(WorkbenchAgentError) as caught:
        service._publish_workbench(release.session, release.provider, {
            "agent_id": 77, "system_revision": "2.8.2", "current_version_no": 3,
        })
    assert caught.value.code == "system_agent_drift_detected"
    release.write.assert_not_called()


def test_publish_rejects_older_application_revision(release):
    release.provider._is_newer_release.return_value = False
    with pytest.raises(WorkbenchAgentError) as caught:
        service._publish_workbench(release.session, release.provider, {
            "agent_id": 77, "system_revision": "2.9.0",
        })
    assert caught.value.code == "system_agent_revision_ahead"
    release.provider._is_newer_release.assert_called_once_with("2.9.0")
    release.next.assert_not_called()
    release.write.assert_not_called()


@pytest.mark.parametrize("previous", [None, "2.8.1"])
def test_publish_allocates_next_version_and_passes_manifest_fields(release, previous):
    existing = {"agent_id": 77, "system_revision": previous}
    result = service._publish_workbench(release.session, release.provider, existing)
    assert result == SystemAgentRef(ASSET_OWNER_TENANT_ID, "workbench_main", 77, 4)
    release.next.assert_called_once_with(release.session, 77)
    release.write.assert_called_once_with(
        release.session, existing=existing, system_key="workbench_main", revision="2.8.2",
        fields={"name": "Workbench", "enabled": True}, version_no=4,
    )
    if previous is None:
        release.provider._is_newer_release.assert_not_called()


def test_release_failure_reaches_transaction_context_and_caller(mocker):
    context = mocker.patch.object(service, "get_db_session").return_value
    context.__exit__.return_value = False
    mocker.patch.object(service, "SystemAgentProvider")
    mocker.patch.object(service, "lock_system_agent_release")
    mocker.patch.object(service, "load_system_agent", return_value={"agent_id": 77})
    failure = RuntimeError("snapshot insert failed")
    mocker.patch.object(service, "_publish_workbench", side_effect=failure)
    with pytest.raises(RuntimeError, match="snapshot insert failed"):
        service.release_system_agents()
    assert context.__exit__.call_args.args[:2] == (RuntimeError, failure)


def test_version_selection_uses_same_identity_lock_and_transaction(mocker):
    context = mocker.patch.object(service, "get_db_session").return_value
    lock = mocker.patch.object(service, "lock_system_agent_release")
    select = mocker.patch.object(service, "select_workbench_snapshot")
    service.select_workbench_version(2)
    lock.assert_called_once_with(context.__enter__.return_value, "workbench_main")
    select.assert_called_once_with(context.__enter__.return_value, 2)
    context.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("version", [None, 2])
def test_command_dispatches_publication_or_snapshot_selection(mocker, capsys, version):
    mocker.patch("sys.argv", ["system_release"] + ([] if version is None else ["--select-workbench-version", "2"]))
    publish = mocker.patch.object(service, "release_system_agents", return_value={"workbench_main": 77, "workbench_version": 4})
    select = mocker.patch.object(service, "select_workbench_version")
    service.main()
    if version is None:
        publish.assert_called_once_with()
        select.assert_not_called()
        assert json.loads(capsys.readouterr().out) == {"workbench_main": 77, "workbench_version": 4}
    else:
        select.assert_called_once_with(2)
        publish.assert_not_called()
        assert capsys.readouterr().out == ""
