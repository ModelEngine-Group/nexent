# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run-scoped output retention for the AgentOS compatibility producer."""

import hashlib
import json
from dataclasses import dataclass

from contracts.constants.environment import RUNTIME_COMPLETED_TTL_SECONDS, RUNTIME_STREAM_MAX_LEN, RUNTIME_STREAM_TTL_SECONDS
from infrastructure.redis.run_state import runtime_state_service

START = "0-1"


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
