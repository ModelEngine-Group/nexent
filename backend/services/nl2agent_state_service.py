# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Persist the current resource card and its safe evidence independently of draft writes."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from nexent.core.concurrency import run_blocking
from redis.exceptions import RedisError, WatchError

from contracts.constants.environment import NL2AGENT_RESOURCE_STATE_TTL_SECONDS
from contracts.nl2agent_resources import ResourceCardAction, ResourceCardType
from infrastructure.redis.client import get_redis_client

ResourceState = dict[str, Any]


class ResourceStateError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ResourceScope:
    tenant_id: str
    user_id: str
    agent_id: int
    conversation_id: str
    run_id: str

    @property
    def legacy_key(self) -> str:
        owner = json.dumps([self.tenant_id, self.user_id, self.agent_id], ensure_ascii=False)
        return "nl2agent:resources:" + hashlib.sha256(owner.encode()).hexdigest()

    @property
    def key(self) -> str:
        conversation = hashlib.sha256(self.conversation_id.encode()).hexdigest()
        return self.legacy_key + ":" + conversation


def _decode_state(raw, legacy_raw, scope: ResourceScope) -> ResourceState | None:
    if raw:
        return json.loads(raw)
    legacy = json.loads(legacy_raw) if legacy_raw else None
    return legacy if legacy and legacy.get("conversation_id") == scope.conversation_id else None


def _update(scope: ResourceScope, change: Callable[[ResourceState | None], ResourceState]) -> ResourceState:
    try:
        client = get_redis_client()
        if client is None:
            raise ResourceStateError("resource_state_unavailable", retryable=True)
        for _ in range(4):
            with client.pipeline() as pipe:
                try:
                    pipe.watch(scope.key)
                    raw = pipe.get(scope.key)
                    legacy_raw = None
                    if not raw:
                        # Protect the source during migration without coupling
                        # subsequent conversation-local writes to old workers.
                        pipe.watch(scope.legacy_key)
                        legacy_raw = pipe.get(scope.legacy_key)
                    next_state = change(_decode_state(raw, legacy_raw, scope))
                    pipe.multi()
                    pipe.set(scope.key, json.dumps(next_state, ensure_ascii=False),
                             ex=NL2AGENT_RESOURCE_STATE_TTL_SECONDS)
                    pipe.execute()
                    return next_state
                except WatchError:
                    continue
    except (RedisError, ValueError) as exc:
        raise ResourceStateError("resource_state_unavailable", retryable=True) from exc
    raise ResourceStateError("resource_state_conflict", retryable=True)


async def update_resource_state(
    scope: ResourceScope, change: Callable[[ResourceState | None], ResourceState],
) -> ResourceState:
    return await run_blocking(
        "nl2agent-resource-state", _update, scope, change, lane="control-io",
        owner="services.nl2agent_state_service",
    )


def _read(scope: ResourceScope) -> ResourceState | None:
    try:
        client = get_redis_client()
        if client is None:
            raise ResourceStateError("resource_state_unavailable", retryable=True)
        raw = client.get(scope.key)
        legacy_raw = client.get(scope.legacy_key) if not raw else None
        return _decode_state(raw, legacy_raw, scope)
    except (RedisError, ValueError) as exc:
        raise ResourceStateError("resource_state_unavailable", retryable=True) from exc


async def read_resource_state(scope: ResourceScope) -> ResourceState | None:
    return await run_blocking(
        "nl2agent-read-resource-state", _read, scope, lane="control-io",
        owner="services.nl2agent_state_service",
    )


def require_current_run(state: ResourceState | None, scope: ResourceScope) -> ResourceState:
    if not state or state["conversation_id"] != scope.conversation_id:
        raise ResourceStateError("resource_state_expired")
    if state["run_id"] != scope.run_id:
        raise ResourceStateError("resource_state_conflict")
    return state


def require_current_card(
    state: ResourceState | None, scope: ResourceScope, subtype: str, action: ResourceCardAction,
) -> ResourceState:
    if not state or state["conversation_id"] != scope.conversation_id:
        raise ResourceStateError("resource_state_expired")
    if state["version"] != action.state_version or state["card"] != {"id": action.card_id, "subtype": subtype}:
        raise ResourceStateError("resource_card_stale")
    return state


def issue_card(state: ResourceState, subtype: ResourceCardType) -> ResourceState:
    return {**state, "version": state["version"] + 1, "card": {"id": uuid4().hex, "subtype": subtype}}
