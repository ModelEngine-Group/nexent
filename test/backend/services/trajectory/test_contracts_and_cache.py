# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Parameter boundaries, publication retention and bounded cache failures."""

from unittest.mock import MagicMock, Mock

import pytest
from contracts.trajectory import CleanupRequest, RecordsQuery
from infrastructure.observability.trajectory_io import (
    TrajectoryConflict,
    TrajectoryCorrupt,
)
from management.services.trajectory.archive import Archive, storage_error
from management.services.trajectory.cache import ByteCache
from pydantic import ValidationError


@pytest.mark.parametrize(
    "params",
    [
        {"conversation_id": "01"},
        {"conversation_id": "2147483648"},
        {"agent_id": "-1"},
        {"page_size": 101},
        {"started_from": "2026-11-01T00:00:00"},
        {"started_from": "2026-11-02T00:00:00Z", "started_to": "2026-11-01T00:00:00Z"},
        {"sort_by": "secret"},
        {"unknown": "value"},
        {"id_query": "x" * 201},
    ],
)
def test_invalid_collection_parameters(params):
    with pytest.raises(ValidationError):
        RecordsQuery(**params)


def test_utc_normalization_and_semantically_equal_time_boundaries():
    query = RecordsQuery(
        started_from="2026-11-01T08:00:00+08:00",
        started_to="2026-11-01T00:00:00Z",
        id_query=" A ",
    )
    assert query.started_from == query.started_to == "2026-11-01T00:00:00Z"
    assert query.filters["id_query"] == "a"


@pytest.mark.parametrize("value", [0, -1, True, 7.0, "7", 3651])
def test_cleanup_requires_strict_integer_days(value):
    with pytest.raises(ValidationError):
        CleanupRequest(before_days=value)


@pytest.mark.parametrize("value", [1, 3650])
def test_cleanup_days_boundaries(value):
    assert CleanupRequest(before_days=value).before_days == value


def test_cache_hard_byte_limit_lru_and_expiry(mocker):
    now = mocker.patch(
        "management.services.trajectory.cache.time.monotonic", return_value=0
    )
    cache = ByteCache(max_bytes=10, ttl=10)
    assert not cache.put("large", object(), 11)
    assert cache.put("a", 1, 6) and cache.put("b", 2, 4)
    assert cache.get("a") == 1
    cache.put("c", 3, 4)
    assert cache.get("b") is None and cache.size == 10
    now.return_value = 10
    assert cache.get("a") is None and cache.size == 4


@pytest.mark.parametrize(
    "error,code,status",
    [
        (
            TrajectoryConflict(
                "Trajectory ownership differs from trusted capture identity"
            ),
            "trajectory_not_found",
            404,
        ),
        (
            TrajectoryConflict("Trajectory ownership lookup budget exhausted"),
            "lookup_unavailable",
            503,
        ),
        (TrajectoryCorrupt("private path"), "trajectory_corrupt", 503),
        (OSError("/private/path"), "storage_unavailable", 503),
    ],
)
def test_safe_storage_error_mapping(error, code, status):
    result = storage_error(error)
    assert result.code == code and result.status == status
    assert "/private/path" not in str(result)


def test_read_tightens_expiry_and_never_revives_after_extension():
    store, directory = MagicMock(), MagicMock()
    store._session.return_value.__enter__ = Mock(return_value=directory)
    store._session.return_value.__exit__ = Mock(return_value=False)
    row = {"tenant_id": "t", "user_id": "u", "conversation_id": "1", "agent_id": "7"}
    meta = {
        "runs": [
            {
                "finished_at": "2026-11-01T00:00:00Z",
                "expires_at": "2026-12-01T00:00:00Z",
            }
        ]
    }
    directory.read_json.return_value = meta
    store.retention_days = 7
    archive = Archive(store)
    archive.manifest(row)
    assert meta["runs"][0]["expires_at"] == "2026-11-08T00:00:00Z"
    store._save_manifest.assert_called_once()
    store.retention_days = 30
    archive.manifest(row)
    store._save_manifest.assert_called_once()


def test_fractional_second_range_compares_instants():
    with pytest.raises(ValidationError):
        RecordsQuery(
            started_from="2026-11-01T00:00:00.1Z", started_to="2026-11-01T00:00:00Z"
        )
    assert RecordsQuery(
        started_from="2026-11-01T00:00:00Z", started_to="2026-11-01T00:00:00.1Z"
    ).started_to.endswith("100000Z")


def test_read_configuration_is_independent_and_shared_per_process(
    tmp_path, monkeypatch
):
    from uuid import uuid4

    from contracts.constants import environment
    from infrastructure.observability.trajectory_store import TrajectoryFileStore
    from management.services.trajectory import runtime
    from management.services.trajectory.primitives import QueryError

    monkeypatch.setattr(runtime, "_service", None)
    monkeypatch.setattr(environment, "TRAJECTORY_READ_ENABLED", False)
    with pytest.raises(QueryError, match="trajectory_read_disabled"):
        runtime.get_service()
    root_id = str(uuid4())
    TrajectoryFileStore.provision(tmp_path, root_id)
    monkeypatch.setattr(environment, "ENABLE_TELEMETRY", False)
    monkeypatch.setattr(environment, "TRAJECTORY_READ_ENABLED", True)
    monkeypatch.setattr(environment, "TRAJECTORY_SIGNING_KEY", "a" * 32)
    monkeypatch.setattr(environment, "TRAJECTORY_ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(environment, "TRAJECTORY_STORAGE_ROOT_ID", root_id)
    service = runtime.get_service()
    assert service is runtime.get_service()
    assert service.max_bytes == environment.TRAJECTORY_QUERY_MAX_BYTES
    assert service.seconds == environment.TRAJECTORY_QUERY_TIMEOUT_SECONDS
    assert service.max_candidates == environment.TRAJECTORY_QUERY_MAX_CANDIDATES
    monkeypatch.setattr(runtime, "_service", None)
    monkeypatch.setattr(environment, "TRAJECTORY_SIGNING_KEY", "short")
    with pytest.raises(QueryError, match="trajectory_configuration_invalid"):
        runtime.get_service()


@pytest.mark.parametrize(
    "availability", ["not_captured", "serialization_failed", "redacted"]
)
def test_missing_body_preserves_capture_availability(availability):
    from management.services.trajectory.primitives import TokenSigner
    from management.services.trajectory.service import TrajectoryService

    service = TrajectoryService(Mock(), Mock(), TokenSigner("a" * 32))
    body = service._body(
        None,
        None,
        None,
        None,
        {"_availability": {"reasoning": availability}},
        "reasoning",
        None,
    )
    assert body["availability"] == availability and body["text"] is None
    assert body["content_id"] is None and not body["complete"]
