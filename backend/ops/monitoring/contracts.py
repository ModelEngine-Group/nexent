# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared transport-safe monitoring facts and identifiers."""

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


FactKind = Literal["model", "mcp_tool", "agent", "skill"]
Outcome = Literal["started", "succeeded", "failed", "cancelled", "unknown"]
MAX_LONG = 2**63 - 1


class Fact(BaseModel):
    """Common envelope extended by a registered monitoring kind."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal[1] = 1
    tenant_id: str = Field(min_length=1, max_length=100)
    fact_kind: FactKind
    fact_id: str = Field(min_length=1, max_length=128)
    call_context_id: str = Field(min_length=1, max_length=128)
    root_run_id: str | None = Field(default=None, max_length=128)
    agent_run_id: str | None = Field(default=None, max_length=128)
    agent_id: int | None = Field(default=None, gt=0, le=2147483647)
    usage_source: Literal["formal"] = "formal"
    initiator_group_ids: tuple[int, ...] | None = Field(default=None, max_length=200)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    record_revision: int = Field(ge=1, le=MAX_LONG)
    outcome: Outcome
    duration_ms: int | None = Field(default=None, ge=0, le=MAX_LONG)

    @model_validator(mode="after")
    def check_observation(self):
        if any(not 0 < group <= 2147483647 for group in (self.initiator_group_ids or ())):
            raise ValueError("Invalid monitoring group ID")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("Monitoring end precedes dispatch")
        if self.outcome == "started" and (self.ended_at is not None or self.duration_ms is not None):
            raise ValueError("An ongoing attempt cannot carry terminal measurements")
        return self

    def document(self, zone: ZoneInfo) -> dict:
        result = self.model_dump(mode="json", exclude_none=True)
        groups = self.initiator_group_ids
        result["initiator_group_ids"] = sorted(set(groups or ()))
        result["group_snapshot_state"] = "unknown" if groups is None else "known"
        result["group_key"] = stable_key(result["group_snapshot_state"], result["initiator_group_ids"])
        result["partition_anchor_at"] = self.partition_anchor().isoformat()
        result["statistic_date"] = self.statistic_day(zone).isoformat()
        return result

    def partition_anchor(self) -> datetime:
        return self.started_at.astimezone(timezone.utc)

    def statistic_day(self, zone: ZoneInfo) -> date:
        return self.started_at.astimezone(zone).date()


class SkillFact(Fact):
    """A formal Skill guide read or script start."""

    fact_kind: Literal["skill"] = "skill"
    skill_id: str = Field(min_length=1, max_length=128)
    skill_name: str = Field(min_length=1, max_length=200)
    triggered_at: AwareDatetime
    trigger_kind: Literal["guide_read", "script_started"]


@dataclass(frozen=True)
class MonitoringKind:
    """A fact schema, daily reducer, and optional fields for the shared indices."""

    fact_model: type[Fact]
    aggregate: Callable[[Iterable[dict]], Iterable[tuple[str, dict]]]
    fact_fields: Mapping[str, str] = field(default_factory=dict)
    daily_fields: Mapping[str, str] = field(default_factory=dict)


def stable_key(*parts: object) -> str:
    """Generate an unambiguous key without exposing caller identifiers."""
    return sha256(json.dumps(parts, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def day_id(tenant_id: str, fact_kind: str, day: date) -> UUID:
    return uuid5(NAMESPACE_URL, stable_key("nexent-ops-monitoring", tenant_id, fact_kind, day.isoformat()))
