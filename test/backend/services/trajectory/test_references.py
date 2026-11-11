# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Opaque references retain trusted state on the server without a deployment key."""

import pytest
from management.services.trajectory import primitives


def test_references_are_random_ids_and_keep_payload_server_side():
    store = primitives.ReferenceStore()
    data = {"actor": "admin", "tenant": "private-tenant", "position": 1}
    first = store.issue("nodes", data)
    second = store.issue("nodes", data)
    assert first != second and len(first) == 32 and int(first, 16) >= 0
    assert "private-tenant" not in first
    assert store.resolve(first, "nodes", actor="admin") == data


@pytest.mark.parametrize("invalid", [None, "", "unknown", "a" * 32, "a" * 8193, 123])
def test_unknown_and_malformed_references_are_rejected(invalid):
    with pytest.raises(primitives.QueryError, match="invalid_reference"):
        primitives.ReferenceStore().resolve(invalid, "content")


def test_reference_scope_and_type_are_checked_before_returning_state():
    store = primitives.ReferenceStore()
    token = store.issue("content", {"actor": "admin", "tenant": "t", "conversation": "1"})
    for kind, binding in [
        ("snapshot", {"actor": "admin"}),
        ("content", {"actor": "other"}),
        ("content", {"tenant": "foreign"}),
        ("content", {"conversation": "2"}),
    ]:
        with pytest.raises(primitives.QueryError, match="invalid_reference"):
            store.resolve(token, kind, **binding)


def test_reference_state_is_detached_from_both_input_and_output():
    store = primitives.ReferenceStore()
    data = {"actor": "admin", "members": [1, 2]}
    token = store.issue("query", data)
    data["members"].append(3)
    loaded = store.resolve(token, "query")
    assert loaded["members"] == [1, 2]
    loaded["members"].append(4)
    assert store.resolve(token, "query")["members"] == [1, 2]


def test_expired_and_restarted_references_require_a_new_query(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("management.services.trajectory.cache.time.monotonic", lambda: clock[0])
    store = primitives.ReferenceStore(ttl=30)
    token = store.issue("snapshot", {"actor": "admin"})
    clock[0] += 30
    with pytest.raises(primitives.QueryError, match="invalid_reference"):
        store.resolve(token, "snapshot")
    fresh = store.issue("snapshot", {"actor": "admin"})
    assert store.resolve(fresh, "snapshot")["actor"] == "admin"
    with pytest.raises(primitives.QueryError, match="invalid_reference"):
        primitives.ReferenceStore().resolve(fresh, "snapshot")


def test_reference_cache_is_bounded_and_eviction_is_explicit():
    store = primitives.ReferenceStore(max_bytes=1024)
    old = store.issue("nodes", {"actor": "admin", "position": 0})
    for position in range(1, 5):
        latest = store.issue("nodes", {"actor": "admin", "position": position})
    assert store.cache.size <= 1024
    with pytest.raises(primitives.QueryError, match="invalid_reference"):
        store.resolve(old, "nodes")
    assert store.resolve(latest, "nodes")["position"] == 4


def test_oversized_reference_state_fails_without_retaining_data():
    store = primitives.ReferenceStore(max_bytes=256)
    with pytest.raises(primitives.QueryError, match="query_budget_exceeded"):
        store.issue("content", {"body": "x" * 1000})
    assert store.cache.size == 0
