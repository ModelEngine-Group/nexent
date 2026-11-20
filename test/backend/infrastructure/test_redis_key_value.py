# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SI-005/009/011: scope, atomic execution, deadlines and unknown writes."""

from time import monotonic
from unittest.mock import MagicMock

import pytest
from nexent.storage.errors import (
    CapabilityUnsupported,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    TTL,
    Missing,
    OperationContext,
    Revision,
    StorageScope,
    TTLMode,
)
from redis.exceptions import ConnectionError, TimeoutError

from infrastructure.redis.kv import RedisKeyValueConfig, RedisKeyValueStore
from infrastructure.storage.bootstrap import KVBinding, bind_key_value


@pytest.fixture
def client_factory():
    factory = MagicMock()
    factory.return_value.__enter__.return_value = MagicMock()
    return factory


def context():
    return OperationContext("operation-1", monotonic() + 5)


def scope(tenant="t1", prefix=""):
    return StorageScope(
        "runtime", tenant, "actor", frozenset({"cache"}), resource_prefix=prefix
    )


def store(factory, tenant="t1", prefix=""):
    return RedisKeyValueStore(
        RedisKeyValueConfig("redis://fixture/0", "test"),
        scope(tenant, prefix),
        namespace="cache",
        client_factory=factory,
    )


def test_constructing_a_scoped_store_does_not_create_a_connection(client_factory):
    store(client_factory)
    client_factory.assert_not_called()


def test_missing_values_and_empty_payload_are_distinct(client_factory):
    client = client_factory.return_value.__enter__.return_value
    client.hmget.side_effect = [[None, None], [b"r1", b""]]
    kv = store(client_factory)
    assert kv.get("key", context=context()) is None
    entry = kv.get("key", context=context())
    assert entry.value == b""
    assert entry.revision == Revision("r1")


def test_tenant_key_encoding_does_not_allow_delimiter_collisions(client_factory):
    client = client_factory.return_value.__enter__.return_value
    client.hmget.return_value = [None, None]
    store(client_factory, "a:b").get("c", context=context())
    first = client.hmget.call_args.args[0]
    store(client_factory, "a").get("b:c", context=context())
    assert client.hmget.call_args.args[0] != first


def test_cas_and_ttl_are_one_server_side_operation(client_factory):
    client = client_factory.return_value.__enter__.return_value
    client.eval.return_value = [1, b"new-revision"]
    receipt = store(client_factory).compare_exchange(
        "key", Missing.VALUE, b"value", ttl=TTL(TTLMode.DURATION, 1), context=context()
    )
    assert receipt.matched and receipt.operation_id == "operation-1"
    assert receipt.revision == Revision("new-revision")
    client.eval.assert_called_once()
    client.hmget.assert_not_called()
    assert client.eval.call_args.args[-2:] == ("duration", 1000)


def test_conflict_reports_actual_revision_without_a_retry(client_factory):
    client = client_factory.return_value.__enter__.return_value
    client.eval.return_value = [0, b"current"]
    receipt = store(client_factory).compare_exchange(
        "key", Revision("stale"), b"value", ttl=TTL(TTLMode.PRESERVE), context=context()
    )
    assert not receipt.matched and receipt.revision == Revision("current")
    client.eval.assert_called_once()


@pytest.mark.parametrize(
    "error", [TimeoutError("secret connection"), ConnectionError("private endpoint")]
)
def test_write_failure_is_unknown_and_never_replayed(client_factory, error):
    client = client_factory.return_value.__enter__.return_value
    client.eval.side_effect = error
    with pytest.raises(OutcomeUnknown) as caught:
        store(client_factory).put(
            "key", b"value", ttl=TTL(TTLMode.NO_EXPIRY), context=context()
        )
    assert caught.value.operation_id == "operation-1"
    assert "secret" not in str(caught.value) and "endpoint" not in str(caught.value)
    client.eval.assert_called_once()
    client_factory.return_value.__exit__.assert_called_once()


def test_read_connection_failure_is_unavailable(client_factory):
    client_factory.return_value.__enter__.return_value.hmget.side_effect = (
        ConnectionError("private")
    )
    with pytest.raises(Unavailable):
        store(client_factory).get("key", context=context())


def test_expired_or_unauthorized_operations_have_zero_io(client_factory):
    kv = store(client_factory, prefix="allowed/")
    with pytest.raises(ScopeDenied):
        kv.get("other/key", context=context())
    with pytest.raises(DeadlineExceeded):
        kv.get("allowed/key", context=OperationContext("expired", monotonic() - 1))
    client_factory.assert_not_called()


def test_binding_rejects_missing_capability_and_service_role_before_connecting(
    client_factory,
):
    binding = KVBinding(
        "cache",
        RedisKeyValueConfig("redis://fixture/0", "test"),
        frozenset({"management"}),
    )
    with pytest.raises(ScopeDenied):
        bind_key_value(binding, scope())
    with pytest.raises(CapabilityUnsupported):
        bind_key_value(
            binding,
            StorageScope("management", "t1", "actor", {"cache"}),
            required=frozenset({"events.append"}),
        )
    client_factory.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "redis://fixture/0?socket_timeout=0",
        "redis://fixture/0?retry_on_timeout=true",
        "https://fixture/0",
        "redis://fixture/not-a-database",
    ],
)
def test_configuration_rejects_driver_overrides_and_invalid_targets(url):
    with pytest.raises(InvalidInput):
        RedisKeyValueConfig(url, "test")


def test_config_repr_hides_credentials():
    config = RedisKeyValueConfig("redis://user:private-password@fixture/0", "test")
    assert "private-password" not in repr(config)


def test_close_and_unsupported_capabilities_never_create_a_client(client_factory):
    kv = store(client_factory)
    with pytest.raises(CapabilityUnsupported):
        kv.scan("", None, context=context())
    kv.close()
    with pytest.raises(Unavailable):
        kv.get("key", context=context())
    client_factory.assert_not_called()


def test_revision_text_cannot_be_interpreted_as_a_missing_key_condition(client_factory):
    client = client_factory.return_value.__enter__.return_value
    client.eval.return_value = [0, None]
    store(client_factory).compare_exchange(
        "key", Revision("-"), b"value", ttl=TTL(TTLMode.NO_EXPIRY), context=context()
    )
    assert client.eval.call_args.args[4] == "r:-"


@pytest.mark.parametrize(
    "response", [[2, b"revision"], [1, b"\xffprivate"], [], [1, "private"]]
)
def test_invalid_write_response_is_unknown_and_does_not_expose_backend_data(
    client_factory, response
):
    client_factory.return_value.__enter__.return_value.eval.return_value = response
    with pytest.raises(OutcomeUnknown) as caught:
        store(client_factory).put(
            "key", b"value", ttl=TTL(TTLMode.NO_EXPIRY), context=context()
        )
    assert "private" not in str(caught.value)


def test_socket_budget_and_retry_policy_cannot_exceed_the_context(
    client_factory, monkeypatch
):
    monkeypatch.setattr("nexent.storage.models.monotonic", lambda: 100.0)
    client_factory.return_value.__enter__.return_value.hmget.return_value = [None, None]
    kv = store(client_factory)
    kv.get("key", context=OperationContext("short", 100.1))
    options = client_factory.call_args.kwargs
    assert 0 < options["socket_timeout"] <= 0.1
    assert options["socket_timeout"] == options["socket_connect_timeout"]
    assert options["retry"].get_retries() == 0
