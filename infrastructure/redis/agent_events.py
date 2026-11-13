# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run-scoped output retention for the AgentOS compatibility producer."""

import hashlib
import json
from dataclasses import dataclass

from contracts.constants.environment import RUNTIME_COMPLETED_TTL_SECONDS, RUNTIME_STREAM_MAX_LEN, RUNTIME_STREAM_TTL_SECONDS
from infrastructure.redis.run_state import runtime_state_service

START = "0-1"

# Check the retained tail and set the flag atomically with respect to terminal writes.
_RUN_STATE_SCRIPT = """
local tail = redis.call('XREVRANGE', KEYS[1], '+', '-', 'COUNT', 1)
if #tail == 0 then
    return nil
end
local fields = tail[1][2]
local status = 'running'
local terminal = false
for i = 1, #fields, 2 do
    if fields[i] == 'kind' then
        terminal = fields[i + 1] == 'terminal'
        if fields[i + 1] == 'start' then
            status = 'starting'
        end
    elseif fields[i] == 'status' then
        status = fields[i + 1]
    end
end
if terminal then
    return {tail[1][1], status, 0}
end
if ARGV[1] == 'stop' then
    redis.call('SET', KEYS[2], '1', 'EX', ARGV[2], 'NX')
end
return {tail[1][1], status, redis.call('EXISTS', KEYS[2])}
"""


@dataclass(frozen=True)
class RunJournal:
    tenant_id: str
    user_id: str
    conversation_id: int
    run_id: str

    @property
    def key(self) -> str:
        scope = json.dumps([self.tenant_id, self.user_id, self.conversation_id, self.run_id])
        return "runtime:agentos:events:" + hashlib.sha256(scope.encode()).hexdigest()

    def _append(self, redis_id, fields, ttl):
        with runtime_state_service.client.pipeline() as pipe:
            pipe.xadd(self.key, fields, id=redis_id, maxlen=max(1, RUNTIME_STREAM_MAX_LEN), approximate=False)
            pipe.expire(self.key, max(1, ttl))
            pipe.execute()

    def start(self) -> None:
        self._append(START, {"kind": "start"}, RUNTIME_STREAM_TTL_SECONDS)

    def append(self, index: int, chunk: str) -> None:
        self._append(f"{index}-0", {"kind": "chunk", "data": chunk}, RUNTIME_STREAM_TTL_SECONDS)

    def finish(self, index: int, status: str) -> None:
        self._append(f"{index}-0", {"kind": "terminal", "status": status}, RUNTIME_COMPLETED_TTL_SECONDS)

    @property
    def cancel_key(self) -> str:
        return f"{self.key}:cancel"

    def run_state(self, request_stop: bool = False) -> tuple[str, str, bool] | None:
        state = runtime_state_service.client.eval(
            _RUN_STATE_SCRIPT, 2, self.key, self.cancel_key,
            "stop" if request_stop else "inspect", max(1, RUNTIME_STREAM_TTL_SECONDS),
        )
        if state is None:
            return None
        event_id, status, cancellation_requested = state
        return event_id, status, bool(cancellation_requested)

    def is_stop_requested(self) -> bool:
        return bool(runtime_state_service.client.exists(self.cancel_key))

    def repair_terminal(self, status: str) -> None:
        # Finish an existing journal exactly once; never reconstruct expired output.
        runtime_state_service.client.eval(
            """
            local tail = redis.call('XREVRANGE', KEYS[1], '+', '-', 'COUNT', 1)
            if #tail == 0 then return end
            local fields = tail[1][2]
            for i = 1, #fields, 2 do
                if fields[i] == 'kind' and fields[i + 1] == 'terminal' then return end
            end
            local index = tonumber(string.match(tail[1][1], '^%d+'))
            local next_id = string.format('%.0f-0', index + 1)
            redis.call('XADD', KEYS[1], 'MAXLEN', '=', ARGV[2], next_id, 'kind', 'terminal', 'status', ARGV[1])
            redis.call('EXPIRE', KEYS[1], ARGV[3])
            """,
            1, self.key, status, max(1, RUNTIME_STREAM_MAX_LEN), max(1, RUNTIME_COMPLETED_TTL_SECONDS),
        )

    def replay(self, after_id):
        with runtime_state_service.client.pipeline() as pipe:
            pipe.xrange(self.key, min=after_id, max=after_id, count=1)
            pipe.xrange(self.key, min=f"({after_id}", count=100)
            pipe.xrevrange(self.key, count=1)
            return tuple(pipe.execute())

    def wait(self, after_id):
        client = runtime_state_service.client
        response = client.xread({self.key: after_id}, count=100, block=1000)
        if response:
            return response[0][1]
        return [] if client.exists(self.key) else None
