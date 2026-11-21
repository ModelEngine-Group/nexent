# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped Redis KV adapter with atomic revision/TTL mutations and no write retries."""

import json
from asyncio import get_running_loop
from base64 import urlsafe_b64encode
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from math import ceil, isfinite
from urllib.parse import urlsplit
from uuid import uuid4

from nexent.storage.errors import (
    CapabilityUnsupported,
    DeadlineExceeded,
    InvalidInput,
    OperationCancelled,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    TTL,
    CapabilitySet,
    KVEntry,
    Missing,
    OperationContext,
    Revision,
    StorageScope,
    TTLMode,
    WriteReceipt,
)

_MUTATE = """
local revision = redis.call('HGET', KEYS[1], 'revision')
local mode = ARGV[1]
local expected = ARGV[2]
if mode == 'cas' or (mode == 'delete' and expected ~= '*') then
    if expected == 'missing' then
        if revision then return {0, revision} end
    elseif revision ~= string.sub(expected, 3) then
        return {0, revision or false}
    end
end
if mode == 'delete' then
    local deleted = redis.call('DEL', KEYS[1])
    return {deleted, revision or false}
end
redis.call('HSET', KEYS[1], 'revision', ARGV[3], 'value', ARGV[4])
if ARGV[5] == 'duration' then
    redis.call('PEXPIRE', KEYS[1], ARGV[6])
elseif ARGV[5] == 'no-expiry' then
    redis.call('PERSIST', KEYS[1])
end
return {1, ARGV[3]}
"""


@dataclass(frozen=True)
class RedisKeyValueConfig:
    url: str = field(repr=False)
    binding: str
    request_timeout: float = 5.0
    max_value_bytes: int = 1024 * 1024

    def __post_init__(self):
        try:
            url = urlsplit(self.url)
            # URL query options must not override adapter-owned timeout/retry settings.
            valid_url = (
                url.scheme in {"redis", "rediss"}
                and url.hostname
                and not url.query
                and not url.fragment
                and url.port != 0
                and (not url.path.strip("/") or url.path.strip("/").isdigit())
            )
        except (TypeError, ValueError):
            raise InvalidInput() from None
        if (
            not valid_url
            or not self.binding
            or not isinstance(self.request_timeout, (int, float))
            or isinstance(self.request_timeout, bool)
            or not isfinite(self.request_timeout)
            or self.request_timeout <= 0
            or type(self.max_value_bytes) is not int
            or self.max_value_bytes <= 0
        ):
            raise InvalidInput()


def _make_client(url, *, context, **options):
    """Refresh the remaining budget before every driver send/read, including handshake."""
    from redis import ConnectionPool, Redis
    from redis.connection import Connection, SSLConnection, parse_url

    class DeadlineConnection:
        def _remaining(self):
            return min(context.remaining(), options["socket_timeout"])

        def _connect(self):
            self.socket_connect_timeout = self._remaining()
            return super()._connect()

        def send_packed_command(self, *args, **kwargs):
            self.socket_timeout = self._remaining()
            if self._sock is not None:
                self._sock.settimeout(self.socket_timeout)
            return super().send_packed_command(*args, **kwargs)

        def read_response(self, *args, **kwargs):
            self.socket_timeout = self._remaining()
            if self._sock is not None:
                self._sock.settimeout(self.socket_timeout)
            return super().read_response(*args, **kwargs)

    class TCPConnection(DeadlineConnection, Connection):
        pass

    class TLSConnection(DeadlineConnection, SSLConnection):
        pass

    parameters = parse_url(url)
    parameters["connection_class"] = (
        TLSConnection if urlsplit(url).scheme == "rediss" else TCPConnection
    )
    pool = ConnectionPool(**parameters, **options, max_connections=1)
    client = Redis(connection_pool=pool)
    client.auto_close_connection_pool = True
    return client


class RedisKeyValueStore:
    capabilities = CapabilitySet(
        frozenset({"kv.get", "kv.put", "kv.compare_exchange", "kv.delete"})
    )

    def __init__(
        self,
        config: RedisKeyValueConfig,
        scope: StorageScope,
        *,
        namespace: str,
        client_factory=None,
    ):
        if namespace not in scope.namespaces:
            raise ScopeDenied()
        self._config = config
        self._scope = scope
        self._namespace = namespace
        self._client_factory = client_factory
        self._closed = False
        domain = json.dumps(
            [config.binding, scope.tenant_id, scope.system, namespace],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode()
        self._prefix = "nexent:si:kv:{" + sha256(domain).hexdigest() + "}:"

    @property
    def scope(self) -> StorageScope:
        return self._scope

    def _key(self, key: str) -> str:
        if not isinstance(key, str) or not key or len(key.encode()) > 1024:
            raise InvalidInput()
        if not key.startswith(self._scope.resource_prefix):
            raise ScopeDenied()
        return self._prefix + urlsafe_b64encode(key.encode()).decode()

    @contextmanager
    def _connection(self, context: OperationContext, *, write=False):
        try:
            get_running_loop()
        except RuntimeError:
            pass
        else:
            raise CapabilityUnsupported(operation_id=context.operation_id)
        if self._closed:
            raise Unavailable(operation_id=context.operation_id)
        timeout = min(context.remaining(), self._config.request_timeout)
        from redis.backoff import NoBackoff
        from redis.exceptions import RedisError
        from redis.retry import Retry

        factory = self._client_factory or _make_client
        try:
            with factory(
                self._config.url,
                decode_responses=False,
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
                retry=Retry(NoBackoff(), 0),
                retry_on_timeout=False,
                retry_on_error=[],
                context=context,
            ) as client:
                yield client
        except (RedisError, DeadlineExceeded, OperationCancelled):
            if write:
                raise OutcomeUnknown(operation_id=context.operation_id) from None
            try:
                context.remaining()
            except (DeadlineExceeded, OperationCancelled) as exc:
                raise exc from None
            raise Unavailable(operation_id=context.operation_id) from None

    def get(self, key: str, *, context: OperationContext) -> KVEntry | None:
        physical = self._key(key)
        with self._connection(context) as client:
            response = client.hmget(physical, "revision", "value")
        if not isinstance(response, (tuple, list)) or len(response) != 2:
            raise Unavailable(operation_id=context.operation_id)
        revision, value = response
        if revision is None and value is None:
            return None
        if not isinstance(revision, bytes) or not isinstance(value, bytes):
            raise Unavailable(operation_id=context.operation_id)
        try:
            return KVEntry(value, Revision(revision.decode("ascii")))
        except (UnicodeError, InvalidInput):
            raise Unavailable(operation_id=context.operation_id) from None

    def _mutate(self, key, action, expected, value, ttl, context):
        physical = self._key(key)
        if not isinstance(value, bytes) or len(value) > self._config.max_value_bytes:
            raise InvalidInput()
        if not isinstance(ttl, TTL):
            raise InvalidInput()
        milliseconds = ceil(ttl.seconds * 1000) if ttl.mode is TTLMode.DURATION else 0
        if milliseconds > 2**53 - 1:
            raise InvalidInput()
        revision = uuid4().hex
        with self._connection(context, write=True) as client:
            response = client.eval(
                _MUTATE,
                1,
                physical,
                action,
                expected,
                revision,
                value,
                ttl.mode.value,
                milliseconds,
            )
        if not isinstance(response, (tuple, list)) or len(response) != 2:
            raise OutcomeUnknown(operation_id=context.operation_id)
        matched, actual = response
        if (
            type(matched) is not int
            or matched not in {0, 1}
            or actual is not None
            and not isinstance(actual, bytes)
        ):
            raise OutcomeUnknown(operation_id=context.operation_id)
        try:
            return WriteReceipt(
                context.operation_id,
                bool(matched),
                Revision(actual.decode("ascii")) if actual else None,
            )
        except (UnicodeError, InvalidInput):
            raise OutcomeUnknown(operation_id=context.operation_id) from None

    def put(
        self, key: str, value: bytes, *, ttl: TTL, context: OperationContext
    ) -> WriteReceipt:
        return self._mutate(key, "put", "*", value, ttl, context)

    def compare_exchange(
        self,
        key: str,
        expected: Revision | Missing,
        value: bytes,
        *,
        ttl: TTL,
        context: OperationContext,
    ) -> WriteReceipt:
        if not isinstance(expected, Revision) and expected is not Missing.VALUE:
            raise InvalidInput()
        expected_value = (
            "missing" if expected is Missing.VALUE else "r:" + expected.value
        )
        return self._mutate(key, "cas", expected_value, value, ttl, context)

    def delete(
        self, key: str, *, expected: Revision | None = None, context: OperationContext
    ) -> WriteReceipt:
        if expected is not None and not isinstance(expected, Revision):
            raise InvalidInput()
        return self._mutate(
            key,
            "delete",
            "r:" + expected.value if expected else "*",
            b"",
            TTL(TTLMode.PRESERVE),
            context,
        )

    def get_many(self, keys, *, context):
        raise CapabilityUnsupported(operation_id=context.operation_id)

    def increment(self, key, delta, *, ttl, context):
        raise CapabilityUnsupported(operation_id=context.operation_id)

    def scan(self, prefix, page, *, context):
        raise CapabilityUnsupported(operation_id=context.operation_id)

    def close(self) -> None:
        # Each operation owns and closes its bounded connection pool.
        self._closed = True
