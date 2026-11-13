# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Managed local span processing; storage failures never rerun business calls."""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nexent.monitor.duration import duration_attributes
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor

from .trajectory_audit import cleanup_audit
from .trajectory_identity import invocation_attributes
from .trajectory_io import digest, json_chunks
from .trajectory_otlp import span_request
from .trajectory_store import CaptureIdentity, business_id, component, timestamp

logger = logging.getLogger(__name__)


def _observed_time(nanoseconds):
    seconds, nanos = divmod(int(nanoseconds), 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanos // 1000)


def _has_dropped_data(value):
    if isinstance(value, dict):
        return any(
            bool(item) if key.startswith("dropped") and key.endswith("Count") else _has_dropped_data(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_dropped_data(item) for item in value)
    return False


def _business_status(attributes, failed):
    """Keep the worker outcome independent of telemetry serialization or I/O."""
    outcome = attributes.get("nexent.business_status")
    if outcome in {"completed", "failed", "cancelled", "interrupted"}:
        return outcome
    if attributes.get("nexent.cancelled"):
        return "cancelled"
    return "failed" if failed else "completed"


class LocalTrajectoryProcessor(SpanProcessor):
    """Use one ThreadManager service and byte-bounded, independent local queues."""

    def __init__(
        self,
        store,
        metadata_provider,
        *,
        flush_interval_ms=200,
        flush_bytes=262144,
        queue_max_bytes=268435456,
        run_queue_max_bytes=16777216,
        maintenance_store=None,
        cleanup_enabled=False,
        cleanup_interval_seconds=3600,
        cleanup_interval_provider=None,
    ):
        if min(flush_interval_ms, flush_bytes, queue_max_bytes, run_queue_max_bytes) <= 0:
            raise ValueError("Trajectory processor budgets must be positive")
        if run_queue_max_bytes > queue_max_bytes:
            raise ValueError("Trajectory per-run queue exceeds the process budget")
        if cleanup_interval_seconds < 60:
            raise ValueError("Trajectory cleanup interval must be at least 60 seconds")
        self.store = store
        self.metadata_provider = metadata_provider
        self.flush_interval = flush_interval_ms / 1000
        self.flush_bytes = flush_bytes
        self.queue_max_bytes = queue_max_bytes
        self.run_queue_max_bytes = run_queue_max_bytes
        self._queue = queue.Queue(maxsize=10000)
        self._deletions = queue.Queue(maxsize=1000)
        self._lock = threading.RLock()
        self._active = {}
        self._started = {}
        self._bytes = 0
        self._run_bytes = {}
        self._gaps = set()
        self._stop = threading.Event()
        self._execution = None
        self._accepting = False
        self._writers = {}
        self._offsets = {}
        self._terminal = {}
        self._last_snapshot = {}
        self._pending = {}
        self._pending_bytes = {}
        self._maintenance_store = maintenance_store
        self._cleanup_enabled = cleanup_enabled
        self.deleted_conversation_check = None
        self._cleanup_interval = cleanup_interval_seconds
        self._cleanup_interval_provider = cleanup_interval_provider
        self._next_schedule_refresh = 0
        self._cleanup_intervals = {}
        self._tenant_last_maintenance = {}
        self._maintenance_due_tenants = set()
        self._maintenance_full_scan = False
        self._next_full_maintenance = 0
        self._maintenance_iterator = None
        self._maintenance_pending = None
        self._next_maintenance = 0

    def start(self, manager, service_spec):
        """Application lifespan supplies the process-local manager and task spec."""
        if self._execution is not None:
            raise RuntimeError("Trajectory processor is already started")
        self._execution = manager.register_service(service_spec, self._work)
        self._accepting = True
        try:
            manager.start_service(self._execution.execution_id)
        except BaseException:
            self._accepting = False
            raise

    @staticmethod
    def wrap_sampler(delegate):
        from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult

        class LocalRecordingSampler(Sampler):
            def should_sample(self, *args, **kwargs):
                result = delegate.should_sample(*args, **kwargs)
                if result.decision == Decision.DROP:
                    return SamplingResult(Decision.RECORD_ONLY, result.attributes, result.trace_state)
                return result

            def get_description(self):
                return f"NexentLocalRecording({delegate.get_description()})"

        return LocalRecordingSampler()

    def request_stop(self):
        self._accepting = False
        self._stop.set()

    def request_conversation_cleanup(self, conversation_ids, owner_user_id):
        """Queue confirmed deletions independently of retention cleanup enablement."""
        component(owner_user_id)
        ids = {business_id(str(value)) for value in conversation_ids}
        accepted = True
        with self._lock:
            if not self._accepting:
                return False
            for conversation_id in ids:
                try:
                    self._deletions.put_nowait((owner_user_id, conversation_id, 0, 0))
                except queue.Full:
                    accepted = False
        return accepted

    def _delete_conversation_files(self):
        """One bounded batch per worker tick; PG and file locks remain authoritative."""
        store = self._maintenance_store
        if store is None:
            return
        try:
            owner, conversation, after_turn, ready_at = self._deletions.get_nowait()
        except queue.Empty:
            return
        retry = False
        try:
            if time.monotonic() < ready_at:
                retry = True
                return
            ready_at = 0
            deadline = time.monotonic() + 2
            for identity in store.identities(owner_user_id=owner, conversation_ids=[conversation]):
                if not self.deleted_conversation_check:
                    raise RuntimeError("Conversation deletion verification is unavailable")
                if not self.deleted_conversation_check(identity):
                    continue
                for run_id, writer in list(self._writers.items()):
                    if writer.identity.owner_user_id == owner and writer.identity.conversation_id == conversation:
                        self._release_denied_writer(run_id)
                result = {}
                with cleanup_audit(
                    source="conversation_deleted", tenant_id=identity.tenant_id,
                    conversation_id=conversation, actor_id=owner, before_days=None,
                    cutoff_at=None, counts=result,
                ):
                    result.update(store.cleanup(
                        identity, force_reason="conversation_deleted", after_turn=after_turn,
                        deadline=deadline,
                    ))
                retry = bool(result["pending_runs"] or result["failed_runs"] or result["next_turn"] is not None)
                after_turn = 0 if result["pending_runs"] or result["failed_runs"] else result["next_turn"] or 0
        except Exception:  # noqa: BLE001 - Retry filesystem and PG failures without disrupting span processing.
            retry = True
            logger.warning("trajectory.conversation_cleanup_deferred", exc_info=False)
        finally:
            self._deletions.task_done()
            if retry:
                try:
                    self._deletions.put_nowait((owner, conversation, after_turn, ready_at or time.monotonic() + 1))
                except queue.Full:
                    logger.warning("trajectory.conversation_cleanup_queue_full", exc_info=False)

    def _enqueue(self, run_id, kind, data, size=0):
        with self._lock:
            if (
                not self._accepting
                or self._bytes + size > self.queue_max_bytes
                or self._run_bytes.get(run_id, 0) + size > self.run_queue_max_bytes
            ):
                if run_id:
                    self._gaps.add(run_id)
                return False
            try:
                self._queue.put_nowait((run_id, kind, data, size))
            except queue.Full:
                self._gaps.add(run_id)
                return False
            self._bytes += size
            self._run_bytes[run_id] = self._run_bytes.get(run_id, 0) + size
            return True

    def on_start(self, span, parent_context=None):
        if not self._accepting:
            return
        try:
            started = time.perf_counter()
            parent = trace.get_current_span(parent_context)
            inherited = getattr(parent, "attributes", None) or {}
            run_id = inherited.get("nexent.trajectory_id")
            root = not run_id and span.name == "agent.run"
            if root:
                metadata = self.metadata_provider()
                if not metadata or metadata.conversation_id is None or not metadata.tenant_id or not metadata.user_id:
                    return
                identity = CaptureIdentity(
                    str(metadata.tenant_id),
                    str(metadata.user_id),
                    str(metadata.conversation_id),
                    str(metadata.agent_id) if metadata.agent_id is not None else None,
                )
                run_id = (metadata.extra_metadata or {}).get("trajectory_id") or str(uuid4())
                turn_id = str(uuid4())
                values = {
                    "tenant.id": identity.tenant_id,
                    "nexent.owner_user_id": identity.owner_user_id,
                    "conversation.id": identity.conversation_id,
                    "session.id": identity.conversation_id,
                    "nexent.trace_id": identity.conversation_id,
                    "nexent.trajectory_id": run_id,
                    "nexent.turn_id": turn_id,
                    "nexent.root_agent_id": identity.root_agent_id or "_unknown",
                    "nexent.trajectory.root": True,
                }
                core = (metadata.extra_metadata or {}).get("core_type", "smolagents")
                source = (metadata.extra_metadata or {}).get("trajectory_source_message_id")
                try:
                    source = business_id(source) if source is not None else None
                except ValueError:
                    source = None
                if source is not None:
                    values["nexent.source_message_id"] = source
                else:
                    values["nexent.availability.source_message_id"] = "not_captured"
                if not self._enqueue(run_id, "start", (identity, turn_id, core, _observed_time(span.start_time), source,
                                                                      (metadata.extra_metadata or {}).get("trajectory_turn_no"))):
                    return
            elif run_id:
                values = {
                    key: value
                    for key, value in inherited.items()
                    if key
                    in {
                        "tenant.id",
                        "nexent.owner_user_id",
                        "conversation.id",
                        "session.id",
                        "nexent.trace_id",
                        "nexent.trajectory_id",
                        "nexent.turn_id",
                        "nexent.root_agent_id",
                    }
                }
                if inherited.get("nexent.record_id"):
                    values["nexent.parent_record_id"] = inherited["nexent.record_id"]
            else:
                return
            values["nexent.record_id"] = str(uuid4())
            values.update(invocation_attributes(span.attributes or {}, inherited, values["nexent.record_id"], root=root))
            span.set_attributes(values)
            with self._lock:
                if len(self._active) >= 10000:
                    self._gaps.add(run_id)
                    return
                self._active[span.context.span_id] = span
                self._started[span.context.span_id] = started
        except Exception:  # noqa: BLE001 - Isolate telemetry failures from Agent execution and shutdown.
            logger.warning("trajectory.capture_start_failed", exc_info=False)

    def on_end(self, span):
        values = span.attributes or {}
        run_id = values.get("nexent.trajectory_id")
        if not run_id:
            return
        try:
            observed_duration = {}
            if not any(key in values for key in (
                "nexent.duration_ms", "nexent.local.nexent.duration_ms", "nexent.availability.duration_ms",
                "nexent.local.nexent.availability.duration_ms",
            )):
                with self._lock:
                    started = self._started.get(span.context.span_id)
                observed_duration = duration_attributes(started, time.perf_counter())
            request = span_request(span, local_attributes=observed_duration)
            size = sum(len(chunk) for chunk in json_chunks(request)) + 1
            with self._lock:
                self._enqueue(run_id, "span", request, size)
                self._active.pop(span.context.span_id, None)
                self._started.pop(span.context.span_id, None)
                if values.get("nexent.trajectory.root"):
                    status = _business_status(values, span.status.status_code.value == 2)
                    self._terminal[run_id] = (status, _observed_time(span.end_time))
        except Exception:  # noqa: BLE001 - Isolate telemetry failures from Agent execution and shutdown.
            with self._lock:
                self._gaps.add(run_id)
                self._active.pop(span.context.span_id, None)
                self._started.pop(span.context.span_id, None)
                if values.get("nexent.trajectory.root"):
                    self._terminal[run_id] = (
                        _business_status(values, span.status.status_code.value == 2),
                        _observed_time(span.end_time),
                    )
            logger.warning("trajectory.capture_end_failed", exc_info=False)

    def force_flush(self, timeout_millis=30000):
        if not self._execution or not self._accepting:
            return False
        event = threading.Event()
        return self._enqueue("", "barrier", event) and event.wait(timeout_millis / 1000)

    def shutdown(self):
        self.request_stop()
        if self._execution and self._execution.future:
            self._execution.future.result(timeout=30)

    def _release_denied_writer(self, run_id):
        """Stop capture on revocation; maintenance may seal only durable bytes."""
        writer = self._writers.pop(run_id, None)
        if writer is None:
            return
        writer.close()
        self._gaps.add(run_id)
        try:
            (self._maintenance_store or self.store).recover(writer.identity, run_id)
        except (OSError, RuntimeError, ValueError):
            logger.warning("trajectory.revoked_archive_deferred", exc_info=False)
        logger.warning("trajectory.capture_authorization_revoked", exc_info=False)

    def _append(self, run_id, requests):
        writer = self._writers.get(run_id)
        if writer is None:
            return
        if run_id in self._gaps:
            writer.mark_incomplete("capture_gap")
        if any(
            a["key"] == "nexent.trajectory.gap" and a["value"].get("boolValue")
            for request in requests
            for resource in request["resourceSpans"]
            for scope in resource["scopeSpans"]
            for body in scope["spans"]
            for a in body["attributes"]
        ):
            writer.mark_incomplete("serialization_failed")
        batch_id = str(uuid4())
        run = self.store._run(self.store.manifest(writer.identity), run_id)
        self._offsets[run_id] = run["confirmed_bytes"]
        if any(_has_dropped_data(request) for request in requests):
            writer.mark_incomplete("otel_dropped_data")
        for attempt in range(2):
            try:
                receipt = writer.append(requests, batch_id=batch_id, expected_offset=self._offsets[run_id])
                self._offsets[run_id] = receipt["confirmed_bytes"]
                return
            except OSError:
                if attempt:
                    raise

    def _flush_pending(self):
        for run_id in list(self._pending):
            requests = self._pending.pop(run_id)
            size = self._pending_bytes.pop(run_id)
            try:
                self._append(run_id, requests)
            except PermissionError:
                self._release_denied_writer(run_id)
            except Exception:  # noqa: BLE001 - Isolate telemetry failures from Agent execution and shutdown.
                self._gaps.add(run_id)
                logger.warning("trajectory.storage_batch_failed", exc_info=False)
            finally:
                with self._lock:
                    self._bytes -= size
                    remaining = self._run_bytes.get(run_id, 0) - size
                    if remaining:
                        self._run_bytes[run_id] = remaining
                    else:
                        self._run_bytes.pop(run_id, None)

    def _snapshot_active(self):
        with self._lock:
            active = list(self._active.values())
        for span in active:
            values = span.attributes or {}
            run_id = values["nexent.trajectory_id"]
            if run_id not in self._writers:
                continue
            request = span_request(span)
            body = request["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            # Generated bodies are persisted only by the ended span, never by active snapshots.
            body["attributes"] = [
                item for item in body["attributes"]
                if item["key"] not in {"output.value", "nexent.reasoning.value", "nexent.raw.value"}
            ]
            body["events"] = []
            if sum(len(chunk) for chunk in json_chunks(request)) > self.run_queue_max_bytes:
                self._gaps.add(run_id)
                self._writers[run_id].mark_incomplete("capture_gap")
                continue
            body = request["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            body["endTimeUnixNano"] = body["startTimeUnixNano"]
            key = (run_id, span.context.span_id)
            fingerprint = digest(request)
            if self._last_snapshot.get(key) == fingerprint:
                continue
            now = time.time_ns()
            body["name"] = "nexent.trajectory.fragment"
            body["spanId"] = uuid4().hex[:16]
            body["startTimeUnixNano"] = body["endTimeUnixNano"] = str(now)
            content = [a for a in body["attributes"] if a["key"] == "input.value"]
            body["attributes"] = [
                a
                for a in body["attributes"]
                if a["key"] not in {
                    "nexent.trajectory.root", "input.value", "output.value", "nexent.reasoning.value", "nexent.raw.value"
                }
            ]
            body["attributes"].append(
                {"key": "nexent.owner_span_id", "value": {"stringValue": f"{span.context.span_id:016x}"}}
            )
            body["events"] = [
                {
                    "name": "nexent.trajectory.snapshot",
                    "timeUnixNano": str(now),
                    "attributes": [
                        {"key": "nexent.event_id", "value": {"stringValue": str(uuid4())}},
                        {"key": "nexent.owner_span_id", "value": {"stringValue": f"{span.context.span_id:016x}"}},
                        {"key": "nexent.snapshot_mode", "value": {"stringValue": "replace"}},
                    ]
                    + content,
                }
            ]
            try:
                self._append(run_id, [request])
            except PermissionError:
                self._release_denied_writer(run_id)
                continue
            self._last_snapshot[key] = fingerprint

    def _publish_completed(self):
        with self._lock:
            active_runs = {(span.attributes or {}).get("nexent.trajectory_id") for span in self._active.values()}
        for run_id in list(self._terminal):
            if run_id in active_runs or self._run_bytes.get(run_id, 0):
                continue
            writer = self._writers.get(run_id)
            if writer:
                try:
                    if run_id in self._gaps:
                        writer.mark_incomplete("capture_gap")
                    status, finished_at = self._terminal[run_id]
                    writer.finish(status, finished_at=finished_at)
                    writer.close()
                    self._writers.pop(run_id, None)
                except PermissionError:
                    self._release_denied_writer(run_id)
            self._terminal.pop(run_id, None)
            self._offsets.pop(run_id, None)
            self._gaps.discard(run_id)
            self._last_snapshot = {key: value for key, value in self._last_snapshot.items() if key[0] != run_id}

    def _refresh_cleanup_interval(self):
        now = time.monotonic()
        if self._cleanup_interval_provider is None or now < self._next_schedule_refresh:
            return
        self._next_schedule_refresh = now + 30
        try:
            intervals = self._cleanup_interval_provider()
            if not isinstance(intervals, dict) or len(intervals) > 1000 or any(
                not isinstance(tenant, str) or not tenant
                or type(interval) is not int or not 60 <= interval <= 31536000
                for tenant, interval in intervals.items()
            ):
                raise ValueError("Invalid cleanup interval")
        except Exception:  # noqa: BLE001 - Configuration failure must not stop file maintenance.
            logger.warning("trajectory.cleanup_schedule_refresh_failed", exc_info=False)
            return
        self._cleanup_intervals = intervals
        if self._maintenance_iterator is None:
            self._schedule_next_maintenance()

    def _schedule_next_maintenance(self):
        deadlines = [self._next_full_maintenance]
        if self._cleanup_enabled:
            deadlines.extend(
                self._tenant_last_maintenance.get(tenant, 0)
                + self._cleanup_intervals.get(tenant, self._cleanup_interval)
                if tenant in self._tenant_last_maintenance else 0
                for tenant in self._cleanup_intervals.keys() | self._tenant_last_maintenance.keys()
            )
        self._next_maintenance = min(deadlines)

    def _maintain(self):
        store = self._maintenance_store
        if store is None:
            return
        self._refresh_cleanup_interval()
        if self._maintenance_iterator is None:
            now = time.monotonic()
            if now < self._next_maintenance:
                return
            self._maintenance_full_scan = now >= self._next_full_maintenance
            self._maintenance_due_tenants = {
                tenant for tenant in self._cleanup_intervals.keys() | self._tenant_last_maintenance.keys()
                if tenant not in self._tenant_last_maintenance or now >= self._tenant_last_maintenance[tenant]
                + self._cleanup_intervals.get(tenant, self._cleanup_interval)
            }
            self._maintenance_iterator = (
                store.identities() if self._maintenance_full_scan
                else store.identities(tenant_ids=self._maintenance_due_tenants)
            )
        started = time.monotonic()
        for _ in range(20):
            if not self._queue.empty() or time.monotonic() - started >= 0.05:
                return
            if self._maintenance_pending:
                identity, after_turn = self._maintenance_pending
            else:
                try:
                    identity = next(self._maintenance_iterator)
                except StopIteration:
                    self._maintenance_iterator = None
                    finished = time.monotonic()
                    for tenant in self._maintenance_due_tenants:
                        self._tenant_last_maintenance[tenant] = finished
                    if self._maintenance_full_scan:
                        self._next_full_maintenance = finished + self._cleanup_interval
                    self._schedule_next_maintenance()
                    return
                after_turn = 0
            if identity.tenant_id not in self._tenant_last_maintenance:
                self._maintenance_due_tenants.add(identity.tenant_id)
            retention_due = self._cleanup_enabled and identity.tenant_id in self._maintenance_due_tenants
            inspected = 0
            last_turn = after_turn
            has_more = False
            for run in store.manifest(identity)["runs"]:
                if run["turn_no"] <= after_turn:
                    continue
                if inspected >= 1000:
                    has_more = True
                    break
                inspected += 1
                last_turn = run["turn_no"]
                if run["capture_state"] == "writing" and run["trajectory_id"] not in self._writers:
                    try:
                        store.recover(identity, run["trajectory_id"])
                    except Exception:  # noqa: BLE001 - Another process can own the actual execution file lock.
                        logger.debug("trajectory.maintenance_recovery_deferred", exc_info=False)
            store.reconcile(identity)
            if retention_due or self.deleted_conversation_check:
                now = store.clock()
                cutoff = now - timedelta(days=store.retention_days)
                result = {}
                with cleanup_audit(
                    source="scheduled", tenant_id=identity.tenant_id, conversation_id=identity.conversation_id,
                    before_days=store.retention_days, cutoff_at=timestamp(cutoff), counts=result, emit_empty=False,
                ):
                    deleted = self.deleted_conversation_check(identity) if self.deleted_conversation_check else False
                    if retention_due or deleted:
                        result.update(store.cleanup(
                            identity,
                            after_turn=after_turn,
                            force_reason="conversation_deleted" if deleted else None,
                            now=now,
                            cutoff_at=cutoff,
                            deadline=time.monotonic() + 2,
                        ))
                if result:
                    has_more = result["next_turn"] is not None
                    last_turn = result["next_turn"] if has_more else last_turn
            self._maintenance_pending = (identity, last_turn) if has_more else None

    def _work(self, cancel_event):
        next_snapshot = time.monotonic()
        try:
            while not (self._stop.is_set() or cancel_event.is_set()) or not self._queue.empty():
                try:
                    run_id, kind, data, size = self._queue.get(timeout=min(self.flush_interval, 0.2))
                except queue.Empty:
                    kind = None
                if kind:
                    try:
                        if kind == "start":
                            identity, turn_id, core, started_at, source, turn_no = data
                            self._writers[run_id] = self.store.start(
                                identity, run_id, turn_id, core_type=core, started_at=started_at,
                                source_message_id=source, turn_no=turn_no,
                            )
                            self._offsets[run_id] = 0
                        elif kind == "span":
                            self._pending.setdefault(run_id, []).append(data)
                            self._pending_bytes[run_id] = self._pending_bytes.get(run_id, 0) + size
                            body = data["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
                            attrs = {a["key"]: next(iter(a["value"].values())) for a in body["attributes"]}
                            if attrs.get("nexent.trajectory.root"):
                                status = _business_status(attrs, body["status"]["code"] == 2)
                                self._terminal[run_id] = (status, _observed_time(body["endTimeUnixNano"]))
                        elif kind == "barrier":
                            self._flush_pending()
                            self._snapshot_active()
                            self._publish_completed()
                            data.set()
                    except Exception:  # noqa: BLE001 - Isolate telemetry failures from Agent execution and shutdown.
                        self._gaps.add(run_id)
                        logger.warning("trajectory.storage_failed", exc_info=False)
                    finally:
                        if kind != "span":
                            with self._lock:
                                self._bytes -= size
                                remaining = self._run_bytes.get(run_id, 0) - size
                                if remaining:
                                    self._run_bytes[run_id] = remaining
                                else:
                                    self._run_bytes.pop(run_id, None)
                        self._queue.task_done()
                try:
                    if time.monotonic() >= next_snapshot or sum(self._pending_bytes.values()) >= self.flush_bytes:
                        self._flush_pending()
                        self._snapshot_active()
                        next_snapshot = time.monotonic() + self.flush_interval
                    self._publish_completed()
                    self._delete_conversation_files()
                    self._maintain()
                except Exception:  # noqa: BLE001 - Isolate telemetry failures from Agent execution and shutdown.
                    logger.warning("trajectory.storage_flush_failed", exc_info=False)
        finally:
            try:
                self._flush_pending()
                self._publish_completed()
            except Exception:  # noqa: BLE001 - Isolate telemetry failures from Agent execution and shutdown.
                logger.warning("trajectory.final_archive_failed", exc_info=False)
            for writer in self._writers.values():
                writer.close()
                try:
                    (self._maintenance_store or self.store).recover(writer.identity, writer.trajectory_id)
                except Exception:  # noqa: BLE001 - Isolate telemetry failures from Agent execution and shutdown.
                    logger.warning("trajectory.interrupted_archive_failed", exc_info=False)
            self._writers.clear()
            self._active.clear()
            self._started.clear()
            self._last_snapshot.clear()
            if self._maintenance_iterator is not None:
                self._maintenance_iterator.close()
                self._maintenance_iterator = None
