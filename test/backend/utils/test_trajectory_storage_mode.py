# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Storage mode is an explicit registration invariant across backend readers and writers."""

import json
import runpy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_io import TrajectoryConflict
from infrastructure.observability.trajectory_runtime import create_local_processor, main
from infrastructure.observability.trajectory_store import TrajectoryFileStore


@pytest.mark.parametrize("mode", ["single_node", "shared_directory"])
def test_registered_mode_is_idempotent_and_cannot_be_overwritten(tmp_path, mode):
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id, storage_mode=mode)
    marker = tmp_path / ".storage-root.json"
    original = marker.read_bytes()
    assert json.loads(original)["storage_mode"] == mode
    TrajectoryFileStore.provision(tmp_path, root_id, storage_mode=mode)
    assert marker.read_bytes() == original
    store = TrajectoryFileStore(
        tmp_path, root_id, authorize=lambda _: None, storage_mode=mode
    )
    assert store.storage_mode == mode
    other = "single_node" if mode == "shared_directory" else "shared_directory"
    with pytest.raises(TrajectoryConflict):
        TrajectoryFileStore.provision(tmp_path, root_id, storage_mode=other)
    with pytest.raises(TrajectoryConflict):
        TrajectoryFileStore(
            tmp_path, root_id, authorize=lambda _: None, storage_mode=other
        )
    assert marker.read_bytes() == original


def test_legacy_registration_is_single_node_and_is_not_silently_promoted(tmp_path):
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    marker = tmp_path / ".storage-root.json"
    marker.write_text(json.dumps({"schema_version": 1, "storage_root_id": root_id}))
    original = marker.read_bytes()
    store = TrajectoryFileStore(tmp_path, root_id, authorize=lambda _: None)
    assert store.storage_mode == "single_node"
    TrajectoryFileStore.provision(tmp_path, root_id)
    with pytest.raises(TrajectoryConflict):
        TrajectoryFileStore(
            tmp_path, root_id, authorize=lambda _: None, storage_mode="shared_directory"
        )
    assert marker.read_bytes() == original


@pytest.mark.parametrize("mode", [None, "", "shared", "other", True])
def test_invalid_mode_is_rejected_before_creating_registration(tmp_path, mode):
    with pytest.raises(ValueError, match="storage mode"):
        TrajectoryFileStore.provision(tmp_path, str(uuid4()), storage_mode=mode)
    assert list(tmp_path.iterdir()) == []


def test_each_root_open_rechecks_registered_mode(tmp_path):
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    store = TrajectoryFileStore(tmp_path, root_id, authorize=lambda _: None)
    marker = tmp_path / ".storage-root.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "storage_root_id": root_id,
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
    from management.services.trajectory import runtime

    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id, storage_mode="shared_directory")
    values = {
        "ENABLE_TELEMETRY": True,
        "MONITORING_TRACE_SINK": "local_file",
        "TRAJECTORY_ROOT_DIR": str(tmp_path),
        "TRAJECTORY_STORAGE_ROOT_ID": root_id,
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
    assert (
        processor.store.storage_mode
        == processor._maintenance_store.storage_mode
        == "shared_directory"
    )
    for key, value in {
        **values,
        "TRAJECTORY_READ_ENABLED": True,
        "TRAJECTORY_SIGNING_KEY": "a" * 32,
    }.items():
        monkeypatch.setattr(environment, key, value)
    monkeypatch.setattr(runtime, "_service", None)
    assert runtime.get_service().archive.store.storage_mode == "shared_directory"
    monkeypatch.setattr(runtime, "_service", None)
    monkeypatch.setattr(environment, "TRAJECTORY_STORAGE_MODE", "single_node")
    from contracts.errors.trajectory import QueryError

    with pytest.raises(QueryError) as raised:
        runtime.get_service()
    assert raised.value.status == 503 and raised.value.code == "storage_busy"


def test_provision_cli_accepts_mode(tmp_path, monkeypatch):
    root_id = str(uuid4())
    monkeypatch.setattr(
        "sys.argv",
        [
            "provision",
            "--root",
            str(tmp_path),
            "--storage-root-id",
            root_id,
            "--storage-mode",
            "shared_directory",
        ],
    )
    main()
    assert (
        json.loads((tmp_path / ".storage-root.json").read_text())["storage_mode"]
        == "shared_directory"
    )
