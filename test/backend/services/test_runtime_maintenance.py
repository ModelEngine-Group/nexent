# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from contextlib import nullcontext
from datetime import datetime
from unittest.mock import Mock, call

import pytest

from management import maintenance


EPOCH = "9d323186-23f6-4ab6-b0ab-8990661e6320"
OWNER = "maintenance-job:8b3af41d6d5d4878bafba688a7875b43"


@pytest.fixture
def maintenance_calls(monkeypatch):
    session = object()
    calls = Mock()
    monkeypatch.setattr(maintenance, "get_db_session", lambda: nullcontext(session))
    monkeypatch.setattr(maintenance, "repository", calls.repository)
    monkeypatch.setattr(maintenance, "recover_runtime_tasks", calls.recover)
    monkeypatch.setattr(maintenance, "recover_expired_executions", calls.recover_agentos)
    monkeypatch.setattr(maintenance, "fail_detecting_models_on_startup", calls.recover_models)
    monkeypatch.setattr(maintenance, "cleanup_orphaned_agent_workspaces", calls.cleanup)
    calls.repository.maintenance_completed_at.return_value = None
    return session, calls


def test_full_stop_is_rechecked_after_taking_maintenance_lock(maintenance_calls):
    session, calls = maintenance_calls
    calls.check_paused.side_effect = [None, RuntimeError("Runtime is running")]

    with pytest.raises(RuntimeError, match="Runtime is running"):
        maintenance.run_runtime_maintenance(EPOCH, OWNER, calls.check_paused)

    calls.repository.lock_maintenance.assert_called_once_with(session)
    calls.recover.assert_not_called()
    calls.cleanup.assert_not_called()
    calls.repository.record_maintenance_completion.assert_not_called()


def test_maintenance_already_completed_is_not_repeated(maintenance_calls):
    session, calls = maintenance_calls
    calls.repository.maintenance_completed_at.return_value = datetime(2026, 11, 19)

    assert not maintenance.run_runtime_maintenance(EPOCH, OWNER, calls.check_paused)

    calls.repository.maintenance_completed_at.assert_called_once_with(session, EPOCH)
    calls.recover.assert_not_called()
    calls.cleanup.assert_not_called()
    calls.repository.interrupt_active_executions.assert_not_called()
    calls.repository.record_maintenance_completion.assert_not_called()


def test_maintenance_checks_full_stop_again_before_publishing(maintenance_calls):
    session, calls = maintenance_calls

    assert maintenance.run_runtime_maintenance(EPOCH, OWNER, calls.check_paused)

    assert calls.mock_calls == [
        call.check_paused(EPOCH),
        call.repository.lock_maintenance(session),
        call.check_paused(EPOCH),
        call.repository.maintenance_completed_at(session, EPOCH),
        call.recover(db_session=session),
        call.recover_agentos(offline_session=session),
        call.recover_models(db_session=session),
        call.cleanup(strict=True),
        call.check_paused(EPOCH),
        call.repository.interrupt_active_executions(session),
        call.repository.record_maintenance_completion(session, EPOCH, OWNER),
    ]


def test_cleanup_failure_does_not_publish_epoch(maintenance_calls):
    _, calls = maintenance_calls
    calls.cleanup.side_effect = OSError("working directory unavailable")

    with pytest.raises(OSError):
        maintenance.run_runtime_maintenance(EPOCH, OWNER, calls.check_paused)

    calls.repository.interrupt_active_executions.assert_not_called()
    calls.repository.record_maintenance_completion.assert_not_called()


def test_runtime_startup_rejects_an_unfinished_epoch(maintenance_calls):
    session, calls = maintenance_calls

    with pytest.raises(RuntimeError, match="does not have a completed maintenance batch"):
        maintenance.require_completed_runtime_maintenance(EPOCH)

    calls.repository.maintenance_completed_at.assert_called_once_with(session, EPOCH)


@pytest.mark.parametrize("epoch", ["", "invalid", EPOCH.upper()])
def test_runtime_startup_rejects_invalid_epoch_before_querying_database(maintenance_calls, epoch):
    _, calls = maintenance_calls

    with pytest.raises(ValueError, match="canonical UUID"):
        maintenance.require_completed_runtime_maintenance(epoch)

    assert not calls.repository.mock_calls


def _paused_runtime():
    return {
        "metadata": {"generation": 2, "annotations": {
            "meta.helm.sh/release-name": "nexent", "nexent.io/maintenance-epoch": EPOCH,
        }},
        "spec": {"replicas": 0},
        "status": {"observedGeneration": 2},
    }


def test_kubernetes_guard_checks_paused_release_and_absence_of_runtime_pods():
    read = Mock(side_effect=[_paused_runtime(), {"items": []}])

    maintenance.require_paused_kubernetes_runtime(read, "scratch", "nexent", EPOCH)

    assert read.call_args_list == [
        call("/apis/apps/v1/namespaces/scratch/deployments/nexent-runtime"),
        call("/api/v1/namespaces/scratch/pods?labelSelector=app%3Dnexent-runtime"),
    ]


@pytest.mark.parametrize("reason", ["wrong-release", "wrong-epoch", "not-paused", "old-pod", "malformed-list"])
def test_kubernetes_guard_rejects_incomplete_or_mismatched_pause(reason):
    deployment = _paused_runtime()
    pods = {"items": []}
    if reason == "wrong-release":
        deployment["metadata"]["annotations"]["meta.helm.sh/release-name"] = "other"
    elif reason == "wrong-epoch":
        deployment["metadata"]["annotations"]["nexent.io/maintenance-epoch"] = "old"
    elif reason == "not-paused":
        deployment["spec"]["replicas"] = 1
    elif reason == "old-pod":
        pods["items"] = [{"metadata": {"deletionTimestamp": "2026-11-19T00:00:00Z"}}]
    else:
        pods = {}

    with pytest.raises(RuntimeError, match="Runtime"):
        maintenance.require_paused_kubernetes_runtime(Mock(side_effect=[deployment, pods]), "scratch", "nexent", EPOCH)


@pytest.mark.parametrize("status", [{}, {"observedGeneration": 1}, {"observedGeneration": 2, "replicas": 1}])
def test_kubernetes_guard_requires_reconciled_zero_even_with_no_pods(status):
    deployment = _paused_runtime()
    deployment["status"] = status
    read = Mock(side_effect=[deployment, {"items": []}])

    with pytest.raises(RuntimeError, match="not reconciled to zero"):
        maintenance.require_paused_kubernetes_runtime(read, "scratch", "nexent", EPOCH)

    assert read.call_count == 1
