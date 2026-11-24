# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SDK-owned, transport-neutral observations for Skill usage."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import sha256
from threading import Lock
from typing import Literal

from nexent.monitor.facts import get_fact_sink
from nexent.monitor.monitoring import get_agent_monitoring_context


logger = logging.getLogger(__name__)
SkillTriggerKind = Literal["guide_read", "script_started"]
_MAX_SEEN_FACTS = 8192


class _RunDedupState:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.fact_ids: set[str] = set()
        self.lock = Lock()


_run_dedup_state: ContextVar[_RunDedupState | None] = ContextVar(
    "skill_usage_run_dedup_state", default=None,
)


def _dedup_state(run_id: str) -> _RunDedupState:
    state = _run_dedup_state.get()
    if state is None or state.run_id != run_id:
        state = _RunDedupState(run_id)
        _run_dedup_state.set(state)
    return state


class SkillUsageObservation:
    """Emit one idempotent Skill usage fact without coupling to an agent core."""

    def __init__(self, payload: dict | None = None, sink=None):
        self.payload = payload
        self.sink = sink
        self._dedup = _dedup_state(payload["agent_run_id"]) if payload else None
        self._triggered = False
        self._lock = Lock()

    @classmethod
    def for_skill(
        cls,
        skill_id: str | int | None,
        skill_name: str,
        trigger_kind: SkillTriggerKind,
    ) -> "SkillUsageObservation":
        sink = get_fact_sink()
        context = get_agent_monitoring_context()
        if sink is None or context is None or not context.tenant_id or not context.monitoring_run_id or not skill_id:
            return cls()

        skill_id = str(skill_id)
        fact_id = sha256(json.dumps(
            ["skill_use", context.tenant_id, context.monitoring_run_id, skill_id],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        return cls({
            "tenant_id": context.tenant_id,
            "fact_kind": "skill",
            "fact_id": fact_id,
            "call_context_id": context.monitoring_run_id,
            "root_run_id": context.monitoring_root_run_id or context.monitoring_run_id,
            "agent_run_id": context.monitoring_run_id,
            "agent_id": context.agent_id,
            "initiator_group_ids": context.monitoring_group_ids,
            "skill_id": skill_id,
            "skill_name": skill_name,
            "trigger_kind": trigger_kind,
            "started_at": now,
            "triggered_at": now,
            "record_revision": 1,
            "outcome": "succeeded",
            "duration_ms": 0,
            "usage_source": "formal",
        }, sink)

    def trigger(self) -> None:
        """Send the observation; monitoring failures never affect the Skill call."""
        with self._lock:
            if self._triggered or self.sink is None or self.payload is None:
                return
            self._triggered = True
        fact_id = self.payload["fact_id"]
        with self._dedup.lock:
            if fact_id in self._dedup.fact_ids:
                return
            if len(self._dedup.fact_ids) >= _MAX_SEEN_FACTS:
                self._dedup.fact_ids.pop()
            self._dedup.fact_ids.add(fact_id)
        try:
            self.sink(self.payload)
        except Exception as error:
            with self._dedup.lock:
                self._dedup.fact_ids.discard(fact_id)
            logger.warning("Skill monitoring observation rejected error=%s", type(error).__name__)


def observe_skill_usage(
    skill_id: str | int | None,
    skill_name: str,
    trigger_kind: SkillTriggerKind,
) -> None:
    """Best-effort convenience entry point used by all Skill integrations."""
    SkillUsageObservation.for_skill(skill_id, skill_name, trigger_kind).trigger()
