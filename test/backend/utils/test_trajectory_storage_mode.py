# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Storage mode is an explicit registration invariant across backend readers and writers."""

import json
import runpy
from types import SimpleNamespace

import pytest
from infrastructure.observability.trajectory_io import TrajectoryConflict
from infrastructure.observability.trajectory_runtime import create_local_processor
from infrastructure.observability.trajectory_store import TrajectoryFileStore


@pytest.mark.parametrize("mode", ["single_node", "shared_directory"])
def test_registered_mode_is_idempotent_and_cannot_be_overwritten(tmp_path, mode):
    TrajectoryFileStore.provision(tmp_path, storage_mode=mode)
    marker = tmp_path / ".storage-root.json"
    original = marker.read_bytes()
    assert json.loads(original)["storage_mode"] == mode
    TrajectoryFileStore.provision(tmp_path, storage_mode=mode)
    assert marker.read_bytes() == original
    store = TrajectoryFileStore(
        tmp_path, authorize=lambda _: None, storage_mode=mode
    )
    assert store.storage_mode == mode
    other = "single_node" if mode == "shared_directory" else "shared_directory"
    with pytest.raises(TrajectoryConflict):
        TrajectoryFileStore.provision(tmp_path, storage_mode=other)
    with pytest.raises(TrajectoryConflict):
        TrajectoryFileStore(
            tmp_path, authorize=lambda _: None, storage_mode=other
        )
    assert marker.read_bytes() == original


def test_legacy_registration_is_single_node_and_is_not_silently_promoted(tmp_path):
    TrajectoryFileStore.provision(tmp_path)
    marker = tmp_path / ".storage-root.json"
    marker.write_text(json.dumps({"schema_version": 1, "unused_legacy_marker": "ignored"}))
    original = marker.read_bytes()
    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    assert store.storage_mode == "single_node"
    TrajectoryFileStore.provision(tmp_path)
    with pytest.raises(TrajectoryConflict):
        TrajectoryFileStore(
            tmp_path, authorize=lambda _: None, storage_mode="shared_directory"
        )
    assert marker.read_bytes() == original


@pytest.mark.parametrize("mode", [None, "", "shared", "other", True])
def test_invalid_mode_is_rejected_before_creating_registration(tmp_path, mode):
    with pytest.raises(ValueError, match="storage mode"):
        TrajectoryFileStore.provision(tmp_path, storage_mode=mode)
    assert list(tmp_path.iterdir()) == []


def test_each_root_open_rechecks_registered_mode(tmp_path):
    TrajectoryFileStore.provision(tmp_path)
    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    marker = tmp_path / ".storage-root.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "unused_legacy_marker": "ignored",
                "storage_mode": "shared_directory",
            }
        )
    )
    with pytest.raises(TrajectoryConflict), store._root():
        pass


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "single_node"),
        ("single_node", "single_node"),
        (" SHARED_DIRECTORY ", "shared_directory"),
    ],
)
def test_environment_mode_default_and_normalization(monkeypatch, raw, expected):
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: False)
    if raw is None:
        monkeypatch.delenv("TRAJECTORY_STORAGE_MODE", raising=False)
    else:
        monkeypatch.setenv("TRAJECTORY_STORAGE_MODE", raw)
    config = runpy.run_module(
        "contracts.constants.environment", run_name="trajectory_mode_test"
    )
    assert config["TRAJECTORY_STORAGE_MODE"] == expected


@pytest.mark.parametrize("raw", ["", "shared", "other"])
def test_environment_rejects_unsupported_modes(monkeypatch, raw):
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kwargs: False)
    monkeypatch.setenv("TRAJECTORY_STORAGE_MODE", raw)
    with pytest.raises(ValueError, match="TRAJECTORY_STORAGE_MODE"):
        runpy.run_module(
            "contracts.constants.environment", run_name="trajectory_mode_test"
        )


def test_capture_maintenance_and_query_receive_the_same_mode(tmp_path, monkeypatch):
    from contracts.constants import environment
    from ops.services.trajectory import runtime

    TrajectoryFileStore.provision(tmp_path, storage_mode="shared_directory")
    values = {
        "ENABLE_TELEMETRY": True,
        "TRAJECTORY_READ_ENABLED": True,
        "MONITORING_PROVIDER": "local_file",
        "TRAJECTORY_ROOT_DIR": str(tmp_path),

        "TRAJECTORY_STORAGE_MODE": "shared_directory",
        "TRAJECTORY_RETENTION_DAYS": 30,
        "TRAJECTORY_FLUSH_INTERVAL_MS": 200,
        "TRAJECTORY_FLUSH_BYTES": 262144,
        "TRAJECTORY_QUEUE_MAX_BYTES": 268435456,
        "TRAJECTORY_RUN_QUEUE_MAX_BYTES": 16777216,
        "TRAJECTORY_CLEANUP_ENABLED": True,
        "TRAJECTORY_CLEANUP_INTERVAL_SECONDS": 3600,
    }
    processor = create_local_processor(SimpleNamespace(**values), lambda: None)
    from ops.services.trajectory.lifecycle import create_maintenance_processor

    maintenance = create_maintenance_processor(SimpleNamespace(**values))
    assert processor.store.storage_mode == maintenance.store.storage_mode == "shared_directory"
    assert processor._maintenance_store is None
    for key, value in {
        **values,
        "TRAJECTORY_READ_ENABLED": True,

    }.items():
        monkeypatch.setattr(environment, key, value)
    monkeypatch.setattr(runtime, "_service", None)
    assert runtime.get_service().archive.store.storage_mode == "shared_directory"
    monkeypatch.setattr(runtime, "_service", None)
    monkeypatch.setattr(environment, "TRAJECTORY_STORAGE_MODE", "single_node")
    from contracts.errors.trajectory import QueryError

    with pytest.raises(QueryError) as raised:
        reader = runtime.get_service()
        reader.archive.store.authorize = lambda _: None
        reader.archive.manifest({"tenant_id": "t", "user_id": "u", "conversation_id": "123"})
    assert raised.value.status == 503 and raised.value.code == "storage_busy"


@pytest.fixture(autouse=True)
def isolated_summary_database(mocker):
    from contextlib import nullcontext
    repository=mocker.patch("management.db.trajectory.repository.ExecutionRepository")
    repository.return_value.initialize.side_effect=lambda identity:nullcontext()
    return repository
