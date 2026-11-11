# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorized historical snapshots and bounded content retrieval."""

from __future__ import annotations

import json

from infrastructure.observability.trajectory_io import TrajectoryCorrupt
from infrastructure.observability.trajectory_reader import (
    JSONReader,
    Text,
    TrajectoryReadBudgetExceeded,
    read_text,
)
from infrastructure.observability.trajectory_store import business_id

from .access import authorize
from .archive import Archive
from .cache import ByteCache
from .coverage import conversation_coverage
from .nodes import build_nodes
from .primitives import Budget, QueryError, fingerprint


class TrajectoryService:
    def __init__(
        self,
        store,
        catalog,
        references,
        *,
        max_bytes=256 * 1024 * 1024,
        seconds=30,
        max_candidates=10_000,
        source_query=None,
    ):
        self.archive, self.catalog, self.references = (
            Archive(store, source_query=source_query),
            catalog,
            references,
        )
        self.max_bytes, self.seconds, self.max_candidates = (
            max_bytes,
            seconds,
            max_candidates,
        )
        self.queries, self.summaries = (
            ByteCache(16 * 1024 * 1024),
            ByteCache(32 * 1024 * 1024),
        )

    def budget(self):
        return Budget(max_bytes=self.max_bytes, seconds=self.seconds)

    def resolve(self, actor, conversation_id, tenant_id=None, target_user_id=None):
        business_id(conversation_id)
        tenants = authorize(self.catalog, actor, tenant_id or actor.tenant_id)
        return self.catalog.resolve(
            tenants, conversation_id, target_user_id=target_user_id
        )

    def recheck(self, actor, row):
        fresh = self.resolve(
            actor, row["conversation_id"], row["tenant_id"], row["user_id"]
        )
        return fresh

    @staticmethod
    def coverage(meta):
        if meta is None:
            return {
                "complete": False,
                "reasons": ["not_captured"],
                "scope": "conversation",
            }
        reasons = [
            key
            for key in (
                "has_uncaptured_history",
                "had_capture_gap",
                "had_expired_history",
                "had_manual_cleanup",
            )
            if meta.get(key)
        ]
        if not meta.get("captured_from_start"):
            reasons.append("capture_start_unknown")
        if any(run.get("publication_no") is None for run in meta.get("runs", [])):
            reasons.append("unarchived")
        if meta.get("source_coverage_version") == 1 and not meta.get(
            "source_coverage_verified"
        ):
            reasons.append("source_verification_unavailable")
        return {"complete": not reasons, "reasons": reasons, "scope": "conversation"}

    def conversation_availability(self, meta, publication=None):
        """Describe the archives visible within the requested publication boundary."""
        if meta is None:
            return "not_captured"
        upper = meta["publication_no"] if publication is None else publication
        pending, expired = False, bool(meta.get("had_expired_history"))
        for run in meta.get("runs", []):
            number = run.get("publication_no")
            if number is None or number > upper:
                pending = True
            elif self.archive.available(run) == "expired":
                expired = True
            else:
                return "available"
        if pending:
            return "unarchived"
        return "expired" if expired else "not_captured"

    @staticmethod
    def binding(actor, row, meta, run=None):
        return {
            "actor": actor.binding,
            "tenant": row["tenant_id"],
            "owner": row["user_id"],
            "conversation": row["conversation_id"],
            "publication": meta["publication_no"] if meta else 0,
            "cleanup": meta["cleanup_version"] if meta else 0,
            **(
                {"trajectory": run["trajectory_id"], "hash": run["confirmed_sha256"]}
                if run
                else {}
            ),
        }

    def _validate(self, actor, row, token, kind, meta):
        data = self.references.resolve(
            token,
            kind,
            actor=actor.binding,
            tenant=row["tenant_id"],
            owner=row["user_id"],
            conversation=row["conversation_id"],
        )
        if data["cleanup"] != (meta["cleanup_version"] if meta else 0):
            raise QueryError("snapshot_reset", 409)
        return data

    def load(self, actor, row, run_id, budget, expected=None):
        with self.archive.opened(row, run_id, budget, expected) as (fd, meta, run):
            cache_key = fingerprint(self.binding(actor, row, meta, run))
            cached = self.summaries.get(cache_key)
            if cached is not None:
                return cached
            budget.check(size=run["confirmed_bytes"])
            reader = JSONReader(fd, run["confirmed_bytes"], check=budget.check)
            try:
                nodes, root, coverage = build_nodes(
                    reader.requests(),
                    conversation_id=row["conversation_id"],
                    complete=run["capture_state"] == "ready",
                    check=budget.check,
                )
            except TrajectoryReadBudgetExceeded as error:
                raise QueryError("query_budget_exceeded", 503, retry_after=2) from error
            except (
                KeyError,
                TypeError,
                ValueError,
                UnicodeError,
                RecursionError,
            ) as error:
                raise TrajectoryCorrupt("Invalid OTLP node structure") from error
            result = (nodes, root, coverage)
            # Four times serialized previews conservatively accounts for Python containers and strings.
            size = (
                len(
                    json.dumps(
                        result, ensure_ascii=False, separators=(",", ":")
                    ).encode()
                )
                * 4
            )
            self.summaries.put(cache_key, result, size)
            return result

    def _body(self, actor, row, meta, run, node, slot, value):
        if value is None:
            return {
                "availability": node.get("_availability", {}).get(slot, "not_returned"),
                "text": None,
                "complete": False,
                "content_id": None,
            }
        if not isinstance(value, Text):
            # Current OTLP content is a JSON string. Unsupported historical encodings stay explicit.
            return {
                "availability": "unsupported_encoding",
                "text": None,
                "complete": False,
                "content_id": None,
            }
        data = {
            **self.binding(actor, row, meta, run),
            "node": node["id"],
            "field": slot,
            "start": value.start,
            "end": value.end,
            "bytes": value.byte_count,
            "chars": value.char_count,
        }
        return {
            "availability": "available",
            "type": "text",
            "text": str(value),
            "preview": str(value),
            "byte_count": value.byte_count,
            "char_count": value.char_count,
            "complete": len(value.encode()) == value.byte_count,
            "content_id": self.references.issue("content", data),
        }

    def _dto(self, actor, row, meta, run, node):
        dto = {key: value for key, value in node.items() if not key.startswith("_")}
        dto.update(user=row["user_name"], user_id=row["user_id"])
        for slot in ("input", "output", "reasoning", "raw"):
            dto[slot] = self._body(
                actor, row, meta, run, node, slot, node["_bodies"].get(slot)
            )
        return dto

    def snapshot(
        self,
        actor,
        conversation_id,
        trajectory_id,
        *,
        tenant_id=None,
        target_user_id=None,
        cursor=None,
        limit=200,
        snapshot_id=None,
        node_id=None,
    ):
        if not 1 <= limit <= 500:
            raise QueryError("invalid_limit")
        row = self.resolve(actor, conversation_id, tenant_id, target_user_id)
        meta = self.archive.manifest(row)
        state = (
            self._validate(
                actor,
                row,
                cursor or snapshot_id,
                "nodes" if cursor else "snapshot",
                meta,
            )
            if cursor or snapshot_id
            else None
        )
        if state and state.get("trajectory") != trajectory_id:
            raise QueryError("invalid_reference")
        run = self.archive.run(meta, trajectory_id, state)
        state = state or self.binding(actor, row, meta, run)
        nodes, root, coverage = self.load(
            actor, row, trajectory_id, self.budget(), state
        )
        ordered = sorted(nodes, key=lambda n: (n["started_at"] or "", n["id"]))
        if node_id:
            index = next(
                (i for i, node in enumerate(ordered) if node["id"] == node_id), None
            )
            if index is None:
                raise QueryError("trajectory_not_found", 404)
        else:
            index = state.get("position", 0)
        by_id = {node["id"]: node for node in nodes}
        selected, context, size, position = [], {}, 0, index
        while position < len(ordered) and len(selected) < limit:
            node = ordered[position]
            ancestors, parent = {}, node["parent_id"]
            while parent in by_id and parent not in ancestors:
                ancestors[parent] = by_id[parent]
                parent = by_id[parent]["parent_id"]
            dto = self._dto(actor, row, meta, run, node)
            added = {
                key: self._dto(actor, row, meta, run, value)
                for key, value in ancestors.items()
                if key not in context
            }
            total_ids = (
                {n["id"] for n in selected} | set(context) | set(added) | {node["id"]}
            )
            required = len(
                json.dumps([dto, *added.values()], ensure_ascii=False).encode()
            )
            if len(total_ids) > 500 or size + required > 8 * 1024 * 1024 - 8192:
                break
            selected.append(dto)
            context.update(added)
            size += required
            position += 1
        if not selected and ordered:
            raise QueryError("node_page_budget_exceeded", 503, retry_after=2)
        selected_ids = {n["id"] for n in selected}
        current = self.archive.manifest(self.recheck(actor, row))
        self.archive.run(current, trajectory_id, state)
        return {
            "snapshot_id": self.references.issue("snapshot", state),
            "conversation_id": conversation_id,
            "trace_id": conversation_id,
            "trajectory_id": trajectory_id,
            "root_node_id": root,
            "nodes": selected,
            "context_nodes": [
                n for key, n in context.items() if key not in selected_ids
            ],
            "next_cursor": self.references.issue(
                "nodes", {**state, "position": position}
            )
            if position < len(ordered)
            else None,
            "coverage": coverage,
            "scope": {
                "kind": "execution",
                "complete": position >= len(ordered) and index == 0,
                "aggregates": "execution_subtree",
            },
        }

    def conversation(
        self,
        actor,
        conversation_id,
        *,
        tenant_id=None,
        target_user_id=None,
        cursor=None,
        limit=50,
        include=None,
        message_cursor=None,
        snapshot_id=None,
        query_id=None,
    ):
        if not 1 <= limit <= 200 or include not in (None, "messages"):
            raise QueryError("invalid_parameters")
        row = self.resolve(actor, conversation_id, tenant_id, target_user_id)
        meta = self.archive.manifest(row)
        reference = cursor or message_cursor or snapshot_id
        kind = "runs" if cursor else ("messages" if message_cursor else "conversation")
        state = (
            self._validate(actor, row, reference, kind, meta)
            if reference
            else {
                **self.binding(actor, row, meta),
                "message_upper": self.catalog.message_upper(conversation_id),
            }
        )
        if query_id and not reference:
            query = self.references.resolve(query_id, "query", actor=actor.binding)
            cached = self.queries.get(query["query"])
            if cached is None:
                raise QueryError("snapshot_reset", 409)
            member = next(
                (
                    item
                    for item in cached["members"]
                    if all(
                        item[key] == row[key]
                        for key in ("tenant_id", "user_id", "conversation_id")
                    )
                ),
                None,
            )
            if member is None or cached.get("view") != "conversation":
                raise QueryError("invalid_reference")
            if member["cleanup"] != (meta or {}).get("cleanup_version", 0):
                raise QueryError("snapshot_reset", 409)
            state.update(
                publication=member["publication"],
                run_ids=member["runs"],
                matching_runs=member["matching_runs"],
            )
        after = state.get("run_after", 0)
        runs = [
            run
            for run in (meta or {}).get("runs", [])
            if run["turn_no"] > after
            and ("run_ids" not in state or run["trajectory_id"] in state["run_ids"])
            and (run.get("publication_no") or state["publication"] + 1)
            <= state["publication"]
        ]
        runs.sort(key=lambda r: r["turn_no"])
        items = [
            {
                key: run.get(key)
                for key in (
                    "trajectory_id",
                    "turn_id",
                    "turn_no",
                    "root_agent_id",
                    "root_agent_version_no",
                    "root_agent_version_name",
                    "cleanup_reason",
                    "core_type",
                    "started_at",
                    "finished_at",
                    "business_status",
                    "capture_state",
                    "safe_error",
                    "source_message_id",
                )
            }
            | {
                "availability": self.archive.available(run),
                "round_no": run["turn_no"],
                "matches_filters": run["trajectory_id"]
                in state.get("matching_runs", [run["trajectory_id"]]),
            }
            for run in runs[:limit]
        ]
        availability = self.conversation_availability(meta, state["publication"])
        result = {
            "snapshot_id": self.references.issue("conversation", state),
            "conversation_id": conversation_id,
            "trace_id": conversation_id,
            "conversation_title": row["conversation_title"],
            "executions": items,
            "availability": availability,
            "active_execution_count": sum(
                1
                for r in (meta or {}).get("runs", [])
                if r.get("publication_no") is None
            ),
            "next_cursor": self.references.issue(
                "runs", {**state, "run_after": runs[limit - 1]["turn_no"]}
            )
            if len(runs) > limit
            else None,
        }
        messages = None
        if include == "messages":
            messages = self.catalog.messages(
                conversation_id,
                state["message_upper"],
                state.get("message_after", 0),
                limit,
            )
            result["messages"] = []
            for message in messages[:limit]:
                data = {
                    **state,
                    "field": "chat",
                    "message_id": message["message_id"],
                    "message_hash": message["hash"],
                }
                result["messages"].append(
                    {k: v for k, v in message.items() if k != "hash"}
                    | {
                        "content_id": self.references.issue("content", data),
                        "complete": len(message["preview"]) == message["char_count"],
                    }
                )
            result["message_cursor"] = (
                self.references.issue(
                    "messages",
                    {**state, "message_after": messages[limit - 1]["message_id"]},
                )
                if len(messages) > limit
                else None
            )
        self.recheck(actor, row)
        current = self.archive.manifest(row)
        if (meta is not None and current is None) or (current or {}).get(
            "cleanup_version", 0
        ) != state["cleanup"]:
            raise QueryError("snapshot_reset", 409)
        current_runs = {
            run["trajectory_id"]: run for run in (current or {}).get("runs", [])
        }
        for item in items:
            run = current_runs.get(item["trajectory_id"])
            if run is None:
                raise QueryError("snapshot_reset", 409)
            item["availability"] = self.archive.available(run)
        result["coverage"] = conversation_coverage(
            self,
            current,
            state,
            has_more_executions=len(runs) > limit,
            messages_requested=messages is not None,
            has_more_messages=len(messages) > limit if messages is not None else None,
        )
        result["availability"] = self.conversation_availability(
            current, state["publication"]
        )
        if (
            len(json.dumps(result, ensure_ascii=False).encode())
            > 2 * 1024 * 1024 - 8192
        ):
            raise QueryError("conversation_page_budget_exceeded", 503, retry_after=2)
        return result

    def content(
        self, actor, conversation_id, content_id, *, offset=0, limit=1024 * 1024
    ):
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 4 <= limit <= 1024 * 1024
        ):
            raise QueryError("invalid_content_range")
        state = self.references.resolve(content_id, "content", actor=actor.binding)
        if state.get("conversation") != conversation_id:
            raise QueryError("trajectory_not_found", 404)
        if state.get("field") not in {"input", "output", "reasoning", "raw", "chat"}:
            raise QueryError("invalid_content_source")
        row = self.resolve(actor, conversation_id, state["tenant"], state["owner"])
        meta = self.archive.manifest(row)
        if state["field"] == "chat":
            self._validate(actor, row, content_id, "content", meta)
            value = self.catalog.message_content(
                conversation_id, state["message_id"], offset, limit
            )
            if not value or value[1] != state["message_hash"]:
                raise QueryError("snapshot_reset", 409)
            raw = bytes(value[0] or b"")
            try:
                text = raw.decode("utf8")
            except UnicodeDecodeError as error:
                if (
                    error.reason != "unexpected end of data"
                    or error.start < len(raw) - 3
                ):
                    raise QueryError("invalid_content_range") from error
                text = raw[: error.start].decode("utf8")
            char_count, byte_count = value[2] or 0, value[3] or 0
            if offset > byte_count:
                raise QueryError("invalid_content_range")
            result = {
                "text": text,
                "offset": offset,
                "next_offset": offset + len(text.encode()),
                "offset_unit": "utf8_bytes",
                "complete": offset + len(text.encode()) >= byte_count,
                "char_count": char_count,
                "byte_count": byte_count,
            }
        else:
            budget = self.budget()
            with self.archive.opened(row, state["trajectory"], budget, state) as (
                fd,
                _,
                run,
            ):
                if (
                    not 0 <= state["start"] < state["end"] <= run["confirmed_bytes"]
                    or offset > state["bytes"]
                ):
                    raise QueryError("invalid_content_range")
                result = read_text(
                    fd,
                    state["start"],
                    state["end"],
                    offset=offset,
                    limit=limit,
                    check=budget.check,
                )
                result.update(
                    offset_unit="utf8_bytes",
                    byte_count=state["bytes"],
                    char_count=state["chars"],
                    complete=result["next_offset"] >= state["bytes"],
                )
        self.recheck(actor, row)
        current = self.archive.manifest(row)
        if state["field"] != "chat":
            self.archive.run(current, state["trajectory"], state)
        else:
            if (current or {}).get("cleanup_version", 0) != state["cleanup"]:
                raise QueryError("snapshot_reset", 409)
            version = self.catalog.message_content(
                conversation_id, state["message_id"], 0, 0
            )
            if not version or version[1] != state["message_hash"]:
                raise QueryError("snapshot_reset", 409)
        return result
