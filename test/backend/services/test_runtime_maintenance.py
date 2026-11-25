# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import ANY, call
from urllib.parse import parse_qs, urlsplit

import pytest

from infrastructure.rdb import client
from management import maintenance


@pytest.fixture
def maintenance_calls(mocker):
    calls = mocker.Mock()
    calls.open_session.return_value = calls.session
    calls.session.scalar.return_value = True
    mocker.patch.object(client.db_client, "session_maker", calls.open_session)
    mocker.patch.object(maintenance, "recover_runtime_tasks", calls.recover)
    mocker.patch.object(maintenance, "recover_expired_executions", calls.recover_agentos)
    mocker.patch.object(maintenance, "fail_detecting_models_on_startup", calls.recover_models)
    mocker.patch.object(maintenance, "cleanup_orphaned_agent_workspaces", calls.cleanup)
    return calls


def test_runtime_must_be_paused_before_opening_transaction(maintenance_calls):
    calls = maintenance_calls
    calls.check_paused.side_effect = RuntimeError("Runtime is running")

    with pytest.raises(RuntimeError, match="Runtime is running"):
        maintenance.run_runtime_maintenance(calls.check_paused)

    assert calls.mock_calls == [call.check_paused()]


def test_deployment_lock_contention_prevents_repair(maintenance_calls):
    calls = maintenance_calls
    calls.session.scalar.return_value = False

    with pytest.raises(RuntimeError, match="Another process holds the Runtime deployment lock"):
        maintenance.run_runtime_maintenance(calls.check_paused)

    assert calls.mock_calls == [
        call.check_paused(),
        call.open_session(),
        call.session.scalar(ANY),
        call.session.rollback(),
        call.session.close(),
    ]


def test_pause_is_rechecked_under_deployment_lock_before_repair(maintenance_calls):
    calls = maintenance_calls
    calls.check_paused.side_effect = [None, RuntimeError("Runtime is running")]

    with pytest.raises(RuntimeError, match="Runtime is running"):
        maintenance.run_runtime_maintenance(calls.check_paused)

    assert calls.mock_calls == [
        call.check_paused(),
        call.open_session(),
        call.session.scalar(ANY),
        call.check_paused(),
        call.session.rollback(),
        call.session.close(),
    ]


def test_repair_rechecks_pause_before_committing(maintenance_calls):
    calls = maintenance_calls

    maintenance.run_runtime_maintenance(calls.check_paused)

    assert str(calls.session.scalar.call_args.args[0]) == (
        "SELECT pg_try_advisory_xact_lock(hashtextextended('nexent:runtime:deployment', 0))"
    )
    assert calls.mock_calls == [
        call.check_paused(),
        call.open_session(),
        call.session.scalar(ANY),
        call.check_paused(),
        call.recover(db_session=calls.session),
        call.recover_agentos(offline_session=calls.session),
        call.recover_models(db_session=calls.session),
        call.cleanup(strict=True),
        call.check_paused(),
        call.session.commit(),
        call.session.close(),
    ]


def test_cleanup_failure_rolls_back_database_repair(maintenance_calls):
    calls = maintenance_calls
    calls.cleanup.side_effect = OSError("working directory unavailable")

    with pytest.raises(OSError, match="working directory unavailable"):
        maintenance.run_runtime_maintenance(calls.check_paused)

    assert calls.check_paused.call_count == 2
    calls.session.commit.assert_not_called()
    calls.session.rollback.assert_called_once_with()
    calls.session.close.assert_called_once_with()


def test_final_pause_check_failure_rolls_back_database_repair(maintenance_calls):
    calls = maintenance_calls
    calls.check_paused.side_effect = [None, None, RuntimeError("Runtime is running")]

    with pytest.raises(RuntimeError, match="Runtime is running"):
        maintenance.run_runtime_maintenance(calls.check_paused)

    calls.cleanup.assert_called_once_with(strict=True)
    calls.session.commit.assert_not_called()
    calls.session.rollback.assert_called_once_with()
    calls.session.close.assert_called_once_with()


def _paused_deployment(name="nexent-runtime", *, release="nexent", replicas=0):
    return {
        "metadata": {
            "name": name,
            "generation": 2,
            "annotations": {"meta.helm.sh/release-name": release},
        },
        "spec": {"replicas": replicas},
        "status": {"observedGeneration": 2},
    }


def test_kubernetes_guard_lists_application_deployments_and_pods(mocker):
    deployments = [_paused_deployment(), _paused_deployment("nexent-config")]
    read = mocker.Mock(side_effect=[{"items": deployments}, {"items": []}])

    maintenance.require_paused_kubernetes_runtime(read, "scratch", "nexent")

    requests = [urlsplit(request.args[0]) for request in read.call_args_list]
    assert [request.path for request in requests] == [
        "/apis/apps/v1/namespaces/scratch/deployments",
        "/api/v1/namespaces/scratch/pods",
    ]
    for request in requests:
        assert parse_qs(request.query) == {
            "labelSelector": [
                "app in (nexent-runtime,nexent-config,nexent-northbound,nexent-mcp,nexent-data-process)"
            ],
        }


@pytest.mark.parametrize(
    ("deployments", "message"),
    [
        ({}, "Could not verify all application Deployments"),
        ({"items": [_paused_deployment()], "metadata": {"continue": "page-2"}},
         "Could not verify all application Deployments"),
        ({"items": [_paused_deployment("nexent-config")]},
         "Runtime Deployment does not belong to this Helm release"),
        ({"items": [_paused_deployment(release="other")]}, "nexent-runtime does not belong to this Helm release"),
        ({"items": [_paused_deployment(), _paused_deployment("nexent-config", replicas=1)]},
         "nexent-config must have zero replicas"),
    ],
)
def test_kubernetes_guard_rejects_incomplete_or_live_deployments(mocker, deployments, message):
    read = mocker.Mock(return_value=deployments)

    with pytest.raises(RuntimeError, match=message):
        maintenance.require_paused_kubernetes_runtime(read, "scratch", "nexent")

    read.assert_called_once()


@pytest.mark.parametrize("status", [{}, {"observedGeneration": 1}, {"observedGeneration": 2, "replicas": 1}])
def test_kubernetes_guard_requires_reconciled_zero_even_with_no_pods(mocker, status):
    deployment = _paused_deployment()
    deployment["status"] = status
    read = mocker.Mock(side_effect=[{"items": [deployment]}, {"items": []}])

    with pytest.raises(RuntimeError, match="nexent-runtime has not reconciled to zero"):
        maintenance.require_paused_kubernetes_runtime(read, "scratch", "nexent")

    read.assert_called_once()


@pytest.mark.parametrize("pods", [
    {},
    {"items": [], "metadata": {"continue": "page-2"}},
    {"items": [{"metadata": {"deletionTimestamp": "2026-11-19T00:00:00Z"}}]},
])
def test_kubernetes_guard_requires_all_business_pods_to_exit(mocker, pods):
    read = mocker.Mock(side_effect=[{"items": [_paused_deployment()]}, pods])

    with pytest.raises(RuntimeError, match="requires all selected business Pods to exit"):
        maintenance.require_paused_kubernetes_runtime(read, "scratch", "nexent")


def test_kubernetes_guard_rejects_invalid_namespace_without_request(mocker):
    read = mocker.Mock()

    with pytest.raises(ValueError, match="Invalid Kubernetes namespace"):
        maintenance.require_paused_kubernetes_runtime(read, "scratch/other", "nexent")

    read.assert_not_called()
