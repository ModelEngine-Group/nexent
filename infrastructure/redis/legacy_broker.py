# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read aggregate legacy broker and result evidence through RecordStore."""

import json

from contracts.knowledge_maintenance import BROKER_INVENTORY
from nexent.storage.errors import CapabilityUnsupported, ScopeDenied, Unavailable
from nexent.storage.models import CapabilitySet, ReadConsistency
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from infrastructure.redis.kv import RedisKeyValueConfig, _make_client
from infrastructure.redis.legacy_tasks import TASK_ID, scan_legacy_keys

_QUEUES = ("parse_q", "process_q", "forward_q", "forward_part_q", "forward_aggregate_q")
# The retired Celery app uses Kombu Redis defaults. Its unrouted tasks can use celery.
_DEFAULT_QUEUE = "celery"
_PRIORITY_SUFFIXES = ("", "\x06\x163", "\x06\x166", "\x06\x169")


_RESULT_PREFIX = b"celery-task-meta-"
_MAX_METADATA_BYTES = 1024 * 1024


def _has_index(raw):
    if len(raw) > _MAX_METADATA_BYTES:
        return False
    try:
        metadata = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return False
    result = metadata.get("result") if isinstance(metadata, dict) else None
    index = result.get("index_name") if isinstance(result, dict) else None
    return isinstance(index, str) and bool(index.strip()) and len(index) <= 100 and index.isprintable()


class LegacyBrokerRecords:
    capabilities = CapabilitySet(frozenset({"record.get"}))

    def __init__(self, scope, url, *, result_url=None, client_factory=None):
        if scope.system or scope.resource_prefix or scope.service_role != "management" or scope.namespaces != {BROKER_INVENTORY}:
            raise ScopeDenied()
        self.scope = scope
        self._config = RedisKeyValueConfig(url, BROKER_INVENTORY)
        self._result_url = result_url
        self._client = client_factory or _make_client
        self._closed = False

    def get(self, dataset, key, *, fields=(), consistency=ReadConsistency.AUTHORITATIVE, context):
        if self._closed or dataset != BROKER_INVENTORY or key not in {"queues", "result_metadata"}:
            raise ScopeDenied()
        if fields or consistency != ReadConsistency.AUTHORITATIVE:
            raise CapabilityUnsupported()
        if key == "result_metadata":
            return self._results(context)
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

    def _results(self, context):
        config = RedisKeyValueConfig(self._result_url, BROKER_INVENTORY)
        timeout = min(context.remaining(), config.request_timeout)
        seen, cursor = set(), 0
        counts = {"with_index_hint": 0, "without_index_hint": 0, "invalid_task_key": 0}
        try:
            with self._client(
                config.url, context=context, decode_responses=False,
                socket_connect_timeout=timeout, socket_timeout=timeout,
                retry=Retry(NoBackoff(), 0), retry_on_timeout=False, retry_on_error=[],
            ) as client:
                while True:
                    cursor, keys = scan_legacy_keys(client, cursor, "celery-task-meta-*", context)
                    for key in keys:
                        if key in seen:
                            continue
                        seen.add(key)
                        task_id = key.removeprefix(_RESULT_PREFIX).decode("ascii", errors="replace")
                        if not key.startswith(_RESULT_PREFIX) or not TASK_ID.fullmatch(task_id):
                            counts["invalid_task_key"] += 1
                            continue
                        context.remaining()
                        raw = client.getrange(key, 0, _MAX_METADATA_BYTES)
                        if not isinstance(raw, bytes):
                            raise Unavailable(operation_id=context.operation_id)
                        category = "with_index_hint" if _has_index(raw) else "without_index_hint"
                        counts[category] += 1
                    if cursor == 0:
                        break
            context.remaining()
        except (RedisError, OSError):
            context.remaining()
            raise Unavailable(operation_id=context.operation_id) from None
        return {"id": "result_metadata", **counts}

    def close(self):
        self._closed = True

    def _unsupported(self, *args, **kwargs):
        raise CapabilityUnsupported()

    query = count = insert = update = patch = delete = transaction = _unsupported
