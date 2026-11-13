# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reconcile durable manifests with the small PG execution projection."""

from infrastructure.observability.trajectory_io import TrajectoryCorrupt
from infrastructure.observability.trajectory_reader import JSONReader
from infrastructure.observability.trajectory_store import parse_time

from .archive import Archive
from .nodes import build_nodes
from .primitives import Budget, QueryError, finite_number


def model_names(nodes):
    values = sorted(
        {n["model"] for n in nodes if n["kind"] == "model" and n.get("model")}
    )
    if len(values) > 1000 or any(len(v) > 100 for v in values):
        raise ValueError("Trajectory model name projection exceeds its storage limit")
    return values


def manifest_runs(meta):
    """Retain the last expired fact after the manifest prunes its run tombstone."""
    runs = list(meta["runs"])
    latest = meta.get("latest_execution")
    if (
        latest
        and (latest.get("cleanup_reason") or latest["capture_state"] == "expired")
        and all(r["trajectory_id"] != latest["trajectory_id"] for r in runs)
    ):
        runs.append(latest)
    return runs


def execution_values(conversation_id, run, nodes=(), root=None):
    state = run["capture_state"]
    status = (
        "expired"
        if state == "expired" or run.get("cleanup_reason")
        else "corrupt"
        if state == "corrupt"
        else "unarchived"
        if run.get("publication_no") is None
        else "partial"
        if state != "ready"
        else "success"
        if run["business_status"] == "completed"
        else "error"
    )
    root_node = next((n for n in nodes if n["id"] == root), {})
    models = [n for n in nodes if n["kind"] == "model"]
    tokens = {}
    for key in ("input", "output", "total"):
        values = [
            finite_number((n.get("usage") or {}).get(key), integer=True) for n in models
        ]
        tokens[key + "_tokens"] = (
            sum(values) if values and all(v is not None for v in values) else None
        )
    version = root_node.get("agent_version_no", run.get("root_agent_version_no"))
    if type(version) is not int or not 0 <= version <= 2147483647:
        version = None
    return {
        "trajectory_id": run["trajectory_id"],
        "conversation_id": int(conversation_id),
        "turn_no": run["turn_no"],
        "agent_id": int(run["root_agent_id"]) if run.get("root_agent_id") else None,
        "agent_version_no": version,
        "models": model_names(nodes),
        "status": status,
        "started_at": parse_time(run["started_at"]) if run.get("started_at") else None,
        "finished_at": parse_time(run["finished_at"])
        if run.get("finished_at")
        else None,
        "duration_ms": root_node.get("duration_ms"),
        **tokens,
    }


class Projector:
    def __init__(self, store, repository):
        self.store, self.repository = store, repository
        self.archive = Archive(store)
        from .cache import ByteCache

        self._versions = ByteCache(16 * 1024 * 1024, ttl=3600)

    def sync(self, identity, check=lambda: None):
        meta = self.store.manifest(identity)
        runs = manifest_runs(meta)
        expired = [
            r["trajectory_id"]
            for r in runs
            if r.get("cleanup_reason") or r["capture_state"] == "expired"
        ]
        self.repository.expire(identity, expired)
        budget = Budget(seconds=30, max_bytes=256 * 1024 * 1024)
        samples = []
        for run in runs:
            check()
            key = (
                run["trajectory_id"],
                run.get("confirmed_sha256"),
                run["capture_state"],
                run.get("publication_no"),
                self.archive.available(run),
            )
            if self._versions.get(key) is not None:
                continue
            nodes, root = (), None
            corrupt, complete = False, True
            if self.archive.available(run) in {"available", "partial"}:
                row = {
                    "tenant_id": identity.tenant_id,
                    "user_id": identity.owner_user_id,
                    "conversation_id": identity.conversation_id,
                    "agent_id": identity.root_agent_id,
                }
                corrupt = False
                complete = False
                try:
                    with self.archive.opened(row, run["trajectory_id"], budget) as (
                        fd,
                        _,
                        confirmed,
                    ):
                        budget.check(size=confirmed["confirmed_bytes"])
                        nodes, root, coverage = build_nodes(
                            JSONReader(
                                fd, confirmed["confirmed_bytes"], check=budget.check
                            ).requests(),
                            conversation_id=identity.conversation_id,
                            complete=confirmed["capture_state"] == "ready",
                            check=budget.check,
                        )
                    complete = bool(coverage.get("complete"))
                except QueryError as error:
                    if error.code not in {"trajectory_corrupt", "content_expired"}:
                        raise
                    corrupt = error.code == "trajectory_corrupt"
                except (
                    TrajectoryCorrupt,
                    KeyError,
                    TypeError,
                    ValueError,
                    UnicodeError,
                    RecursionError,
                ):
                    corrupt = True
                samples.extend(
                    n["ttft_ms"]
                    for n in nodes
                    if n["kind"] == "model" and n.get("ttft_ms") is not None
                )
            # Recheck the current manifest under the same conversation lock used by
            # cleanup; a delayed parser must never republish a removed execution.
            with self.store._session(identity) as directory:
                current = next(
                    (
                        r
                        for r in manifest_runs(directory.read_json("meta.json"))
                        if r["trajectory_id"] == run["trajectory_id"]
                    ),
                    None,
                )
                if current is None:
                    self.repository.expire(identity, [run["trajectory_id"]])
                    continue
                if current.get("confirmed_sha256") != run.get("confirmed_sha256"):
                    continue
                values = execution_values(
                    identity.conversation_id, current, nodes, root
                )
                if self.archive.available(current) == "expired":
                    values["status"] = "expired"
                elif corrupt:
                    values["status"] = "corrupt"
                elif not complete and values["status"] in {"success", "error"}:
                    values["status"] = "partial"
                self.repository.sync(identity, values)
            self._versions.put(key, True, 512)
        return samples
