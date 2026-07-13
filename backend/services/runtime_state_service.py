import asyncio
import hashlib
import logging
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

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

logger = logging.getLogger(__name__)


class RuntimeStateService:
    """Redis-backed short-lived state used by multi-replica runtime services."""

    def __init__(self):
        self._client: Optional[Any] = None
        self._pod_name = socket.gethostname()

    @property
    def enabled(self) -> bool:
        return bool(RUNTIME_STATE_REDIS_URL)

    @property
    def client(self) -> Any:
        if not RUNTIME_STATE_REDIS_URL:
            raise ValueError("RUNTIME_STATE_REDIS_URL or REDIS_URL environment variable is not set")
        if redis is None:
            raise ValueError("redis package is not installed")
        if self._client is None:
            self._client = redis.from_url(
                RUNTIME_STATE_REDIS_URL,
                socket_timeout=5,
                socket_connect_timeout=5,
                decode_responses=True,
            )
        return self._client

    def _run_key(self, user_id: str, conversation_id: int) -> str:
        return f"runtime:run:{user_id}:{conversation_id}"

    def _cancel_key(self, user_id: str, conversation_id: int) -> str:
        return f"runtime:cancel:{user_id}:{conversation_id}"

    def _stream_key(self, user_id: str, conversation_id: int) -> str:
        return f"runtime:stream:{user_id}:{conversation_id}"

    def _stream_done_key(self, user_id: str, conversation_id: int) -> str:
        return f"runtime:stream:done:{user_id}:{conversation_id}"

    def _idempotency_key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"northbound:idempotency:{digest}"

    def _rate_key(self, tenant_id: str, minute_bucket: str) -> str:
        return f"northbound:rate:{tenant_id}:{minute_bucket}"

    def _expire_completed_runtime_keys(self, user_id: str, conversation_id: int) -> None:
        ttl = max(1, RUNTIME_COMPLETED_TTL_SECONDS)
        for key in (
            self._run_key(user_id, conversation_id),
            self._cancel_key(user_id, conversation_id),
            self._stream_key(user_id, conversation_id),
            self._stream_done_key(user_id, conversation_id),
        ):
            self.client.expire(key, ttl)

    def reset_stream(self, user_id: str, conversation_id: int) -> None:
        if not self.enabled:
            return
        try:
            self.client.delete(
                self._stream_key(user_id, conversation_id),
                self._stream_done_key(user_id, conversation_id),
            )
        except Exception as exc:
            logger.warning("Failed to reset runtime stream state: %s", exc)

    async def reset_stream_async(self, user_id: str, conversation_id: int) -> None:
        await asyncio.to_thread(self.reset_stream, user_id, conversation_id)

    def register_run(self, user_id: str, conversation_id: int, message_id: Optional[int] = None) -> None:
        if not self.enabled:
            return
        try:
            now = str(int(time.time()))
            payload = {
                "owner_pod": self._pod_name,
                "status": "running",
                "started_at": now,
                "updated_at": now,
            }
            if message_id is not None:
                payload["message_id"] = str(message_id)
            key = self._run_key(user_id, conversation_id)
            self.client.hset(key, mapping=payload)
            self.client.expire(key, RUNTIME_RUN_TTL_SECONDS)
            self.client.delete(self._cancel_key(user_id, conversation_id))
        except Exception as exc:
            logger.warning("Failed to register runtime run state: %s", exc)

    def mark_run_finished(self, user_id: str, conversation_id: int, status: str) -> None:
        if not self.enabled:
            return
        try:
            key = self._run_key(user_id, conversation_id)
            self.client.hset(key, mapping={
                "status": status,
                "updated_at": str(int(time.time())),
            })
            self._expire_completed_runtime_keys(user_id, conversation_id)
        except Exception as exc:
            logger.warning("Failed to mark runtime run state as finished: %s", exc)

    def get_run_state(self, user_id: str, conversation_id: int) -> Dict[str, str]:
        if not self.enabled:
            return {}
        try:
            return self.client.hgetall(self._run_key(user_id, conversation_id)) or {}
        except Exception as exc:
            logger.warning("Failed to get runtime run state: %s", exc)
            return {}

    async def get_run_state_async(self, user_id: str, conversation_id: int) -> Dict[str, str]:
        return await asyncio.to_thread(self.get_run_state, user_id, conversation_id)

    def set_cancel_signal(self, user_id: str, conversation_id: int) -> bool:
        if not self.enabled:
            return False
        try:
            self.client.setex(self._cancel_key(user_id, conversation_id), RUNTIME_CANCEL_TTL_SECONDS, self._pod_name)
            return True
        except Exception as exc:
            logger.warning("Failed to set runtime cancel signal: %s", exc)
            return False

    def is_cancelled(self, user_id: str, conversation_id: int) -> bool:
        if not self.enabled:
            return False
        try:
            return bool(self.client.get(self._cancel_key(user_id, conversation_id)))
        except Exception as exc:
            logger.warning("Failed to read runtime cancel signal: %s", exc)
            return False

    async def is_cancelled_async(self, user_id: str, conversation_id: int) -> bool:
        return await asyncio.to_thread(self.is_cancelled, user_id, conversation_id)

    def append_stream_event(self, user_id: str, conversation_id: int, chunk: str) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            stream_key = self._stream_key(user_id, conversation_id)
            event_id = self.client.xadd(
                stream_key,
                {"chunk": chunk},
                maxlen=RUNTIME_STREAM_MAX_LEN,
                approximate=True,
            )
            self.client.expire(stream_key, RUNTIME_STREAM_TTL_SECONDS)
            return event_id
        except Exception as exc:
            logger.warning("Failed to append runtime stream event: %s", exc)
            return None

    async def append_stream_event_async(self, user_id: str, conversation_id: int, chunk: str) -> Optional[str]:
        return await asyncio.to_thread(self.append_stream_event, user_id, conversation_id, chunk)

    def mark_stream_completed(
        self,
        user_id: str,
        conversation_id: int,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            payload = {
                "status": status,
                "updated_at": str(int(time.time())),
            }
            if error:
                payload["error"] = error
            done_key = self._stream_done_key(user_id, conversation_id)
            self.client.hset(done_key, mapping=payload)
            self._expire_completed_runtime_keys(user_id, conversation_id)
        except Exception as exc:
            logger.warning("Failed to mark runtime stream completed: %s", exc)

    async def mark_stream_completed_async(
        self,
        user_id: str,
        conversation_id: int,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        await asyncio.to_thread(self.mark_stream_completed, user_id, conversation_id, status, error)

    def get_stream_status(self, user_id: str, conversation_id: int) -> Dict[str, str]:
        if not self.enabled:
            return {}
        try:
            return self.client.hgetall(self._stream_done_key(user_id, conversation_id)) or {}
        except Exception as exc:
            logger.warning("Failed to get runtime stream status: %s", exc)
            return {}

    async def get_stream_status_async(self, user_id: str, conversation_id: int) -> Dict[str, str]:
        return await asyncio.to_thread(self.get_stream_status, user_id, conversation_id)

    def read_stream_events(
        self,
        user_id: str,
        conversation_id: int,
        after_id: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        if not self.enabled:
            return []
        try:
            min_id = "-" if after_id is None else f"({after_id}"
            events = self.client.xrange(self._stream_key(user_id, conversation_id), min=min_id)
            return [(event_id, values.get("chunk", "")) for event_id, values in events]
        except Exception as exc:
            logger.warning("Failed to read runtime stream events: %s", exc)
            return []

    async def read_stream_events_async(
        self,
        user_id: str,
        conversation_id: int,
        after_id: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        return await asyncio.to_thread(self.read_stream_events, user_id, conversation_id, after_id)

    def wait_for_stream_events(
        self,
        user_id: str,
        conversation_id: int,
        last_id: str,
        block_ms: int = 1000,
        count: int = 100,
    ) -> List[Tuple[str, str]]:
        if not self.enabled:
            return []
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
            logger.warning("Failed to wait for runtime stream events: %s", exc)
            return []

    async def wait_for_stream_events_async(
        self,
        user_id: str,
        conversation_id: int,
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

    def acquire_idempotency(self, key: str, ttl_seconds: int) -> bool:
        redis_key = self._idempotency_key(key)
        acquired = self.client.set(redis_key, self._pod_name, nx=True, ex=ttl_seconds)
        return bool(acquired)

    async def acquire_idempotency_async(self, key: str, ttl_seconds: int) -> bool:
        return await asyncio.to_thread(self.acquire_idempotency, key, ttl_seconds)

    def release_idempotency(self, key: str) -> None:
        self.client.delete(self._idempotency_key(key))

    async def release_idempotency_async(self, key: str) -> None:
        await asyncio.to_thread(self.release_idempotency, key)

    def consume_rate_limit(self, tenant_id: str, limit_per_minute: int) -> int:
        minute_bucket = str(int(time.time() // 60))
        key = self._rate_key(tenant_id, minute_bucket)
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, 120)
        count, _ = pipe.execute()
        count = int(count)
        if count > limit_per_minute:
            raise ValueError("rate limit exceeded")
        return count

    async def consume_rate_limit_async(self, tenant_id: str, limit_per_minute: int) -> int:
        return await asyncio.to_thread(self.consume_rate_limit, tenant_id, limit_per_minute)


runtime_state_service = RuntimeStateService()
