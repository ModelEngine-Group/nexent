# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded trusted retrieval progress shared between local MCP and SSE workers."""
import hashlib
import json
import logging

from infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)
STAGES = {"preparing_embeddings", "computing_similarity", "verifying_capabilities", "fallback_to_text", "searching_text", "searching_hybrid"}


def _key(scope):
    owner = [scope.tenant_id, scope.user_id, scope.agent_id, scope.conversation_id, scope.run_id]
    return "nl2agent:retrieval-progress:" + hashlib.sha256(json.dumps(owner).encode()).hexdigest()


class ProgressPublisher:
    def __init__(self, scope):
        self.scope = scope

    def publish(self, stage, completed=None, total=None):
        if stage not in STAGES:
            raise ValueError("Unknown retrieval stage")
        try:
            client = get_redis_client()
            if client is None:
                return
            key = _key(self.scope)
            sequence = client.incr(key + ":sequence")
            event = {"event": "resource_retrieval_progress", "agent_id": self.scope.agent_id,
                     "run_id": self.scope.run_id, "sequence": sequence, "stage": stage}
            if total and type(completed) is int and 0 <= completed <= total:
                event.update(completed=completed, total=total)
            pipe = client.pipeline()
            pipe.rpush(key, json.dumps(event))
            pipe.ltrim(key, -32, -1)
            pipe.expire(key, 900)
            pipe.expire(key + ":sequence", 900)
            pipe.execute()
        except Exception:
            # Progress is presentation only; existing state services remain authoritative.
            logger.warning("Resource retrieval progress unavailable")


def read_progress(scope, after):
    try:
        client = get_redis_client()
        if client is None:
            return []
        events = [json.loads(value) for value in client.lrange(_key(scope), 0, -1)]
        return sorted((event for event in events if event["sequence"] > after), key=lambda event: event["sequence"])
    except Exception:
        return []


def clear_progress(scope):
    try:
        client = get_redis_client()
        if client is not None:
            client.delete(_key(scope), _key(scope) + ":sequence")
    except Exception:
        logger.warning("Resource retrieval progress cleanup unavailable")
