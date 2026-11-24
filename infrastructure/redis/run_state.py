# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import hashlib
import json
import logging
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

from nexent.core.concurrency import ManagedTaskSpec, ThreadManager

try:
    import redis
except ImportError:
    redis = None

from contracts.constants.environment import RUNTIME_CANCEL_TTL_SECONDS, RUNTIME_COMPLETED_TTL_SECONDS, RUNTIME_RUN_TTL_SECONDS, RUNTIME_STATE_REDIS_URL, RUNTIME_STREAM_MAX_LEN, RUNTIME_STREAM_TTL_SECONDS
from contracts.constants.environment import RUNTIME_CREATOR_LEASE_SECONDS

logger = logging.getLogger(__name__)


class RuntimeStateService:
    """Redis-backed short-lived state used by multi-replica runtime services."""

    def __init__(self):
        self._client: Optional[Any] = None
        self._pod_name = socket.gethostname()
        self._thread_manager: Optional[ThreadManager] = None
        self._distributed = None

    def configure_distributed(self, state):
        if self._distributed is not None and self._distributed is not state:
            raise RuntimeError('Runtime stream protocol is immutable after configuration')
        self._distributed = state

    @property
    def distributed_enabled(self):
        return self._distributed is not None

    def set_thread_manager(self, thread_manager: Optional[ThreadManager]) -> None:
        """Inject the process-local manager used for blocking Redis calls."""
        self._thread_manager = thread_manager

    async def _run_managed(self, task_name: str, fn, *args, **kwargs):
        if self._thread_manager is None:
            return fn(*args, **kwargs)
        return await self._thread_manager.run(
            "control-io",
            ManagedTaskSpec(
                task_name=task_name,
                owner="infrastructure.redis.run_state",
            ),
            fn,
            *args,
            **kwargs,
        )

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

    def _execution_cancel_key(self, user_id: str, conversation_id: int, execution_id: int) -> str:
        return f"runtime:execution:cancel:{user_id}:{conversation_id}:{execution_id}"

    def _stream_key(self, user_id: str, conversation_id: int) -> str:
        return f"runtime:stream:{user_id}:{conversation_id}"

    def _stream_done_key(self, user_id: str, conversation_id: int) -> str:
        return f"runtime:stream:done:{user_id}:{conversation_id}"

    def _replay_key(self, user_id: str, conversation_id: int) -> str:
        return f"runtime:replay:{user_id}:{conversation_id}"

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
            self._replay_key(user_id, conversation_id),
        ):
            self.client.expire(key, ttl)

    def mark_interrupted_run(self, user_id: str, conversation_id: int, message_id: int) -> None:
        """Finish the abandoned message's stream, not a newer turn of the same conversation."""
        self.client.eval("""
            local bound = redis.call('HGET', KEYS[1], 'message_id')
            if bound and bound ~= ARGV[1] then return 0 end
            if not bound and redis.call('HEXISTS', KEYS[1], 'execution_id') == 1 then return 0 end
            redis.call('HSET', KEYS[1], 'status', 'failed', 'updated_at', ARGV[2])
            redis.call('HSET', KEYS[2], 'status', 'failed', 'updated_at', ARGV[2])
            for _, key in ipairs(KEYS) do redis.call('EXPIRE', key, ARGV[3]) end
            return 1
        """, 5, self._run_key(user_id, conversation_id), self._stream_done_key(user_id, conversation_id),
            self._cancel_key(user_id, conversation_id), self._stream_key(user_id, conversation_id),
            self._replay_key(user_id, conversation_id), str(message_id), str(int(time.time())),
            max(1, RUNTIME_COMPLETED_TTL_SECONDS))

    def reset_stream(
        self, user_id: str, conversation_id: int, generation: Optional[str] = None, *, required: bool = False,
        execution_id: Optional[int] = None, run_ref=None,
    ) -> None:
        """Initialize an admitted new turn before its cancellation polls start."""
        if self._distributed is not None:
            return self._distributed.reset_stream(user_id, conversation_id, generation, run_ref=run_ref)
        if not self.enabled:
            if required:
                raise RuntimeError("Runtime stream coordination requires Redis")
            return
        try:
            if generation is not None:
                self.client.eval("""
                    redis.call('DEL', KEYS[1], KEYS[2], KEYS[3], KEYS[5])
                    redis.call('HSET', KEYS[4], 'generation', ARGV[1])
                    redis.call('HDEL', KEYS[4], 'replay_incomplete')
                    if ARGV[3] ~= '' then
                        redis.call('HSET', KEYS[4], 'execution_id', ARGV[3], 'status', 'preparing')
                        redis.call('HDEL', KEYS[4], 'message_id', 'owner_pod', 'started_at')
                    else
                        redis.call('HDEL', KEYS[4], 'execution_id')
                    end
                    redis.call('EXPIRE', KEYS[4], ARGV[2])
                    return 1
                """, 5, self._stream_key(user_id, conversation_id),
                    self._stream_done_key(user_id, conversation_id),
                    self._cancel_key(user_id, conversation_id), self._run_key(user_id, conversation_id),
                    self._replay_key(user_id, conversation_id), generation, RUNTIME_RUN_TTL_SECONDS,
                    str(execution_id) if execution_id is not None else "")
                return
            self.client.hdel(self._run_key(user_id, conversation_id), "generation", "execution_id", "replay_incomplete")
            self.client.delete(
                self._stream_key(user_id, conversation_id),
                self._stream_done_key(user_id, conversation_id),
                self._cancel_key(user_id, conversation_id),
                self._replay_key(user_id, conversation_id),
            )
        except Exception as exc:
            if required:
                raise
            logger.warning("Failed to reset runtime stream state: %s", exc)

    async def reset_stream_async(
        self, user_id: str, conversation_id: int, generation: Optional[str] = None, *, required: bool = False,
        execution_id: Optional[int] = None, run_ref=None,
    ) -> None:
        if run_ref is not None:
            await self._run_managed(
                "runtime-state-reset-stream", self.reset_stream, user_id, conversation_id, generation, run_ref=run_ref,
            )
        elif required or execution_id is not None:
            await self._run_managed("runtime-state-reset-stream", self.reset_stream, user_id, conversation_id,
                                    generation, required=required,
                                    **({"execution_id": execution_id} if execution_id is not None else {}))
        elif generation is None:
            await self._run_managed("runtime-state-reset-stream", self.reset_stream, user_id, conversation_id)
        else:
            await self._run_managed("runtime-state-reset-stream", self.reset_stream, user_id, conversation_id, generation)

    def claim_creator_run(
        self, user_id: str, conversation_id: int, generation: str, *, execution_id: Optional[int] = None,
    ) -> bool:
        """Fence Redis writes; an established database owner can replace an obsolete lease."""
        if not self.enabled:
            return True
        return bool(self.client.eval("""
            if ARGV[6] == '' and redis.call('HGET', KEYS[1], 'status') == 'running'
                and redis.call('EXISTS', KEYS[5]) == 1 then return 0 end
            redis.call('DEL', KEYS[2], KEYS[3], KEYS[4], KEYS[6])
            redis.call('HSET', KEYS[1], 'generation', ARGV[1], 'status', 'running',
                'owner_pod', ARGV[2], 'updated_at', ARGV[3])
            redis.call('HDEL', KEYS[1], 'replay_incomplete')
            if ARGV[6] ~= '' then
                redis.call('HSET', KEYS[1], 'execution_id', ARGV[6])
                redis.call('HDEL', KEYS[1], 'message_id', 'started_at')
            else
                redis.call('HDEL', KEYS[1], 'execution_id')
            end
            redis.call('EXPIRE', KEYS[1], ARGV[4])
            redis.call('SET', KEYS[5], ARGV[1], 'EX', ARGV[5])
            return 1
        """, 6, self._run_key(user_id, conversation_id), self._stream_key(user_id, conversation_id),
            self._stream_done_key(user_id, conversation_id), self._cancel_key(user_id, conversation_id),
            self._run_key(user_id, conversation_id) + ":creator-lease",
            self._replay_key(user_id, conversation_id),
            generation, self._pod_name, str(int(time.time())), RUNTIME_RUN_TTL_SECONDS,
            max(1, RUNTIME_CREATOR_LEASE_SECONDS), str(execution_id) if execution_id is not None else ""))

    async def claim_creator_run_async(
        self, user_id: str, conversation_id: int, generation: str, *, execution_id: Optional[int] = None,
    ) -> bool:
        return await self._run_managed(
            "creator-claim", self.claim_creator_run, user_id, conversation_id, generation,
            **({"execution_id": execution_id} if execution_id is not None else {}),
        )

    def creator_lease(self, user_id, conversation_id, generation, renew=False):
        if not self.enabled:
            return True
        return bool(self.client.eval("""
            if redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return 0 end
            if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
            if ARGV[2] == '1' then redis.call('EXPIRE', KEYS[2], ARGV[3]) end
            return 1
        """, 2, self._run_key(user_id, conversation_id),
            self._run_key(user_id, conversation_id) + ":creator-lease", generation,
            "1" if renew else "0", max(1, RUNTIME_CREATOR_LEASE_SECONDS)))

    async def creator_lease_async(self, user_id, conversation_id, generation, renew=False):
        return await self._run_managed("creator-lease", self.creator_lease,
                                      user_id, conversation_id, generation, renew)

    def cancel_creator_run(self, user_id, conversation_id, expected_generation=None):
        if not self.enabled:
            return False
        run_key = self._run_key(user_id, conversation_id)
        return bool(self.client.eval("""
            local generation = redis.call('HGET', KEYS[1], 'generation')
            if not generation or redis.call('GET', KEYS[2]) ~= generation
                or redis.call('HGET', KEYS[1], 'status') ~= 'running'
                or (ARGV[1] ~= '' and ARGV[1] ~= generation) then return 0 end
            redis.call('SETEX', KEYS[3], ARGV[2], '1')
            return 1
        """, 3, run_key, run_key + ':creator-lease', self._cancel_key(user_id, conversation_id),
            expected_generation or '', RUNTIME_CANCEL_TTL_SECONDS))

    def register_run(
        self, user_id: str, conversation_id: int | str, message_id: Optional[int] = None, *,
        run_ref=None, tenant_id: str | None = None,
    ) -> None:
        if self._distributed is not None:
            return self._distributed.register_run(user_id, conversation_id, message_id, run_ref=run_ref)
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
            if tenant_id is not None:
                payload["tenant_id"] = tenant_id
            key = self._run_key(user_id, conversation_id)
            self.client.hset(key, mapping=payload)
            self.client.expire(key, RUNTIME_RUN_TTL_SECONDS)
            # A stop arriving during preparation belongs to this admitted turn.
            # Only reset_stream may clear cancellation from the previous turn.
        except Exception as exc:
            logger.warning("Failed to register runtime run state: %s", exc)

    def mark_run_finished(self, user_id: str, conversation_id: int, status: str, generation: Optional[str] = None, *, run_ref=None) -> None:
        if self._distributed is not None:
            return self._distributed.mark_run_finished(user_id, conversation_id, status, generation, run_ref=run_ref)
        if not self.enabled:
            return
        try:
            key = self._run_key(user_id, conversation_id)
            if generation is not None:
                self.client.eval("""
                    if redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return 0 end
                    redis.call('HSET', KEYS[1], 'status', ARGV[2], 'updated_at', ARGV[3])
                    for _, key in ipairs(KEYS) do redis.call('EXPIRE', key, ARGV[4]) end
                    return 1
                """, 5, key, self._cancel_key(user_id, conversation_id),
                    self._stream_key(user_id, conversation_id), self._stream_done_key(user_id, conversation_id),
                    self._replay_key(user_id, conversation_id),
                    generation, status, str(int(time.time())), max(1, RUNTIME_COMPLETED_TTL_SECONDS))
                return
            self.client.hset(key, mapping={
                "status": status,
                "updated_at": str(int(time.time())),
            })
            self._expire_completed_runtime_keys(user_id, conversation_id)
        except Exception as exc:
            logger.warning("Failed to mark runtime run state as finished: %s", exc)

    def get_run_state(self, user_id: str, conversation_id: int, *, run_ref=None) -> Dict[str, str]:
        if self._distributed is not None:
            return self._distributed.get_run_state(user_id, conversation_id, run_ref=run_ref)
        if not self.enabled:
            return {}
        try:
            return self.client.hgetall(self._run_key(user_id, conversation_id)) or {}
        except Exception as exc:
            logger.warning("Failed to get runtime run state: %s", exc)
            return {}

    async def get_run_state_async(self, user_id: str, conversation_id: int, *, run_ref=None) -> Dict[str, str]:
        return await self._run_managed("runtime-state-get-run", self.get_run_state, user_id, conversation_id,
                                       **({'run_ref': run_ref} if run_ref is not None else {}))

    def set_cancel_signal(self, user_id: str, conversation_id: int, expected_generation: Optional[str] = None, *, run_ref=None) -> bool:
        if self._distributed is not None:
            return self._distributed.set_cancel_signal(user_id, conversation_id, expected_generation, run_ref=run_ref)
        if not self.enabled:
            return False
        try:
            if expected_generation is not None:
                return bool(self.client.eval("""
                    if redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return 0 end
                    redis.call('SETEX', KEYS[2], ARGV[2], ARGV[1])
                    return 1
                """, 2, self._run_key(user_id, conversation_id), self._cancel_key(user_id, conversation_id),
                    expected_generation, RUNTIME_CANCEL_TTL_SECONDS))
            self.client.setex(self._cancel_key(user_id, conversation_id), RUNTIME_CANCEL_TTL_SECONDS, self._pod_name)
            return True
        except Exception as exc:
            logger.warning("Failed to set runtime cancel signal: %s", exc)
            return False

    def is_cancelled(self, user_id: str, conversation_id: int, *, run_ref=None) -> bool:
        if self._distributed is not None:
            return self._distributed.is_cancelled(user_id, conversation_id, run_ref=run_ref)
        if not self.enabled:
            return False
        try:
            return bool(self.client.get(self._cancel_key(user_id, conversation_id)))
        except Exception as exc:
            logger.warning("Failed to read runtime cancel signal: %s", exc)
            return False

    async def is_cancelled_async(self, user_id: str, conversation_id: int, *, run_ref=None) -> bool:
        return await self._run_managed("runtime-state-is-cancelled", self.is_cancelled, user_id, conversation_id,
                                       **({'run_ref': run_ref} if run_ref is not None else {}))

    def request_execution_cancel(
        self, user_id: str, conversation_id: int | str, execution_id: int, expected_generation: Optional[str] = None,
    ) -> bool:
        """Record a stop against an authorized database execution, not a reusable conversation key."""
        return bool(self.client.eval("""
            if ARGV[2] ~= '' then
                if redis.call('HGET', KEYS[1], 'execution_id') ~= ARGV[1]
                    or redis.call('HGET', KEYS[1], 'generation') ~= ARGV[2] then return 0 end
            end
            redis.call('SET', KEYS[2], '1', 'EX', ARGV[3])
            return 1
        """, 2, self._run_key(user_id, conversation_id), self._execution_cancel_key(user_id, conversation_id, execution_id),
            str(execution_id), expected_generation or "", RUNTIME_CANCEL_TTL_SECONDS))

    async def request_execution_cancel_async(self, user_id, conversation_id, execution_id, expected_generation=None):
        return await self._run_managed(
            "runtime-execution-request-cancel", self.request_execution_cancel,
            user_id, conversation_id, execution_id, expected_generation,
        )

    def is_execution_cancelled(self, user_id, conversation_id, execution_id, generation) -> bool:
        try:
            owned, occurrence = self.client.mget(
                self._execution_cancel_key(user_id, conversation_id, execution_id), self._cancel_key(user_id, conversation_id),
            )
            return bool(owned or (generation and occurrence == generation))
        except Exception as exc:
            logger.warning("Failed to read Runtime execution cancel signal: %s", exc)
            return False

    async def is_execution_cancelled_async(self, user_id, conversation_id, execution_id, generation):
        return await self._run_managed(
            "runtime-execution-is-cancelled", self.is_execution_cancelled,
            user_id, conversation_id, execution_id, generation,
        )

    def append_stream_event(
        self, user_id: str, conversation_id: int, chunk: str, generation: Optional[str] = None,
        replay_update: Optional[dict] = None, *, run_ref=None,
    ) -> Optional[str]:
        if self._distributed is not None:
            return self._distributed.append_stream_event(
                user_id, conversation_id, chunk, run_ref=run_ref,
                **({'replay_update': replay_update} if replay_update is not None else {}),
            )
        if not self.enabled:
            return None
        try:
            if replay_update is not None:
                return self.client.eval("""
                    if ARGV[1] ~= '' and redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return false end
                    if ARGV[8] ~= '' then
                        local previous = tonumber(redis.call('HGET', KEYS[3], 'sequence') or '0')
                        if previous + 1 ~= tonumber(ARGV[8]) then
                            redis.call('HSET', KEYS[1], 'replay_incomplete', '1')
                            return false
                        end
                    end
                    local payload = cjson.decode(ARGV[6])
                    local field = 'part:' .. ARGV[5]
                    if ARGV[7] == '1' then
                        local old = redis.call('HGET', KEYS[3], field)
                        if not old then return redis.error_reply('Replay checkpoint prefix missing') end
                        old = cjson.decode(old)
                        payload.content = old.content .. payload.content
                    end
                    local id = redis.call('XADD', KEYS[2], 'MAXLEN', '~', ARGV[2], '*', 'chunk', ARGV[3])
                    redis.call('HSET', KEYS[3], field, cjson.encode(payload), 'cursor', id,
                        'count', tonumber(ARGV[5]) + 1, 'generation', ARGV[1])
                    if ARGV[8] ~= '' then redis.call('HSET', KEYS[3], 'sequence', ARGV[8]) end
                    redis.call('EXPIRE', KEYS[2], ARGV[4])
                    redis.call('EXPIRE', KEYS[3], ARGV[4])
                    return id
                """, 3, self._run_key(user_id, conversation_id), self._stream_key(user_id, conversation_id),
                    self._replay_key(user_id, conversation_id), generation or "", max(1, RUNTIME_STREAM_MAX_LEN),
                    chunk, RUNTIME_STREAM_TTL_SECONDS, replay_update["slot"],
                    json.dumps(replay_update["payload"], ensure_ascii=False), "1" if replay_update["append"] else "0",
                    str(replay_update.get("sequence", ""))) or None
            if generation is not None:
                return self.client.eval("""
                    if redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return false end
                    local id = redis.call('XADD', KEYS[2], 'MAXLEN', '~', ARGV[2], '*', 'chunk', ARGV[3])
                    redis.call('EXPIRE', KEYS[2], ARGV[4])
                    return id
                """, 2, self._run_key(user_id, conversation_id), self._stream_key(user_id, conversation_id),
                    generation, max(1, RUNTIME_STREAM_MAX_LEN), chunk, RUNTIME_STREAM_TTL_SECONDS) or None
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

    async def append_stream_event_async(
        self, user_id: str, conversation_id: int, chunk: str, generation: Optional[str] = None,
        replay_update: Optional[dict] = None, *, run_ref=None,
    ) -> Optional[str]:
        return await self._run_managed(
            "runtime-state-append-event",
            self.append_stream_event,
            user_id,
            conversation_id,
            chunk,
            **({'run_ref': run_ref} if run_ref is not None else {}),
            **({"generation": generation} if generation is not None else {}),
            **({"replay_update": replay_update} if replay_update is not None else {}),
        )

    def read_replay_checkpoint(self, user_id: str, conversation_id: int, *, run_ref=None) -> Optional[dict]:
        """Read records and their covered cursor in one atomic Redis operation."""
        if self._distributed is not None:
            return self._distributed.read_replay_checkpoint(user_id, conversation_id, run_ref=run_ref)
        if not self.enabled:
            return None
        data = self.client.hgetall(self._replay_key(user_id, conversation_id))
        return self._decode_checkpoint(data)

    @staticmethod
    def _decode_checkpoint(data):
        if not data:
            return None
        return {
            "entries": [json.loads(data[f"part:{index}"]) for index in range(int(data["count"]))],
            "cursor": data["cursor"], "generation": data.get("generation", ""),
        }

    async def read_replay_checkpoint_async(self, user_id: str, conversation_id: int, *, run_ref=None) -> Optional[dict]:
        return await self._run_managed(
            "runtime-state-read-replay", self.read_replay_checkpoint, user_id, conversation_id,
            **({'run_ref': run_ref} if run_ref is not None else {}),
        )

    def bind_execution_message(self, user_id, conversation_id, execution_id, message_id) -> bool:
        return bool(self.client.eval("""
            if redis.call('HGET', KEYS[1], 'execution_id') ~= ARGV[1] then return 0 end
            redis.call('HSET', KEYS[1], 'message_id', ARGV[2])
            return 1
        """, 1, self._run_key(user_id, conversation_id), str(execution_id), str(message_id)))

    async def bind_execution_message_async(self, user_id, conversation_id, execution_id, message_id):
        return await self._run_managed(
            "runtime-execution-bind-message", self.bind_execution_message,
            user_id, conversation_id, execution_id, message_id,
        )

    def read_execution_stream(self, user_id, conversation_id, execution_id):
        """Snapshot one bound generation, including its last output and terminal marker."""
        snapshot = self.client.eval("""
            if redis.call('HGET', KEYS[1], 'execution_id') ~= ARGV[1] then return {} end
            local generation = redis.call('HGET', KEYS[1], 'generation')
            if not generation then return {} end
            return {generation, redis.call('HGET', KEYS[2], 'status') or '',
                redis.call('HGET', KEYS[1], 'message_id') or '', redis.call('HGETALL', KEYS[3]),
                redis.call('EXISTS', KEYS[4]), redis.call('HGET', KEYS[2], 'event_count') or '',
                redis.call('HGET', KEYS[1], 'replay_incomplete') or ''}
        """, 4, self._run_key(user_id, conversation_id), self._stream_done_key(user_id, conversation_id),
            self._replay_key(user_id, conversation_id), self._stream_key(user_id, conversation_id), str(execution_id))
        if not snapshot:
            return None
        generation, status, message_id, entries, raw_exists, event_count, invalid = snapshot
        data = dict(zip(entries[::2], entries[1::2]))
        try:
            checkpoint = self._decode_checkpoint(data) if data.get("generation") == generation else None
        except (KeyError, TypeError, ValueError):
            checkpoint = None
        return {"generation": generation, "terminal_status": status or None, "checkpoint": checkpoint,
                "message_id": int(message_id) if message_id else None,
                "incomplete": bool(invalid or (event_count and data.get("sequence", "0") != event_count)
                                   or (checkpoint is None and (data or raw_exists)))}

    async def read_execution_stream_async(self, user_id, conversation_id, execution_id):
        return await self._run_managed(
            "runtime-execution-read-stream", self.read_execution_stream, user_id, conversation_id, execution_id,
        )

    def mark_stream_completed(
        self,
        user_id: str,
        conversation_id: int,
        status: str,
        error: Optional[str] = None,
        generation: Optional[str] = None,
        event_count: Optional[int] = None,
        *, run_ref=None,
    ) -> None:
        if self._distributed is not None:
            return self._distributed.mark_stream_completed(user_id, conversation_id, status, error, run_ref=run_ref)
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
            if generation is not None:
                self.client.eval("""
                    if redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return 0 end
                    redis.call('HSET', KEYS[2], 'status', ARGV[2], 'updated_at', ARGV[3])
                    if ARGV[5] ~= '' then redis.call('HSET', KEYS[2], 'event_count', ARGV[5]) end
                    redis.call('EXPIRE', KEYS[2], ARGV[4])
                    return 1
                """, 2, self._run_key(user_id, conversation_id), done_key, generation,
                    status, str(int(time.time())), max(1, RUNTIME_COMPLETED_TTL_SECONDS),
                    str(event_count) if event_count is not None else "")
                return
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
        generation: Optional[str] = None,
        event_count: Optional[int] = None,
        *, run_ref=None,
    ) -> None:
        await self._run_managed(
            "runtime-state-mark-stream-completed",
            self.mark_stream_completed,
            user_id,
            conversation_id,
            status,
            error,
            **({'run_ref': run_ref} if run_ref is not None else {}),
            **({"generation": generation} if generation is not None else {}),
            **({"event_count": event_count} if event_count is not None else {}),
        )

    def get_stream_status(self, user_id: str, conversation_id: int, *, run_ref=None) -> Dict[str, str]:
        if self._distributed is not None:
            return self._distributed.get_stream_status(user_id, conversation_id, run_ref=run_ref)
        if not self.enabled:
            return {}
        try:
            return self.client.hgetall(self._stream_done_key(user_id, conversation_id)) or {}
        except Exception as exc:
            logger.warning("Failed to get runtime stream status: %s", exc)
            return {}

    async def get_stream_status_async(self, user_id: str, conversation_id: int, *, run_ref=None) -> Dict[str, str]:
        return await self._run_managed(
            "runtime-state-get-stream-status",
            self.get_stream_status,
            user_id,
            conversation_id,
            **({'run_ref': run_ref} if run_ref is not None else {}),
        )

    def read_stream_events(
        self,
        user_id: str,
        conversation_id: int,
        after_id: Optional[str] = None,
        *, run_ref=None,
    ) -> List[Tuple[str, str]]:
        if self._distributed is not None:
            return self._distributed.read_stream_events(user_id, conversation_id, after_id, run_ref=run_ref)
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
        *, run_ref=None,
    ) -> List[Tuple[str, str]]:
        return await self._run_managed(
            "runtime-state-read-stream-events",
            self.read_stream_events,
            user_id,
            conversation_id,
            after_id,
            **({'run_ref': run_ref} if run_ref is not None else {}),
        )

    def wait_for_stream_events(
        self,
        user_id: str,
        conversation_id: int,
        last_id: str,
        block_ms: int = 1000,
        count: int = 100,
        *, run_ref=None,
    ) -> List[Tuple[str, str]]:
        if self._distributed is not None:
            return self._distributed.wait_for_stream_events(user_id, conversation_id, last_id, block_ms, count,
                                                           run_ref=run_ref)
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
        *, run_ref=None,
    ) -> List[Tuple[str, str]]:
        return await self._run_managed(
            "runtime-state-wait-stream-events",
            self.wait_for_stream_events,
            user_id,
            conversation_id,
            last_id,
            block_ms,
            count,
            **({'run_ref': run_ref} if run_ref is not None else {}),
        )

    def acquire_idempotency(self, key: str, ttl_seconds: int) -> bool:
        redis_key = self._idempotency_key(key)
        acquired = self.client.set(redis_key, self._pod_name, nx=True, ex=ttl_seconds)
        return bool(acquired)

    async def acquire_idempotency_async(self, key: str, ttl_seconds: int) -> bool:
        return await self._run_managed(
            "runtime-state-acquire-idempotency",
            self.acquire_idempotency,
            key,
            ttl_seconds,
        )

    def release_idempotency(self, key: str) -> None:
        self.client.delete(self._idempotency_key(key))

    async def release_idempotency_async(self, key: str) -> None:
        await self._run_managed(
            "runtime-state-release-idempotency",
            self.release_idempotency,
            key,
        )

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
        return await self._run_managed(
            "runtime-state-consume-rate-limit",
            self.consume_rate_limit,
            tenant_id,
            limit_per_minute,
        )


runtime_state_service = RuntimeStateService()
creator_runtime_state_service = RuntimeStateService()
