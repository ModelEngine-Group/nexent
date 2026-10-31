# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deployment checkpoint, private snapshot and retry contracts."""

import argparse
import base64
import hashlib
import json

import pytest

from deploy.sql.tools.supabase_to_postgres import migrate_docker as migration
from deploy.sql.tools.supabase_to_postgres.migrate_docker import (
    _run_worker,
    _source_target,
    deployment_status,
)


@pytest.fixture
def upgrade(tmp_path, mocker, monkeypatch):
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    args = argparse.Namespace(deployment="docker", namespace="nexent", database_target="owned-target",
                              config_target="owned-config", state_dir=tmp_path, env_file=tmp_path / ".env",
                              source_container=None, deploy_phase="prepare", wait_timeout=1)
    checksum = hashlib.sha256((migration.ROOT / "deploy/sql/migrations" / migration.AUTH_SQL).read_bytes()).hexdigest()
    status = {"history": {}, "pending": 0, "legacy_logins": False}
    mocker.patch.object(migration, "deployment_status", return_value=status)
    source = mocker.patch.object(migration, "_source_target", return_value=None)
    worker = mocker.patch.object(migration, "_run_worker", return_value={"inserted": 0})
    cleanup = mocker.patch.object(migration, "cleanup_source_stack")
    return args, checksum, status, source, worker, cleanup


def checkpoint(status, checksum, *markers):
    status["history"].update({marker: {"checksum": checksum} for marker in markers})


def test_fresh_install_uses_empty_snapshot_then_records_data_and_cleanup(upgrade):
    args, checksum, status, _, worker, cleanup = upgrade
    assert migration.automatic_upgrade(args)["source"] == 0
    snapshot = next(args.state_dir.glob("*.json"))
    assert json.loads(snapshot.read_text())["rows"] == []
    checkpoint(status, checksum, migration.AUTH_SQL)
    args.deploy_phase = "apply"
    migration.automatic_upgrade(args)
    assert [call.args[1]["action"] for call in worker.call_args_list] == ["apply", "cleanup"]
    cleanup.assert_not_called()
    assert not snapshot.exists()


def test_completed_upgrade_skips_source_and_removes_stale_snapshot(upgrade):
    args, checksum, status, source, worker, _ = upgrade
    migration.automatic_upgrade(args)
    checkpoint(status, checksum, migration.AUTH_SQL, migration.DATA_MARKER, migration.CLEANUP_MARKER)
    source.reset_mock()
    assert migration.automatic_upgrade(args) == {"automatic": True, "skipped": True}
    source.assert_not_called()
    worker.assert_not_called()
    assert not list(args.state_dir.glob("*.json"))


@pytest.mark.parametrize("field", ["pending", "legacy_logins"])
def test_missing_historical_source_fails_before_replacement(upgrade, field):
    args, _, status, _, worker, _ = upgrade
    status[field] = 1
    with pytest.raises(migration.MigrationSetupError, match="original Supabase"):
        migration.automatic_upgrade(args)
    worker.assert_not_called()
    assert not list(args.state_dir.glob("*.json"))


def test_prepare_retry_reuses_snapshot_and_rejects_different_target(upgrade):
    args, _, _, source, _, _ = upgrade
    migration.automatic_upgrade(args)
    source.reset_mock()
    assert migration.automatic_upgrade(args)["retained"]
    source.assert_not_called()
    args.database_target = "different"
    with pytest.raises(migration.MigrationSetupError, match="different deployment"):
        migration.automatic_upgrade(args)


@pytest.mark.parametrize("failure", ["import", "cleanup"])
def test_failed_apply_retains_snapshot_and_only_cleans_after_commit(upgrade, failure, mocker):
    args, checksum, status, source, worker, cleanup = upgrade
    source.return_value = {"target": "supabase-db", "configuration": {"owned": True}}
    # No actual source I/O is allowed in this unit test.
    mocker.patch.object(migration, "source_snapshot", return_value=[])
    migration.automatic_upgrade(args)
    checkpoint(status, checksum, migration.AUTH_SQL)
    args.deploy_phase = "apply"
    if failure == "import":
        worker.side_effect = migration.MigrationConflict("conflict")
    else:
        cleanup.side_effect = migration.MigrationSetupError("cleanup failed")
    with pytest.raises((migration.MigrationConflict, migration.MigrationSetupError)):
        migration.automatic_upgrade(args)
    assert list(args.state_dir.glob("*.json"))
    assert worker.call_count == 1
    assert cleanup.call_count == (failure == "cleanup")
    worker.side_effect = cleanup.side_effect = None
    migration.automatic_upgrade(args)
    assert not list(args.state_dir.glob("*.json"))


def test_sql_success_does_not_skip_import_and_timeout_preserves_snapshot(upgrade, mocker):
    args, checksum, status, _, worker, _ = upgrade
    migration.automatic_upgrade(args)
    args.deploy_phase = "apply"
    mocker.patch.object(migration.time, "monotonic", side_effect=[0, 2, 3])
    with pytest.raises(migration.MigrationSetupError, match="timed out"):
        migration.automatic_upgrade(args)
    worker.assert_not_called()
    checkpoint(status, checksum, migration.AUTH_SQL)
    migration.automatic_upgrade(args)
    assert worker.call_args_list[0].args[1]["action"] == "apply"


def test_apply_without_prepare_is_rejected(upgrade):
    args = upgrade[0]
    args.deploy_phase = "apply"
    with pytest.raises(migration.MigrationSetupError, match="snapshot is missing"):
        migration.automatic_upgrade(args)


def test_source_psql_uses_exported_password_over_container_and_sends_it_on_stdin(upgrade, mocker):
    args = upgrade[0]
    mocker.patch.object(migration, "_database_environment", return_value={"POSTGRES_PASSWORD": "old", "PGPORT": "5436"})
    execute = mocker.patch.object(migration, "_exec", return_value="[]")
    migration._psql(args, "source", "SELECT 1;", {"SUPABASE_POSTGRES_PASSWORD": "exported"}, source=True)
    _, _, command, data = execute.call_args.args
    assert "exported" not in str(command) and "old" not in str(command)
    assert "5436" in command
    assert data == base64.b64encode(b"exported").decode() + "\nSELECT 1;"


def test_kubernetes_storage_is_backed_up_and_retained_before_rollout(upgrade, mocker):
    args = upgrade[0]
    args.deployment = "kubernetes"
    command = mocker.patch.object(migration, "_command", side_effect=[
        json.dumps({"spec": {"volumeName": "owned-pv"}}),
        json.dumps({"spec": {"persistentVolumeReclaimPolicy": "Delete"}}), "patched"])
    path = args.state_dir / "snapshot.json"
    migration._preserve_source_storage(args, {"target": "owned-source"}, path)
    assert json.loads((args.state_dir / "snapshot-storage.json").read_text())["claim"]["spec"]["volumeName"] == "owned-pv"
    assert command.call_args.args[0] == ["kubectl", "patch", "pv", "owned-pv", "--type=merge", "-p", '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}']


def test_remote_source_never_removes_local_containers(upgrade, mocker):
    args, checksum, status, source, _, cleanup = upgrade
    source.return_value = {"remote": True}
    mocker.patch.object(migration, "source_snapshot", return_value=[])
    migration.automatic_upgrade(args)
    checkpoint(status, checksum, migration.AUTH_SQL)
    args.deploy_phase = "apply"
    migration.automatic_upgrade(args)
    cleanup.assert_not_called()


def test_explicit_remote_host_does_not_discover_unrelated_local_sources(upgrade, mocker):
    args = upgrade[0]
    docker = mocker.patch.object(migration, "_docker")
    assert _source_target(args, {"SUPABASE_POSTGRES_HOST": "old-db.example"}) == {"remote": True}
    docker.assert_not_called()


def test_command_preserves_stdin_newlines_on_windows(mocker):
    run = mocker.patch.object(migration.subprocess, "run", return_value=argparse.Namespace(returncode=0, stdout=b"ready\n"))
    assert migration._command(["owned-test"], data="line1\nline2\n") == "ready"
    assert run.call_args.kwargs["input"] == b"line1\nline2\n"
    assert "text" not in run.call_args.kwargs


def test_kubernetes_exec_uses_selected_namespace_and_stdin(upgrade, mocker):
    args = upgrade[0]
    args.deployment = "kubernetes"
    args.namespace = "owned-namespace"
    command = mocker.patch.object(migration, "_command")
    migration._exec(args, "owned-pod", ["python", "-c", "pass"], "private-input")
    command.assert_called_once_with(["kubectl", "--namespace", "owned-namespace", "exec", "-i",
                                     "deployment/owned-pod", "--", "python", "-c", "pass"], data="private-input")


def test_status_only_accepts_completed_history_and_counts_pending_accounts(upgrade, mocker):
    args = upgrade[0]
    rows = [{"migration_id": migration.AUTH_SQL, "status": "baselined", "checksum": "sql"},
            {"migration_id": migration.DATA_MARKER, "status": "failed", "checksum": "data"}]
    psql = mocker.patch.object(migration, "_psql", return_value=json.dumps(rows) + '\n{"pending":2}\n{"legacy_logins":true}')
    status = deployment_status(args, {})
    assert status == {"history": {migration.AUTH_SQL: rows[0]}, "pending": 2, "legacy_logins": True}
    assert "auth.audit_log_entries" not in psql.call_args.args[2]


def test_source_snapshot_keeps_provider_binding_in_readonly_transaction(upgrade, mocker):
    args = upgrade[0]
    output = mocker.patch.object(migration, "_psql", return_value='[{"id":"one"},{"id":"two"}]\n[{"user_id":"one","provider":"github"}]')
    rows = migration.source_snapshot(args, {}, {"target": "source"})
    assert rows[0]["source_provider_identities"] == [{"user_id": "one", "provider": "github"}]
    assert rows[1]["source_provider_identities"] == []
    assert "REPEATABLE READ READ ONLY" in output.call_args.args[2]
    assert output.call_args.kwargs == {"source": True}


def test_worker_reports_sanitized_conflict_and_transports_payload_on_stdin(upgrade, mocker):
    args = upgrade[0]
    execute = mocker.patch.object(migration, "_exec", return_value='{"migration_error":"Target account conflicts with a source identity"}')
    with pytest.raises(migration.MigrationConflict, match="Target account conflicts"):
        _run_worker(args, {"action": "apply", "rows": [{"private": "credential"}]})
    command, payload = execute.call_args.args[2:]
    assert "credential" not in str(command)
    assert json.loads(payload)["job"]["rows"] == [{"private": "credential"}]
