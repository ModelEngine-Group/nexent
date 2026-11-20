# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import MagicMock, Mock

import pytest
from contracts.knowledge_maintenance import BROKER_INVENTORY
from nexent.storage.errors import CapabilityUnsupported, ScopeDenied, Unavailable
from nexent.storage.models import StorageScope
from redis.exceptions import ConnectionError

from infrastructure.redis.legacy_broker import LegacyBrokerRecords
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def broker():
    client, pipe = MagicMock(), MagicMock()
    client.__enter__.return_value = client
    client.pipeline.return_value.__enter__.return_value = pipe
    pipe.execute.return_value = list(range(26))
    factory = Mock(return_value=client)
    store = LegacyBrokerRecords(
        StorageScope("management", "tenant", "operator", {BROKER_INVENTORY}),
        "redis://local/0", client_factory=factory,
    )
    return store, client, pipe, factory


def test_regular_priority_and_shared_state_are_counted_atomically(broker):
    store, client, pipe, factory = broker

    result = store.get(BROKER_INVENTORY, "queues", context=context())

    assert result["queues"] == {
        "parse_q": 6, "process_q": 22, "forward_q": 38, "forward_part_q": 54, "forward_aggregate_q": 70,
    }
    assert result["shared_default_queue"] == 86
    assert (result["shared_unacked"], result["shared_unacked_index"]) == (24, 25)
    assert [args[0] for args, _ in pipe.llen.call_args_list[:4]] == [
        "parse_q", "parse_q\x06\x163", "parse_q\x06\x166", "parse_q\x06\x169",
    ]
    client.pipeline.assert_called_once_with(transaction=True)
    pipe.hlen.assert_called_once_with("unacked")
    pipe.zcard.assert_called_once_with("unacked_index")
    pipe.execute.assert_called_once_with()
    assert factory.call_args.kwargs["retry_on_error"] == []


def test_only_fixed_read_is_permitted(broker):
    store, _, _, factory = broker
    with pytest.raises(ScopeDenied):
        store.get(BROKER_INVENTORY, "arbitrary-key", context=context())
    with pytest.raises(CapabilityUnsupported):
        store.delete(BROKER_INVENTORY, "queues", context=context())
    factory.assert_not_called()


@pytest.mark.parametrize("response", [[0], [False]*26, [-1]*26, None])
def test_invalid_inventory_never_reports_empty(broker, response):
    store, client, pipe, _ = broker
    pipe.execute.return_value = response
    with pytest.raises(Unavailable):
        store.get(BROKER_INVENTORY, "queues", context=context())
    client.__exit__.assert_called_once()


def test_provider_error_is_redacted_and_never_retried(broker):
    store, client, pipe, _ = broker
    pipe.execute.side_effect = ConnectionError("private address")
    with pytest.raises(Unavailable, match="Storage is unavailable"):
        store.get(BROKER_INVENTORY, "queues", context=context())
    pipe.execute.assert_called_once()
    client.__exit__.assert_called_once()


def test_result_inventory_counts_distinct_keys_without_exposing_metadata(broker):
    store, client, pipe, factory = broker
    store._result_url = "redis://local/1"
    prefix = b"celery-task-meta-"
    indexed, missing, malformed, oversized, expired, invalid = (
        prefix + suffix for suffix in (b"first", b"second", b"bad", b"huge", b"gone", b"/invalid")
    )
    client.scan.side_effect = [(8, [indexed, missing, invalid]), (0, [indexed, malformed, oversized, expired])]
    client.getrange.side_effect = [
        b'{"result":{"index_name":"private-index"}}', b'{"result":{"tenant_id":"private-tenant"}}',
        b'not-json', b' ' * (1024 * 1024 + 1), b'',
    ]

    assert store.get(BROKER_INVENTORY, "result_metadata", context=context()) == {
        "id": "result_metadata", "with_index_hint": 1, "without_index_hint": 4, "invalid_task_key": 1,
    }
    assert [call.args for call in client.getrange.call_args_list] == [
        (key, 0, 1024 * 1024) for key in (indexed, missing, malformed, oversized, expired)
    ]
    assert factory.call_args.args == ("redis://local/1",)
    client.pipeline.assert_not_called()


@pytest.mark.parametrize("response", [(False, []), (0, ["decoded"]), None])
def test_invalid_result_scan_cannot_report_counts(broker, response):
    store, client, _, _ = broker
    store._result_url = "redis://local/1"
    client.scan.return_value = response
    with pytest.raises(Unavailable):
        store.get(BROKER_INVENTORY, "result_metadata", context=context())
    client.getrange.assert_not_called()
    client.__exit__.assert_called_once()
