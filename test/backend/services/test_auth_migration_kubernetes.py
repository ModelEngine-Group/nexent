# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Kubernetes source storage, isolated worker Job and exact cleanup ownership."""

import pytest

from test.backend.services.migration_shell_fixture import run_migration


@pytest.mark.parametrize("replicas", ["0", "1"])
def test_source_scales_only_stopped_deployment_and_waits(tmp_path, replicas):
    result = run_migration(tmp_path, ["--deployment", "kubernetes", "--apply"], {"FAKE_REPLICAS": replicas})
    assert result.code == 0, result.stderr
    assert any("scale" in c for c in result.commands) is (replicas == "0")
    assert any("rollout" in c and "status" in c for c in result.commands)
    assert "automountServiceAccountToken: false" in result.job
    assert "backoffLimit: 0" in result.job and "--container" in result.job
    assert not list(tmp_path.glob("nexent-account.*"))
    assert any("delete" in c and "secret" in c for c in result.commands)
    assert any("delete" in c and "job" in c for c in result.commands)


def test_missing_source_is_not_recreated(tmp_path):
    result = run_migration(tmp_path, ["--deployment", "kubernetes"], {"FAKE_SOURCE_PRESENT": "false"})
    assert result.code != 0
    assert not any("create" in c for c in result.commands)


def test_remote_source_does_not_touch_cluster_source_workloads(tmp_path):
    result = run_migration(tmp_path, ["--deployment", "kubernetes", "--apply"], {"SUPABASE_POSTGRES_HOST": "original.example"})
    assert result.code == 0, result.stderr
    assert not any("scale" in c or "patch" in c or "deployment,service" in c for c in result.commands)


def test_actual_custom_pvc_is_archived_before_reclaim_change(tmp_path):
    result = run_migration(tmp_path, ["--deployment", "kubernetes"], {"FAKE_CLAIM": "custom-data", "FAKE_VOLUME": "custom-pv"})
    assert result.code == 0, result.stderr
    backups = list((tmp_path / "backups").glob("*.yaml"))
    assert len(backups) == 3
    assert any("custom-data" in p.name and "PersistentVolumeClaim" in p.read_text() for p in backups)
    assert any("custom-pv" in p.name and "PersistentVolume" in p.read_text() for p in backups)
    patch = next(i for i,c in enumerate(result.commands) if "patch" in c)
    assert sum("yaml" in c for c in result.commands[:patch]) == 3
    assert "custom-pv" in result.commands[patch]


@pytest.mark.parametrize("values", [{"FAKE_CLAIM": ""}, {"FAKE_VOLUME": ""}])
def test_ephemeral_or_unbound_storage_blocks_upgrade(tmp_path, values):
    result = run_migration(tmp_path, ["--deployment", "kubernetes"], values)
    assert result.code != 0
    assert not any("create" in c or "patch" in c for c in result.commands)


def test_failed_job_preserves_source_and_cleans_owned_job_secret(tmp_path):
    result = run_migration(tmp_path, ["--deployment", "kubernetes", "--apply"], {"FAKE_WORKER_STATUS": "1"})
    assert result.code != 0
    assert not any("deployment,service" in c for c in result.commands)
    assert any("delete" in c and "job" in c for c in result.commands)
    assert any("delete" in c and "secret" in c for c in result.commands)
    assert not list(tmp_path.glob("nexent-account.*"))
