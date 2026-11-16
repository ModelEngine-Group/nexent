# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Kombu-owned broker delivery with scoped KV metadata and opaque receipts."""

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from queue import Empty
from threading import get_ident
from urllib.parse import urlsplit
from uuid import uuid4

from kombu import Connection
from kombu.exceptions import KombuError
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    StorageError,
    Unavailable,
)
from nexent.storage.models import (
    TTL,
    CapabilitySet,
    Missing,
    Revision,
    TaskEnvelope,
    TTLMode,
)
from nexent.storage.queue import Delivery, DeliveryState
from redis.exceptions import RedisError

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TTL = TTL(TTLMode.DURATION, 7 * 24 * 3600)


def _release(queue, connection):
    failed = False
    for close in (queue.close, connection.release):
        try:
            close()
        except (KombuError, RedisError, OSError):
            failed = True
            logging.getLogger(__name__).warning("work_queue_release_failed")
    if failed and sys.exc_info()[0] is None:
        raise Unavailable()


def _identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise InvalidInput()
    return value


@dataclass(frozen=True)
class QueueBinding:
    namespace: str
    broker_url: str = field(repr=False)
    roles: frozenset[str]
    handlers: frozenset[str]
    visibility_timeout: int = 3600

    def __post_init__(self):
        _identifier(self.namespace)
        object.__setattr__(self, "roles", frozenset(self.roles))
        object.__setattr__(self, "handlers", frozenset(self.handlers))
        if not self.roles or not self.handlers or not self.broker_url:
            raise InvalidInput()
        try:
            url = urlsplit(self.broker_url)
            if (
                url.scheme not in {"redis", "rediss", "memory"}
                or url.query
                or url.fragment
            ):
                raise ValueError()
            if url.scheme != "memory" and not url.hostname:
                raise ValueError()
        except (ValueError, TypeError):
            raise InvalidInput() from None
        if type(self.visibility_timeout) is not int or self.visibility_timeout <= 0:
            raise InvalidInput()
        for handler in self.handlers:
            _identifier(handler)


class KombuWorkQueue:
    """One unacknowledged delivery per process/thread-owned consumer handle."""

    capabilities = CapabilitySet(
        frozenset(
            {
                "queue.enqueue",
                "queue.consume",
                "queue.ack",
                "queue.retry.immediate",
                "queue.cancel_request",
                "queue.inspect_delivery",
            }
        )
    )

    def __init__(self, scope, binding, kv, *, connection_factory=Connection):
        if scope.resource_prefix:
            raise CapabilityUnsupported()
        if (
            scope.system
            or scope.service_role not in binding.roles
            or binding.namespace not in scope.namespaces
            or kv.scope.tenant_id != scope.tenant_id
            or kv.scope.service_role != scope.service_role
        ):
            raise ScopeDenied()
        self._scope = scope
        self._binding = binding
        self._kv = kv
        self._factory = connection_factory
        self._pid = os.getpid()
        self._lease = None
        self._closed = False
        self._name = (
            binding.namespace
            + "."
            + hashlib.sha256(scope.tenant_id.encode()).hexdigest()
        )

    @property
    def scope(self):
        return self._scope

    def _check(self, context):
        if self._closed or os.getpid() != self._pid:
            raise ScopeDenied()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise CapabilityUnsupported()
        return context.remaining()

    def _connect(self, context):
        remaining = self._check(context)
        timeout = min(5, remaining)
        connection = self._factory(
            self._binding.broker_url,
            connect_timeout=timeout,
            transport_options={
                "socket_connect_timeout": timeout,
                "socket_timeout": timeout,
                "visibility_timeout": self._binding.visibility_timeout,
                "max_retries": 0,
            },
        )
        try:
            connection.ensure_connection(max_retries=0, timeout=remaining)
            queue = connection.SimpleQueue(
                self._name,
                no_ack=False,
                accept=["json"],
                queue_opts={"durable": True},
                exchange_opts={"durable": True},
            )
            return connection, queue
        except (KombuError, RedisError, OSError):
            connection.release()
            raise Unavailable(operation_id=context.operation_id) from None

    def _key(self, task_id, kind="state"):
        return self._binding.namespace + "." + kind + "." + _identifier(task_id)

    def _state(self, task_id, phase, context):
        self._kv.put(self._key(task_id), phase.encode(), ttl=_TTL, context=context)

    def enqueue(self, task, *, context):
        self._check(context)
        if (
            not isinstance(task, TaskEnvelope)
            or task.handler not in self._binding.handlers
            or not isinstance(task.arguments, dict)
            or task.revision is not None
            and not isinstance(task.revision, Revision)
        ):
            raise InvalidInput()
        _identifier(task.task_id)
        try:
            serialized = json.dumps(asdict(task), sort_keys=True, allow_nan=False)
        except (ValueError, TypeError):
            raise InvalidInput() from None
        if len(serialized.encode()) > 8 * 1024 * 1024:
            raise InvalidInput()
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest().encode()
        key = self._key(task.task_id, "input")
        previous = self._kv.get(key, context=context)
        if previous is None:
            receipt = self._kv.compare_exchange(
                key, Missing.VALUE, fingerprint, ttl=_TTL, context=context
            )
            if not receipt.matched:
                previous = self._kv.get(key, context=context)
                if previous is None:
                    raise Unavailable()
        if previous is not None and previous.value != fingerprint:
            raise Conflict()
        connection, queue = self._connect(context)
        try:
            self._check(context)
            queue.put(
                json.loads(serialized), serializer="json", delivery_mode=2, retry=False
            )
            self._state(task.task_id, "queued", context)
        except (KombuError, RedisError, OSError, StorageError):
            raise OutcomeUnknown(operation_id=context.operation_id) from None
        finally:
            _release(queue, connection)

    def consume(self, *, max_wait, context):
        self._check(context)
        if self._lease is not None:
            raise Conflict()
        if (
            isinstance(max_wait, bool)
            or not isinstance(max_wait, (int, float))
            or not 0 < max_wait <= 30
        ):
            raise InvalidInput()
        connection, queue = self._connect(context)
        retained = False
        try:
            try:
                message = queue.get(
                    block=True, timeout=min(max_wait, self._check(context))
                )
            except Empty:
                return None
            body = message.payload
            try:
                task_id, handler = _identifier(body["task_id"]), body["handler"]
                if handler not in self._binding.handlers or not isinstance(
                    body["arguments"], dict
                ):
                    raise InvalidInput()
                version = (
                    Revision(body["revision"]["value"])
                    if body.get("revision")
                    else None
                )
                task = TaskEnvelope(task_id, handler, body["arguments"], version)
            except (KeyError, TypeError, InvalidInput):
                message.reject(requeue=False)
                raise InvalidInput() from None
            token = uuid4().hex
            self._state(task_id, "received", context)
            self._lease = (token, task_id, message, queue, connection, get_ident())
            retained = True
            return Delivery(token, task)
        except (KombuError, RedisError, OSError):
            raise Unavailable(operation_id=context.operation_id) from None
        finally:
            if not retained:
                _release(queue, connection)

    def _finish(self, receipt, *, requeue, context):
        self._check(context)
        lease = self._lease
        if lease is None or lease[0] != receipt or lease[5] != get_ident():
            raise NotFound()
        try:
            lease[2].reject(requeue=True) if requeue else lease[2].ack()
            self._state(lease[1], "queued" if requeue else "acked", context)
        except (KombuError, RedisError, OSError, StorageError):
            raise OutcomeUnknown(operation_id=context.operation_id) from None
        finally:
            self._lease = None
            _release(lease[3], lease[4])

    def ack(self, receipt, *, context):
        self._finish(receipt, requeue=False, context=context)

    def retry(self, receipt, *, context):
        self._finish(receipt, requeue=True, context=context)

    def cancel_request(self, task_id, *, context):
        self._check(context)
        self._kv.put(self._key(task_id, "cancel"), b"1", ttl=_TTL, context=context)

    def inspect_delivery(self, task_id, *, context):
        self._check(context)
        state = self._kv.get(self._key(task_id), context=context)
        cancelled = self._kv.get(self._key(task_id, "cancel"), context=context)
        return DeliveryState(
            state.value.decode() if state else "unknown", cancelled is not None
        )

    def close(self):
        if os.getpid() != self._pid:
            raise ScopeDenied()
        if self._lease is not None:
            if self._lease[5] != get_ident():
                raise ScopeDenied()
            lease, self._lease = self._lease, None
            try:
                lease[2].reject(requeue=True)
            finally:
                _release(lease[3], lease[4])
        self._closed = True
