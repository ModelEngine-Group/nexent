# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project buffered per-agent memory operations into one detailed preparation phase."""

from __future__ import annotations

import json
import math

from .duration import duration_attributes
from .local_content import safe_local_content


_MEMORY_PHASES = {
    "memory.initialize",
    "memory.external_search",
    "memory.load_context",
    "memory.presearch",
    "memory.retrieve",
}


def _body(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value


def _summarize(group):
    result, members = group["record"], group["members"]
    attrs = result["attributes"]
    first = min(record["started_monotonic"] for _, record in members)
    ends, steps, positions = [], [], {}
    status = "success"
    for index, record in members:
        values = record["attributes"]
        duration = values.get("nexent.duration_ms")
        valid = type(duration) in (int, float) and math.isfinite(duration) and duration >= 0
        if valid:
            ends.append(record["started_monotonic"] + duration / 1000)
        state = values.get("nexent.business_status")
        if not state:
            state = "failed" if record["status"] == "error" else "success"
        if state == "failed" or state == "cancelled" and status == "success":
            status = state
        step = {
            "name": record["name"],
            "status": state,
            "started_at_ns": str(record["started_at_ns"]),
            "finished_at_ns": str(record["finished_at_ns"]),
            "duration_ms": duration if valid else None,
            "parent_step": positions.get(record["parent"]),
        }
        for slot in ("input", "output"):
            if f"{slot}.value" in values:
                step[slot] = _body(values[f"{slot}.value"])
            if f"nexent.availability.{slot}" in values:
                step.setdefault("availability", {})[slot] = values[f"nexent.availability.{slot}"]
        if "error.type" in values:
            step["error_type"] = values["error.type"]
        if values.get("nexent.trajectory.gap"):
            attrs["nexent.trajectory.gap"] = True
        if record["name"] == "memory.presearch" and "input.value" in values:
            attrs["input.value"] = values["input.value"]
            attrs.pop("nexent.availability.input", None)
        positions[index] = len(steps)
        steps.append(step)
    attrs.pop("nexent.duration_ms", None)
    attrs.update(duration_attributes(first, max(ends) if len(ends) == len(members) else None))
    attrs["nexent.business_status"] = status
    attrs["output.value"] = safe_local_content({"steps": steps})
    attrs.pop("nexent.availability.output", None)
    result.update(
        started_at_ns=min(record["started_at_ns"] for _, record in members),
        finished_at_ns=max(record["finished_at_ns"] for _, record in members),
        started_monotonic=first,
        status="error" if status in {"failed", "cancelled"} else "success",
    )


def group_memory_preparation(records):
    """Merge adjacent same-agent siblings and their nested memory work without mutating facts."""
    projected, groups, aliases, membership, active = [], [], {}, {}, {}
    for index, record in enumerate(records):
        parent, attrs = record["parent"], record["attributes"]
        agent = attrs.get("agent.id")
        memory = record["name"] in _MEMORY_PHASES
        group = membership.get(parent) if memory else None
        if group is not None and agent and agent != group["agent"]:
            group = None
        if group is None and memory and agent:
            candidate = active.get(parent)
            if candidate is not None and candidate["agent"] == agent:
                group = candidate
            else:
                merged = {**record, "name": "memory.prepare", "parent": aliases.get(parent), "attributes": dict(attrs)}
                group = {"agent": agent, "record": merged, "members": [], "position": len(projected)}
                projected.append(merged)
                groups.append(group)
                active[parent] = group
        if group is not None:
            group["members"].append((index, record))
            membership[index] = group
            aliases[index] = group["position"]
        else:
            active.pop(parent, None)
            aliases[index] = len(projected)
            projected.append({**record, "parent": aliases.get(parent)})
    for group in groups:
        _summarize(group)
    return projected
