# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ops publication definitions using the shared event protocol."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from uuid import NAMESPACE_URL, UUID, uuid5

from infrastructure.monitoring.contracts import Fact, FactKind, Outcome, stable_key
from infrastructure.monitoring.facts import SkillFact


@dataclass(frozen=True)
class MonitoringKind:
    """A fact schema and fields for the shared indices, with optional daily publication."""

    fact_model: type[Fact]
    aggregate: Callable[[Iterable[dict]], Iterable[tuple[str, dict]]] | None = None
    fact_fields: Mapping[str, str] = field(default_factory=dict)
    daily_fields: Mapping[str, str] = field(default_factory=dict)


def day_id(tenant_id: str, fact_kind: str, day: date) -> UUID:
    return uuid5(NAMESPACE_URL, stable_key("nexent-ops-monitoring", tenant_id, fact_kind, day.isoformat()))
