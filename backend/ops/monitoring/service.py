# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Write confirmed facts and atomically publish their daily projections."""

import json
import logging
from collections import deque
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4
from zoneinfo import ZoneInfo

from elasticsearch import NotFoundError

from ops.monitoring.contracts import MonitoringKind, stable_key
from ops.monitoring.search import DAILY, FACTS, bulk_write, delete_documents, existing_fact, filters, partition, snapshot
from ops.monitoring.store import ControlStore


logger = logging.getLogger(__name__)
CLEANUP_INTERVAL_SECONDS = 3600


def _apply_revision(previous, document):
    if previous is None:
        return True
    for field in ("tenant_id", "fact_kind", "fact_id", "started_at", "call_context_id"):
        if previous[field] != document[field]:
            raise ValueError("Monitoring identity changed")
    if previous["record_revision"] > document["record_revision"]:
        return False
    if previous["record_revision"] == document["record_revision"]:
        if {key: value for key, value in previous.items() if key != "write_version"} != document:
            raise ValueError("Conflicting monitoring revision")
        return False
    return True


def _merge_skill_usage(previous, document):
    """Keep the earliest trigger when duplicate Skill facts race or replay."""
    if previous is None or previous.get("fact_kind") != "skill" or document.get("fact_kind") != "skill":
        return document
    if previous.get("fact_id") != document.get("fact_id"):
        return document
    previous_triggered = previous.get("triggered_at")
    current_triggered = document.get("triggered_at")
    if not previous_triggered or not current_triggered or current_triggered >= previous_triggered:
        return None
    merged = dict(previous)
    merged["triggered_at"] = current_triggered
    merged["trigger_kind"] = document.get("trigger_kind")
    merged["record_revision"] = max(previous.get("record_revision", 1), document.get("record_revision", 1)) + 1
    return merged


class Monitoring:
    def __init__(self, store: ControlStore, es, zone: ZoneInfo, kinds: Mapping[str, MonitoringKind]):
        self.store = store
        self.es = es
        self.zone = zone
        self.kinds = kinds
        self._cleanup_at = 0.0
        self._cleanup_queue = deque()

    def _stage(self, batch, kind, tenant):
        writes = {}
        coverage = {}
        for payload in batch["replay_payload"]:
            fact = self.kinds[kind].fact_model.model_validate(payload)
            if fact.tenant_id != tenant or fact.fact_kind != kind:
                raise ValueError("Monitoring batch scope differs from its facts")
            index = partition(FACTS, fact.partition_anchor())
            doc_id = stable_key(tenant, kind, fact.fact_id)
            document = fact.document(self.zone)
            pending = writes.get((index, doc_id))
            previous = pending["document"] if pending else existing_fact(self.es, index, doc_id)
            if kind == "skill" and previous is not None:
                merged = _merge_skill_usage(previous, document)
                if merged is None:
                    continue
                document = merged
            if not _apply_revision(previous, document):
                continue
            document["write_version"] = batch["write_version"]
            writes[index, doc_id] = {"index": index, "id": doc_id, "document": document}
            anchor = fact.partition_anchor().isoformat()
            days = {document["statistic_date"]}
            if previous is not None:
                days.add(previous["statistic_date"])
            for day in days:
                coverage[day] = min(coverage.get(day, anchor), anchor)
        return {"writes": list(writes.values()), "coverage": coverage}

    def apply_batch(self, tenant, kind) -> bool:
        with self.store.lock("source", tenant, kind) as conn:
            with conn.begin():
                batch = self.store.next_batch(conn, tenant, kind)
            if batch is None:
                return False
            try:
                if batch["batch_state"] == "queued":
                    staged = self._stage(batch, kind, tenant)
                    with conn.begin():
                        self.store.stage(conn, batch["batch_id"], json.dumps(staged), list(staged["coverage"]))
                        batch = self.store.next_batch(conn, tenant, kind)
                staged = batch["replay_payload"]
                bulk_write(self.es, staged["writes"], external=True)
                with conn.begin():
                    self.store.confirm(conn, batch, tenant, kind, staged["coverage"])
            except Exception:
                with conn.begin():
                    self.store.batch_failed(conn, batch["batch_id"], "WRITE_FAILED")
                raise
        return True

    def publish(self, tenant, kind) -> None:
        aggregate = self.kinds[kind].aggregate
        if aggregate is None:
            return
        with self.store.lock("publish", tenant, kind) as publish_conn, ExitStack() as stack:
            with self.store.lock("source", tenant, kind) as source_conn, source_conn.begin():
                batch = self.store.next_batch(source_conn, tenant, kind)
                if batch is not None and batch["batch_state"] == "pending":
                    return
                days = self.store.dirty_days(source_conn, tenant, kind)
                if not days:
                    return
                point = stack.enter_context(snapshot(self.es, f"{FACTS}-*"))
                timepoint = datetime.now(timezone.utc)
            query = filters(tenant_id=tenant, fact_kind=kind, usage_source="formal",
                            statistic_date=[day.isoformat() for day, _ in days])
            publish_id = uuid4()
            writes = []
            target_dates = {day for day, _ in days}
            for key, daily in aggregate(point.documents(query)):
                day = datetime.fromisoformat(daily["statistic_date"]).date()
                if day not in target_dates:
                    raise ValueError("Monitoring reducer returned a date outside its publication")
                writes.append({"index": partition(DAILY, day), "id": stable_key(publish_id.hex, key),
                               "document": {**daily, "tenant_id": tenant, "fact_kind": kind,
                                            "publish_id": str(publish_id)}})
                if len(writes) == 500:
                    bulk_write(self.es, writes, external=False)
                    writes.clear()
            bulk_write(self.es, writes, external=False)
            with publish_conn.begin():
                self.store.publish(publish_conn, tenant, kind, days, publish_id, timepoint)

    @contextmanager
    def publication_snapshot(self, tenant, kind, start, end):
        with ExitStack() as stack:
            # Hold the publication rows until Elasticsearch pins their documents.
            with self.store.read_states(tenant, kind, start, end, lock=True) as states:
                point = None
                if any(row["publish_id"] and row["published_source_revision"] for row in states):
                    point = stack.enter_context(snapshot(self.es, f"{DAILY}-*"))
            yield states, point

    def cleanup(self, tenant, kind) -> None:
        with ExitStack() as stack:
            with self.store.lock("publish", tenant, kind) as conn:
                with conn.begin():
                    days = self.store.published_days(conn, tenant, kind)
                if not days:
                    return
                # No newer publication can enter this snapshot while the publisher is locked.
                try:
                    point = stack.enter_context(snapshot(self.es, f"{DAILY}-*"))
                except NotFoundError:
                    return
            for offset in range(0, len(days), 250):
                obsolete_days = []
                for day, current_id in days[offset:offset + 250]:
                    target = filters(statistic_date=day.isoformat())
                    target["bool"]["must_not"] = [{"term": {"publish_id": str(current_id)}}]
                    obsolete_days.append(target)
                query = filters(tenant_id=tenant, fact_kind=kind)
                query["bool"]["filter"].append({"exists": {"field": "publish_id"}})
                query["bool"].update(should=obsolete_days, minimum_should_match=1)
                delete_documents(self.es, point.hits(query, source=False))

    def _next_cleanup_scope(self):
        now = monotonic()
        if not self._cleanup_queue and now >= self._cleanup_at:
            self._cleanup_queue.extend(self.store.published_scopes())
            self._cleanup_at = now + CLEANUP_INTERVAL_SECONDS
        return [self._cleanup_queue.popleft()] if self._cleanup_queue else []

    def tick(self):
        today = datetime.now(self.zone).date()
        if getattr(self, "_coverage_day", None) != today:
            self.store.ensure_today(today)
            self._coverage_day = today
        for action, scopes in ((self.apply_batch, self.store.batch_scopes), (self.publish, self.store.dirty_scopes),
                               (self.cleanup, self._next_cleanup_scope)):
            for tenant, kind in scopes():
                if kind not in self.kinds:
                    continue
                try:
                    action(tenant, kind)
                except Exception as error:
                    logger.warning("Monitoring operation failed action=%s kind=%s error=%s",
                                   action.__name__, kind, type(error).__name__)
