import asyncio
import hashlib
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import redis
except ImportError:
    redis = None

from consts.const import (
    RUNTIME_CANCEL_TTL_SECONDS,
    RUNTIME_COMPLETED_TTL_SECONDS,
    RUNTIME_RUN_TTL_SECONDS,
    RUNTIME_STATE_REDIS_URL,
    RUNTIME_STREAM_MAX_LEN,
    RUNTIME_STREAM_TTL_SECONDS,
)
from consts.exceptions import DistributedStateUnavailable

logger = logging.getLogger(__name__)


class RuntimeExecutionSuperseded(Exception):
    """Raised when an old execution attempts to mutate a newer run."""


class RuntimeStateService:
    """Redis-backed source of truth for multi-replica runtime services."""

    _REGISTER_RUN_SCRIPT = """
        redis.call('DEL', KEYS[1], KEYS[2], KEYS[3], KEYS[4])
        redis.call('HSET', KEYS[1],
            'execution_id', ARGV[1],
            'status', 'running',
            'started_at', ARGV[2],
            'updated_at', ARGV[2])
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
        return ARGV[1]
    """

    _HEARTBEAT_RUN_SCRIPT = """
        if redis.call('HGET', KEYS[1], 'execution_id') ~= ARGV[1] then
            return 0
        end
        if redis.call('HGET', KEYS[1], 'status') ~= 'running' then
            return 0
        end
        redis.call('HSET', KEYS[1], 'updated_at', ARGV[2])
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
        return 1
    """

    _FINISH_RUN_SCRIPT = """
        local execution_id = redis.call('HGET', KEYS[1], 'execution_id')
        if execution_id ~= ARGV[1] then
            return 0
        end
        local current_status = redis.call('HGET', KEYS[1], 'status')
        if current_status ~= 'running' then
            if current_status == ARGV[2] then
                return 1
            end
            return 0
        end
        redis.call('HSET', KEYS[1],
            'status', ARGV[2],
            'updated_at', ARGV[3])
        redis.call('HSET', KEYS[4],
            'execution_id', ARGV[1],
            'status', ARGV[2],
            'updated_at', ARGV[3])
        if ARGV[5] ~= '' then
            redis.call('HSET', KEYS[1], 'error', ARGV[5])
            redis.call('HSET', KEYS[4], 'error', ARGV[5])
        else
            redis.call('HDEL', KEYS[1], 'error')
            redis.call('HDEL', KEYS[4], 'error')
        end
        redis.call('DEL', KEYS[2])
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
        redis.call('EXPIRE', KEYS[3], tonumber(ARGV[6]))
        redis.call('EXPIRE', KEYS[4], tonumber(ARGV[4]))
        return 1
    """

    _SET_CANCEL_SCRIPT = """
        local execution_id = redis.call('HGET', KEYS[1], 'execution_id')
        if not execution_id then
            return 0
        end
        if redis.call('HGET', KEYS[1], 'status') ~= 'running' then
            return 0
        end
        redis.call('SET', KEYS[2], execution_id, 'EX', tonumber(ARGV[1]))
        return 1
    """

    _IS_CANCELLED_SCRIPT = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return 1
        end
        return 0
    """

    _APPEND_STREAM_SCRIPT = """
        if redis.call('HGET', KEYS[1], 'execution_id') ~= ARGV[1] then
            return false
        end
        if redis.call('HGET', KEYS[1], 'status') ~= 'running' then
            return false
        end
        local event_id = redis.call('XADD', KEYS[2], 'MAXLEN', '~', tonumber(ARGV[3]), '*', 'chunk', ARGV[2])
        redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
        return event_id
    """

    _RELEASE_IDEMPOTENCY_SCRIPT = """
        if redis.call('GET', KEYS[1]) ~= ARGV[1] then
            return 0
        end
        return redis.call('DEL', KEYS[1])
    """

    def __init__(self, client: Optional[Any] = None):
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        if not RUNTIME_STATE_REDIS_URL:
            raise DistributedStateUnavailable("RUNTIME_STATE_REDIS_URL or REDIS_URL is not configured.")
        if redis is None:
            raise DistributedStateUnavailable("The redis package is not installed.")
        try:
            self._client = redis.from_url(
                RUNTIME_STATE_REDIS_URL,
                socket_timeout=5,
                socket_connect_timeout=5,
                decode_responses=True,
            )
        except Exception as exc:
            self._raise_unavailable("create Redis client", exc)
        return self._client

    @staticmethod
    def _now() -> str:
        return str(int(time.time()))

    @staticmethod
    def _raise_unavailable(operation: str, exc: Exception) -> None:
        if isinstance(exc, DistributedStateUnavailable):
            raise exc
        logger.error("Distributed state operation failed during %s: %s", operation, exc)
        raise DistributedStateUnavailable(f"Distributed state is unavailable during {operation}.") from exc

    def _eval(self, operation: str, script: str, keys: List[str], args: List[Any]) -> Any:
        try:
            return self.client.eval(script, len(keys), *keys, *args)
        except Exception as exc:
            self._raise_unavailable(operation, exc)

    def _run_key(self, user_id: str, conversation_id: Union[int, str]) -> str:
        return f"runtime:run:{user_id}:{conversation_id}"

    def _cancel_key(self, user_id: str, conversation_id: Union[int, str]) -> str:
        return f"runtime:cancel:{user_id}:{conversation_id}"

    def _stream_key(self, user_id: str, conversation_id: Union[int, str]) -> str:
        return f"runtime:stream:{user_id}:{conversation_id}"

    def _stream_done_key(self, user_id: str, conversation_id: Union[int, str]) -> str:
        return f"runtime:stream:done:{user_id}:{conversation_id}"

    def _runtime_keys(self, user_id: str, conversation_id: Union[int, str]) -> List[str]:
        return [
            self._run_key(user_id, conversation_id),
            self._cancel_key(user_id, conversation_id),
            self._stream_key(user_id, conversation_id),
            self._stream_done_key(user_id, conversation_id),
        ]

    def _idempotency_key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"northbound:idempotency:{digest}"

    def _rate_key(self, tenant_id: str, minute_bucket: str) -> str:
        return f"northbound:rate:{tenant_id}:{minute_bucket}"

    def ping(self) -> bool:
        try:
            if not self.client.ping():
                raise RuntimeError("Redis PING returned false")
            return True
        except Exception as exc:
            self._raise_unavailable("Redis PING", exc)

    async def ping_async(self) -> bool:
        return await asyncio.to_thread(self.ping)

    def register_run(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: Optional[str] = None,
    ) -> str:
        execution_id = execution_id or uuid.uuid4().hex
        result = self._eval(
            "register runtime run",
            self._REGISTER_RUN_SCRIPT,
            self._runtime_keys(user_id, conversation_id),
            [execution_id, self._now(), max(1, RUNTIME_RUN_TTL_SECONDS)],
        )
        return str(result or execution_id)

    async def register_run_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: Optional[str] = None,
    ) -> str:
        return await asyncio.to_thread(
            self.register_run,
            user_id,
            conversation_id,
            execution_id,
        )

    def heartbeat_run(self, user_id: str, conversation_id: Union[int, str], execution_id: str) -> bool:
        result = self._eval(
            "heartbeat runtime run",
            self._HEARTBEAT_RUN_SCRIPT,
            [self._run_key(user_id, conversation_id)],
            [execution_id, self._now(), max(1, RUNTIME_RUN_TTL_SECONDS)],
        )
        return bool(result)

    async def heartbeat_run_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: str,
    ) -> bool:
        return await asyncio.to_thread(self.heartbeat_run, user_id, conversation_id, execution_id)

    def mark_run_finished(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        if status not in {"completed", "failed", "stopped"}:
            raise ValueError(f"Unsupported runtime terminal status: {status}")
        result = self._eval(
            "finish runtime run",
            self._FINISH_RUN_SCRIPT,
            self._runtime_keys(user_id, conversation_id),
            [
                execution_id,
                status,
                self._now(),
                max(1, RUNTIME_COMPLETED_TTL_SECONDS),
                error or "",
                max(1, RUNTIME_STREAM_TTL_SECONDS),
            ],
        )
        return bool(result)

    async def mark_run_finished_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self.mark_run_finished,
            user_id,
            conversation_id,
            execution_id,
            status,
            error,
        )

    def get_run_state(self, user_id: str, conversation_id: Union[int, str]) -> Dict[str, str]:
        try:
            return self.client.hgetall(self._run_key(user_id, conversation_id)) or {}
        except Exception as exc:
            self._raise_unavailable("read runtime run", exc)

    async def get_run_state_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
    ) -> Dict[str, str]:
        return await asyncio.to_thread(self.get_run_state, user_id, conversation_id)

    def set_cancel_signal(self, user_id: str, conversation_id: Union[int, str]) -> bool:
        result = self._eval(
            "set runtime cancel signal",
            self._SET_CANCEL_SCRIPT,
            [self._run_key(user_id, conversation_id), self._cancel_key(user_id, conversation_id)],
            [max(1, RUNTIME_CANCEL_TTL_SECONDS)],
        )
        return bool(result)

    async def set_cancel_signal_async(self, user_id: str, conversation_id: Union[int, str]) -> bool:
        return await asyncio.to_thread(self.set_cancel_signal, user_id, conversation_id)

    def is_cancelled(self, user_id: str, conversation_id: Union[int, str], execution_id: str) -> bool:
        result = self._eval(
            "read runtime cancel signal",
            self._IS_CANCELLED_SCRIPT,
            [self._cancel_key(user_id, conversation_id)],
            [execution_id],
        )
        return bool(result)

    async def is_cancelled_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: str,
    ) -> bool:
        return await asyncio.to_thread(self.is_cancelled, user_id, conversation_id, execution_id)

    def append_stream_event(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: str,
        chunk: str,
    ) -> str:
        result = self._eval(
            "append runtime stream event",
            self._APPEND_STREAM_SCRIPT,
            [self._run_key(user_id, conversation_id), self._stream_key(user_id, conversation_id)],
            [execution_id, chunk, max(1, RUNTIME_STREAM_MAX_LEN), max(1, RUNTIME_STREAM_TTL_SECONDS)],
        )
        if not result:
            raise RuntimeExecutionSuperseded("Runtime execution is no longer current.")
        return str(result)

    async def append_stream_event_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: str,
        chunk: str,
    ) -> str:
        return await asyncio.to_thread(
            self.append_stream_event,
            user_id,
            conversation_id,
            execution_id,
            chunk,
        )

    def mark_stream_completed(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        return self.mark_run_finished(user_id, conversation_id, execution_id, status, error)

    async def mark_stream_completed_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        execution_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        return await self.mark_run_finished_async(user_id, conversation_id, execution_id, status, error)

    def get_stream_status(self, user_id: str, conversation_id: Union[int, str]) -> Dict[str, str]:
        try:
            return self.client.hgetall(self._stream_done_key(user_id, conversation_id)) or {}
        except Exception as exc:
            self._raise_unavailable("read runtime stream status", exc)

    async def get_stream_status_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
    ) -> Dict[str, str]:
        return await asyncio.to_thread(self.get_stream_status, user_id, conversation_id)

    def read_stream_events(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        after_id: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        try:
            min_id = "-" if after_id is None else f"({after_id}"
            events = self.client.xrange(self._stream_key(user_id, conversation_id), min=min_id)
            return [(event_id, values.get("chunk", "")) for event_id, values in events]
        except Exception as exc:
            self._raise_unavailable("read runtime stream events", exc)

    async def read_stream_events_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        after_id: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        return await asyncio.to_thread(self.read_stream_events, user_id, conversation_id, after_id)

    def wait_for_stream_events(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        last_id: str,
        block_ms: int = 1000,
        count: int = 100,
    ) -> List[Tuple[str, str]]:
        try:
            response = self.client.xread(
                {self._stream_key(user_id, conversation_id): last_id},
                count=count,
                block=block_ms,
            )
            if not response:
                return []
            _, events = response[0]
            return [(event_id, values.get("chunk", "")) for event_id, values in events]
        except Exception as exc:
            self._raise_unavailable("wait for runtime stream events", exc)

    async def wait_for_stream_events_async(
        self,
        user_id: str,
        conversation_id: Union[int, str],
        last_id: str,
        block_ms: int = 1000,
        count: int = 100,
    ) -> List[Tuple[str, str]]:
        return await asyncio.to_thread(
            self.wait_for_stream_events,
            user_id,
            conversation_id,
            last_id,
            block_ms,
            count,
        )

    def acquire_idempotency(self, key: str, ttl_seconds: int) -> Optional[str]:
        token = uuid.uuid4().hex
        try:
            acquired = self.client.set(
                self._idempotency_key(key),
                token,
                nx=True,
                ex=max(1, ttl_seconds),
            )
            return token if acquired else None
        except Exception as exc:
            self._raise_unavailable("acquire northbound idempotency", exc)

    async def acquire_idempotency_async(self, key: str, ttl_seconds: int) -> Optional[str]:
        return await asyncio.to_thread(self.acquire_idempotency, key, ttl_seconds)

    def release_idempotency(self, key: str, token: str) -> bool:
        result = self._eval(
            "release northbound idempotency",
            self._RELEASE_IDEMPOTENCY_SCRIPT,
            [self._idempotency_key(key)],
            [token],
        )
        return bool(result)

    async def release_idempotency_async(self, key: str, token: str) -> bool:
        return await asyncio.to_thread(self.release_idempotency, key, token)

    def consume_rate_limit(self, tenant_id: str, limit_per_minute: int) -> int:
        minute_bucket = str(int(time.time() // 60))
        key = self._rate_key(tenant_id, minute_bucket)
        try:
            pipe = self.client.pipeline()
            pipe.incr(key)
            pipe.expire(key, 120)
            count, _ = pipe.execute()
        except Exception as exc:
            self._raise_unavailable("consume northbound rate limit", exc)
        count = int(count)
        if count > limit_per_minute:
            raise ValueError("rate limit exceeded")
        return count

    async def consume_rate_limit_async(self, tenant_id: str, limit_per_minute: int) -> int:
        return await asyncio.to_thread(self.consume_rate_limit, tenant_id, limit_per_minute)


runtime_state_service = RuntimeStateService()
