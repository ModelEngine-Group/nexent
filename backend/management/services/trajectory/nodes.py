# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Derive business nodes and complete subtree metrics from native OTLP spans."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from infrastructure.observability.trajectory_io import TrajectoryCorrupt
from infrastructure.observability.trajectory_reader import Text

from .primitives import finite_number

BODY_FIELDS = {
    "input": "input.value",
    "output": "output.value",
    "reasoning": "nexent.reasoning.value",
    "raw": "nexent.raw.value",
}


def any_value(value):
    if "arrayValue" in value:
        return [any_value(v) for v in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return attributes(value["kvlistValue"].get("values", []))
    return next(iter(value.values()), None)


def attributes(items):
    return {str(item["key"]): any_value(item["value"]) for item in items}


def native_id(span):
    return f"otel:{span['traceId']}:{span['spanId']}"


def _same_export(first, second):
    """Compare complete decoded strings even when only their previews are retained."""
    if isinstance(first, Text) and isinstance(second, Text):
        return (first.byte_count, first.char_count, first.digest) == (
            second.byte_count,
            second.char_count,
            second.digest,
        )
    if isinstance(first, dict) and isinstance(second, dict):
        return first.keys() == second.keys() and all(
            _same_export(value, second[key]) for key, value in first.items()
        )
    if isinstance(first, list) and isinstance(second, list):
        return len(first) == len(second) and all(
            _same_export(a, b) for a, b in zip(first, second)
        )
    return first == second


def times(span):
    start, end = (
        finite_number(span.get("startTimeUnixNano"), integer=True),
        finite_number(span.get("endTimeUnixNano"), integer=True),
    )

    def iso(value):
        try:
            return (
                datetime.fromtimestamp(value / 1e9, UTC)
                .isoformat()
                .replace("+00:00", "Z")
                if value
                else None
            )
        except (ValueError, OverflowError, OSError):
            return None

    duration = (
        (end - start) / 1e6
        if start is not None and end is not None and end >= start
        else None
    )
    return iso(start), iso(end), duration


def build_nodes(requests, *, conversation_id, complete=True, check=lambda **_: None):
    spans, fragments, aliases = {}, {}, {}
    capture_gap = False
    for request in requests:
        for resource in request.get("resourceSpans", []):
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    check(
                        nodes=1,
                        retained=len(json.dumps(span, ensure_ascii=False).encode()) * 4,
                    )
                    attrs = attributes(span.get("attributes", []))
                    dropped = any(
                        span.get(field, 0)
                        for field in (
                            "droppedAttributesCount",
                            "droppedEventsCount",
                            "droppedLinksCount",
                        )
                    ) or any(
                        item.get("droppedAttributesCount", 0)
                        for item in [*span.get("events", []), *span.get("links", [])]
                    )
                    if dropped or attrs.get("nexent.trajectory.gap"):
                        complete, capture_gap = False, True
                    if (
                        span.get("name") == "nexent.trajectory.fragment"
                        or attrs.get("nexent.span.role") == "fragment"
                    ):
                        owner = f"otel:{span['traceId']}:{attrs.get('nexent.owner_span_id', span.get('parentSpanId', ''))}"
                        fragments.setdefault(owner, []).append((span, attrs))
                    else:
                        key = native_id(span)
                        if key in spans:
                            # Immutable exports may be repeated; only identical records are valid.
                            if not _same_export(spans[key][0], span):
                                raise TrajectoryCorrupt("Conflicting duplicate span")
                            continue
                        spans[key] = (span, attrs)
    for key, values in fragments.items():
        if key not in spans:
            fragment, attrs = values[0]
            spans[key] = (
                {
                    **fragment,
                    "spanId": attrs.get(
                        "nexent.owner_span_id", fragment.get("parentSpanId")
                    ),
                    "parentSpanId": "",
                    "endTimeUnixNano": None,
                },
                attrs,
            )
            complete = False
    nodes = {}
    for key, (span, attrs) in spans.items():
        identity = str(attrs.get("nexent.record_id") or key)
        if identity in nodes:
            raise TrajectoryCorrupt("Business node identity is duplicated")
        aliases[key] = identity
        started, finished, duration = times(span)
        if finished is None or "nexent.availability.duration_ms" in attrs:
            duration = None
        elif "nexent.duration_ms" in attrs:
            duration = finite_number(attrs["nexent.duration_ms"])
        semantic = str(attrs.get("openinference.span.kind", "")).upper()
        kind = {"AGENT": "agent", "LLM": "model", "TOOL": "tool"}.get(semantic)
        if kind is None and semantic:
            kind = "context"
        if kind is None:
            kind = (
                "model"
                if attrs.get("llm.model_name")
                else (
                    "tool"
                    if attrs.get("tool.name")
                    else ("agent" if attrs.get("nexent.trajectory.root") else "context")
                )
            )
        bodies = {
            slot: attrs[field] for slot, field in BODY_FIELDS.items() if field in attrs
        }
        seen_events = set()
        for fragment, _ in sorted(
            fragments.get(key, []),
            key=lambda item: int(item[0].get("startTimeUnixNano", 0)),
        ):
            for event in fragment.get("events", []):
                event_attrs = attributes(event.get("attributes", []))
                event_id = event_attrs.get("nexent.event_id")
                if event_id and event_id in seen_events:
                    continue
                seen_events.add(event_id)
                if event_attrs.get("nexent.snapshot_mode") == "replace":
                    for slot, field in BODY_FIELDS.items():
                        if field not in attrs and field in event_attrs:
                            bodies[slot] = event_attrs[field]
        usage = {
            name: finite_number(attrs.get(field), integer=True)
            for name, field in (
                ("input", "llm.token_count.prompt"),
                ("output", "llm.token_count.completion"),
                ("total", "llm.token_count.total"),
            )
        }
        if (
            usage["total"] is None
            and usage["input"] is not None
            and usage["output"] is not None
        ):
            usage["total"] = usage["input"] + usage["output"]
        usage["complete"] = kind == "model" and all(
            usage[k] is not None for k in ("input", "output", "total")
        )
        ttft = finite_number(attrs.get("llm.ttft_ms"))
        if (
            ttft is None
            and finite_number(attrs.get("llm.time_to_first_token")) is not None
        ):
            ttft = finite_number(attrs["llm.time_to_first_token"]) * 1000
        if kind != "model" or duration is None or ttft is None or ttft > duration:
            ttft = None
        status = attrs.get("nexent.business_status")
        if not status:
            status = (
                "failed"
                if span.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR")
                else "completed"
            )
        if finished is None:
            status = "interrupted"
        native_parent = (
            f"otel:{span['traceId']}:{span['parentSpanId']}"
            if span.get("parentSpanId")
            else None
        )
        node = {
            "id": identity,
            "parent_id": attrs.get("nexent.parent_record_id"),
            "display_trace_id": identity,
            "kind": kind,
            "name": str(
                attrs.get(
                    {
                        "agent": "agent.name",
                        "model": "llm.model_name",
                        "tool": "tool.name",
                    }.get(kind, "")
                )
                or span.get("name", "")
            ),
            "status": str(status),
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration,
            "direct_child_count": 0,
            "model_call_count": None,
            "tool_call_count": None,
            "ttft_ms": ttft,
            "usage": usage if kind == "model" else None,
            "throughput": usage["output"] / (duration / 1000)
            if kind == "model"
            and usage["output"] is not None
            and duration
            and duration > 0
            else None,
            "model": str(attrs["llm.model_name"])
            if attrs.get("llm.model_name")
            else None,
            "attributes": {
                k: str(v) if isinstance(v, str) else v
                for k, v in attrs.items()
                if k
                in (
                    "nexent.invocation_id",
                    "nexent.parent_invocation_id",
                    "nexent.attempt_id",
                    "nexent.attempt_no",
                    "nexent.call_id",
                    "nexent.core_type",
                    "llm.ttft_basis",
                )
            },
            "source": {
                "trace_id": str(span["traceId"]),
                "span_id": str(span["spanId"]),
                "export_seq": str(attrs.get("nexent.export_seq", "")),
            },
            "_native_parent": None
            if attrs.get("nexent.trajectory.root")
            else native_parent,
            "_bodies": bodies,
            "_availability": {
                slot: str(attrs[f"nexent.availability.{slot}"])
                for slot in BODY_FIELDS
                if f"nexent.availability.{slot}" in attrs
            },
        }
        nodes[identity] = node
    # Technical spans retain source ancestry but do not become Agent/model/tool calls.
    for node in nodes.values():
        parent = node["parent_id"] or aliases.get(
            node["_native_parent"], node["_native_parent"]
        )
        visited = set()
        while parent in nodes and nodes[parent]["kind"] == "context":
            if parent in visited:
                raise TrajectoryCorrupt("Technical parent hierarchy contains a cycle")
            visited.add(parent)
            ancestor = nodes[parent]
            parent = ancestor["parent_id"] or aliases.get(
                ancestor["_native_parent"], ancestor["_native_parent"]
            )
        node["parent_id"] = parent
        node["_native_parent"] = None
    nodes = {key: value for key, value in nodes.items() if value["kind"] != "context"}
    children = {key: [] for key in nodes}
    roots, missing = [], False
    for node in nodes.values():
        native_parent = node.pop("_native_parent")
        node["parent_id"] = node["parent_id"] or aliases.get(
            native_parent, native_parent
        )
        parent = node["parent_id"]
        if parent in nodes:
            children[parent].append(node["id"])
        elif parent:
            node["attributes"]["missing_parent"] = True
            missing = True
        else:
            roots.append(node["id"])
    visiting, done = set(), set()

    def aggregate(identity, depth=0):
        if depth > 128 or identity in visiting:
            raise TrajectoryCorrupt(
                "Node hierarchy contains a cycle or exceeds depth budget"
            )
        if identity in done:
            return
        visiting.add(identity)
        node = nodes[identity]
        totals = [0, 0, 0]
        known = [True, True, True]
        models = tools = 0
        subtree_complete = complete and not missing
        for child_id in children[identity]:
            aggregate(child_id, depth + 1)
            child = nodes[child_id]
            models += child["_models"]
            tools += child["_tools"]
            for index in range(3):
                totals[index] += child["_totals"][index]
                known[index] &= child["_known"][index]
        if node["kind"] == "model":
            models += 1
            for index, field in enumerate(("input", "output", "total")):
                value = node["usage"][field]
                totals[index] += value or 0
                known[index] &= value is not None
        elif node["kind"] == "tool":
            tools += 1
        node.update(_models=models, _tools=tools, _totals=totals, _known=known)
        node["direct_child_count"] = len(children[identity])
        if node["kind"] == "agent":
            node["model_call_count"] = models if subtree_complete else None
            node["tool_call_count"] = tools if subtree_complete else None
            node["usage"] = {
                field: totals[i] if known[i] and subtree_complete else None
                for i, field in enumerate(("input", "output", "total"))
            }
            node["usage"].update(
                complete=subtree_complete and all(known),
                scope="execution_subtree",
                known={
                    field: totals[i]
                    for i, field in enumerate(("input", "output", "total"))
                },
            )
        visiting.remove(identity)
        done.add(identity)

    for identity in nodes:
        aggregate(identity)
    for node in nodes.values():
        for field in ("_models", "_tools", "_totals", "_known"):
            node.pop(field)
    root_id = roots[0] if len(roots) == 1 else None
    if root_id:
        nodes[root_id]["display_trace_id"] = conversation_id
    return (
        list(nodes.values()),
        root_id,
        {
            "complete": complete and not missing and len(roots) == 1,
            "missing_parent": missing,
            "capture_gap": capture_gap,
            "scope": "execution_subtree",
        },
    )
