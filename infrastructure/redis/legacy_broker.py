# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read counts for the fixed production legacy broker keys through RecordStore."""

from contracts.knowledge_maintenance import BROKER_INVENTORY
from nexent.storage.errors import CapabilityUnsupported, ScopeDenied, Unavailable
from nexent.storage.models import CapabilitySet, ReadConsistency
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from infrastructure.redis.kv import RedisKeyValueConfig, _make_client

_QUEUES = ("parse_q", "process_q", "forward_q", "forward_part_q", "forward_aggregate_q")
# The retired Celery app uses Kombu Redis defaults. Its unrouted tasks can use celery.
_DEFAULT_QUEUE = "celery"
_PRIORITY_SUFFIXES = ("", "\x06\x163", "\x06\x166", "\x06\x169")


class LegacyBrokerRecords:
    capabilities = CapabilitySet(frozenset({"record.get"}))

    def __init__(self, scope, url, *, client_factory=None):
        if scope.system or scope.resource_prefix or scope.service_role != "management" or scope.namespaces != {BROKER_INVENTORY}:
            raise ScopeDenied()
        self.scope = scope
        self._config = RedisKeyValueConfig(url, BROKER_INVENTORY)
        self._client = client_factory or _make_client
        self._closed = False

    def get(self, dataset, key, *, fields=(), consistency=ReadConsistency.AUTHORITATIVE, context):
        if self._closed or dataset != BROKER_INVENTORY or key != "queues":
            raise ScopeDenied()
        if fields or consistency != ReadConsistency.AUTHORITATIVE:
            raise CapabilityUnsupported()
        timeout = min(context.remaining(), self._config.request_timeout)
        try:
            with self._client(
                self._config.url, context=context, decode_responses=False,
                socket_connect_timeout=timeout, socket_timeout=timeout,
                retry=Retry(NoBackoff(), 0), retry_on_timeout=False, retry_on_error=[],
            ) as client, client.pipeline(transaction=True) as pipe:
                for name in (*_QUEUES, _DEFAULT_QUEUE):
                    for suffix in _PRIORITY_SUFFIXES:
                        pipe.llen(name + suffix)
                pipe.hlen("unacked")
                pipe.zcard("unacked_index")
                counts = pipe.execute()
            context.remaining()
        except (RedisError, OSError):
            context.remaining()
            raise Unavailable(operation_id=context.operation_id) from None
        if (
            not isinstance(counts, (list, tuple))
            or len(counts) != (len(_QUEUES) + 1) * len(_PRIORITY_SUFFIXES) + 2
            or any(type(count) is not int or count < 0 for count in counts)
        ):
            raise Unavailable(operation_id=context.operation_id)
        width = len(_PRIORITY_SUFFIXES)
        return {
            "id": key,
            "queues": {name: sum(counts[i * width:(i + 1) * width]) for i, name in enumerate(_QUEUES)},
            "shared_default_queue": sum(counts[-width - 2:-2]),
            "shared_unacked": counts[-2],
            "shared_unacked_index": counts[-1],
        }

    def close(self):
        self._closed = True

    def _unsupported(self, *args, **kwargs):
        raise CapabilityUnsupported()

    query = count = insert = update = patch = delete = transaction = _unsupported
