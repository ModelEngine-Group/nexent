# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared cache instances execute real Lua against an isolated Redis protocol substitute."""

from unittest.mock import Mock

import fakeredis
import pytest
from redis.exceptions import ConnectionError

# isort: split
from ops.services.trajectory.primitives import QueryError, ReferenceStore
from ops.services.trajectory.redis_cache import RedisByteCache


@pytest.fixture
def caches():
    server = fakeredis.FakeServer()
    clients = [
        fakeredis.FakeRedis(server=server, decode_responses=True) for _ in range(2)
    ]
    try:
        yield [
            RedisByteCache(client, namespace="test", max_bytes=1024, ttl=30)
            for client in clients
        ]
    finally:
        for client in clients:
            client.close()


def test_references_survive_switching_instances_without_a_signing_key(caches):
    first, second = [ReferenceStore(cache=cache) for cache in caches]
    token = first.issue("content", {"actor": "admin", "tenant": "t", "position": 1})
    assert second.resolve(token, "content", actor="admin", tenant="t")["position"] == 1
    with pytest.raises(QueryError, match="invalid_reference"):
        second.resolve(token, "content", actor="other")
    with pytest.raises(QueryError, match="invalid_reference"):
        second.resolve(token, "nodes", actor="admin")


def test_shared_membership_is_a_detached_frozen_value(caches):
    value = {"members": [{"conversation_id": "123"}]}
    assert caches[0].put("query", value, 100)
    value["members"].clear()
    loaded = caches[1].get("query")
    assert loaded["members"] == [{"conversation_id": "123"}]
    loaded["members"].clear()
    assert caches[0].get("query")["members"] == [{"conversation_id": "123"}]


def test_shared_budget_evicts_least_recently_used_and_replaces_sizes(caches):
    a, b = caches
    assert a.put("a", 1, 500) and b.put("b", 2, 500)
    assert b.get("a") == 1
    assert b.put("c", 3, 500)
    assert a.get("b") is None
    assert a.put("a", 4, 100)
    assert b.put("d", 5, 400)
    assert b.get("a") == 4 and a.get("c") == 3
    assert not a.put("too-large", 6, 1025)
    assert b.get("too-large") is None


def test_expired_state_does_not_revive_on_access(caches, monkeypatch):
    a, b = caches
    assert a.put("expired", "value", 10)
    # Redis owns the clock; only its protocol substitute is advanced for this UT.
    import time

    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 20)
    assert b.get("expired") == "value"
    assert b.put("other", "still-live", 10)
    monkeypatch.setattr(time, "time", lambda: now + 31)
    assert b.get("expired") is None
    assert a.get("other") == "still-live"
    assert a.put("fresh", "new", 1024)
    assert b.get("fresh") == "new"


@pytest.mark.parametrize("operation", ["get", "put"])
def test_redis_failure_is_explicit_and_never_uses_local_fallback(
    caches, mocker, operation
):
    client = caches[0].client
    mocker.patch.object(
        client, "eval", side_effect=ConnectionError("private redis address")
    )
    with pytest.raises(QueryError, match="trajectory_cache_unavailable") as error:
        caches[0].get("key") if operation == "get" else caches[0].put("key", {}, 10)
    assert error.value.status == 503 and error.value.retry_after == 2
    assert "private" not in str(error.value)


def test_namespaces_do_not_mix_references_and_list_membership(caches):
    queries = RedisByteCache(caches[0].client, namespace="queries")
    assert queries.put("same", {"members": [1]}, 100)
    assert caches[1].get("same") is None
    assert caches[1].put("same", "content", 100)
    assert queries.get("same") == {"members": [1]}


@pytest.mark.parametrize("url", [None, "", "invalid-redis-url"])
def test_missing_or_invalid_redis_configuration_is_a_safe_domain_error(url):
    from ops.services.trajectory.redis_cache import shared_caches

    with pytest.raises(QueryError) as error:
        shared_caches(url)
    assert error.value.status == 503
    assert error.value.code in {
        "trajectory_cache_unavailable",
        "trajectory_configuration_invalid",
    }


def test_shared_clients_bound_transport_wait_and_do_not_retry_implicitly():
    from ops.services.trajectory.redis_cache import shared_caches

    client, references, queries = shared_caches("redis://test/1")
    try:
        settings = client.connection_pool.connection_kwargs
        assert settings["socket_connect_timeout"] == settings["socket_timeout"] == 2
        assert settings["retry"].get_retries() == 0
        assert references.client is queries.client is client
    finally:
        client.close()


def test_runtime_constructor_failure_closes_owned_redis_client(mocker):
    from contracts.constants import environment
    from ops.services.trajectory import runtime

    client = Mock()
    mocker.patch.object(runtime, "_service", None)
    mocker.patch.object(environment, "TRAJECTORY_READ_ENABLED", True)
    mocker.patch(
        "ops.services.trajectory.redis_cache.shared_caches",
        return_value=(client, Mock(), Mock()),
    )
    mocker.patch(
        "infrastructure.observability.trajectory_store.TrajectoryFileStore",
        side_effect=ValueError("private path"),
    )
    with pytest.raises(QueryError, match="trajectory_configuration_invalid"):
        runtime.get_service()
    client.close.assert_called_once()
    assert runtime._service is None
