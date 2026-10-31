# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Kubernetes-specific deployment startup, storage preservation and routing."""

import argparse
import json

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate_docker as migrate
from deploy.sql.tools.supabase_to_postgres import migrate_k8s


@pytest.fixture
def args():
    return argparse.Namespace(namespace="isolated", source_container=None, wait_timeout=30)


@pytest.mark.parametrize("replicas", [0, 1])
def test_source_scales_only_stopped_deployment_and_waits(args, mocker, replicas):
    command = mocker.patch.object(migrate, "_command", return_value=json.dumps({"spec": {"replicas": replicas}}))
    assert migrate_k8s.source_target(args, {})["target"] == "nexent-supabase-db"
    commands = [call.args[0] for call in command.call_args_list]
    assert any("scale" in cmd for cmd in commands) == (replicas == 0)
    assert commands[-1] == ["kubectl", "--namespace", "isolated", "rollout", "status", "deployment/nexent-supabase-db", "--timeout=30s"]


def test_missing_source_is_not_recreated(args, mocker):
    command = mocker.patch.object(migrate, "_command", return_value="")
    assert migrate_k8s.source_target(args, {}) is None
    command.assert_called_once()


def test_external_source_does_not_touch_cluster_workloads(args, mocker):
    command = mocker.patch.object(migrate, "_command")
    assert migrate_k8s.source_target(args, {"SUPABASE_POSTGRES_HOST": "external"}) == {"remote": True}
    command.assert_not_called()


def test_actual_custom_pvc_is_archived_before_reclaim_policy_change(args, mocker, tmp_path):
    source = {"deployment": {"spec": {"template": {"spec": {"volumes": [
        {"persistentVolumeClaim": {"claimName": "custom-db-data"}}, {"emptyDir": {}}]}}}}}
    command = mocker.patch.object(migrate, "_command", side_effect=[
        json.dumps({"spec": {"volumeName": "custom-pv"}}),
        json.dumps({"metadata": {"name": "custom-pv"}, "spec": {"persistentVolumeReclaimPolicy": "Delete"}}), ""])
    migrate_k8s.preserve_storage(args, source, tmp_path / "snapshot.json")
    saved = json.loads((tmp_path / "snapshot-storage.json").read_text())
    assert saved["storage"][0]["claim"]["spec"]["volumeName"] == "custom-pv"
    assert command.call_args_list[0].args[0][5] == "custom-db-data"
    assert command.call_args.args[0][0:4] == ["kubectl", "patch", "pv", "custom-pv"]


def test_ephemeral_source_storage_blocks_upgrade(args, tmp_path):
    with pytest.raises(migrate.MigrationSetupError, match="no persistent claim"):
        migrate_k8s.preserve_storage(args, {"deployment": {"spec": {"template": {"spec": {"volumes": []}}}}}, tmp_path / "state.json")


def test_cluster_identity_is_bound_to_retry(args, mocker):
    mocker.patch.object(migrate, "_command", return_value='{"clusters":[{"cluster":{"server":"https://cluster"}}]}')
    automatic = mocker.patch.object(migrate, "automatic_upgrade")
    migrate_k8s.upgrade(args)
    assert len(args.cluster_identity) == 64
    automatic.assert_called_once_with(args, source_resolver=migrate_k8s.source_target, storage_preserver=migrate_k8s.preserve_storage)


def test_entry_routes_only_to_kubernetes_upgrade(mocker):
    mocker.patch.object(migrate_k8s.sys, "argv", ["migrate_k8s.py", "--deploy-phase", "prepare"])
    main = mocker.patch.object(migrate, "main", return_value=0)
    assert migrate_k8s.main() == 0
    assert migrate_k8s.sys.argv[-2:] == ["--deployment", "kubernetes"]
    main.assert_called_once_with(upgrade=migrate_k8s.upgrade)
