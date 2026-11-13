# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Durable per-execution OTLP files with fixed conversation ownership."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import logging
import os
import re
import threading
import time
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from .trajectory_io import (
    Directory,
    TrajectoryConflict,
    TrajectoryCorrupt,
    digest,
    json_chunks,
    prefix_hash,
    write_all,
)
from .trajectory_sources import (
    initial_sources,
    register_source,
    unverified_sources,
    verified_sources,
)

logger = logging.getLogger(__name__)


def timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Trajectory timestamps must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise TrajectoryCorrupt("Trajectory timestamp is missing a timezone")
    return result.astimezone(UTC)


def uuid_string(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Trajectory UUID must use canonical lowercase notation")
    return value


def component(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128 or value in {".", ".."}:
        raise ValueError("Invalid trajectory identity")
    if any(char in value for char in ("/", "\\", "\0")):
        raise ValueError("Trajectory identity must be a single path component")
    encoded = quote(value, safe="-_.@")
    if len(encoded.encode()) > 240 or encoded.startswith("."):
        raise ValueError("Invalid trajectory directory identity")
    return encoded


def business_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", value) or int(value) > 2147483647:
        raise ValueError("Trajectory business IDs must be canonical positive INT4 strings")
    return value


@dataclass(frozen=True)
class CaptureIdentity:
    """Trusted application identity; the authorization callback revalidates it."""

    tenant_id: str
    owner_user_id: str
    conversation_id: str
    root_agent_id: str | None

    def __post_init__(self):
        component(self.tenant_id)
        component(self.owner_user_id)
        business_id(self.conversation_id)
        if self.root_agent_id is not None:
            business_id(self.root_agent_id)


class TrajectoryFileStore:
    """Blocking storage boundary, called from a managed I/O worker."""

    def __init__(
        self, root, *, authorize, retention_days: int = 30, clock=None, source_query=None,
        storage_mode="single_node", initialization_guard=None, expire_callback=None,
        initialize_storage=True,
    ):
        self.root = Path(root)
        self.storage_mode = self._mode(storage_mode)
        self.authorize = authorize
        self.source_query = source_query
        self.initialization_guard = initialization_guard
        self.expire_callback = expire_callback
        self.on_publish = None
        self.retention_days = self._days(retention_days)
        self.clock = clock or (lambda: datetime.now(UTC))
        if not callable(authorize):
            raise TypeError("Trusted capture authorization is required")
        if initialize_storage:
            self.provision(self.root, storage_mode=self.storage_mode)

    def notify(self, identity):
        if self.on_publish is not None:
            try:
                self.on_publish(identity)
            except Exception:  # noqa: BLE001 - A failed wakeup is repaired by periodic reconciliation.
                logger.warning("trajectory.summary_notification_deferred", exc_info=False)

    @staticmethod
    def _days(days):
        if type(days) is not int or not 1 <= days <= 3650:
            raise ValueError("Trajectory retention days must be an integer between 1 and 3650")
        return days

    @classmethod
    def provision(cls, root, *, storage_mode="single_node"):
        """Initialize the persistent directory and enforce its configured storage mode."""
        storage_mode = cls._mode(storage_mode)
        with Directory.root(Path(root), create=True) as directory, directory.lock(".storage-root.lock"):
            try:
                marker = directory.read_json(".storage-root.json")
            except FileNotFoundError:
                directory.atomic_json(".storage-root.json", {
                    "schema_version": 1, "storage_mode": storage_mode,
                })
            else:
                if not cls._registered(marker, storage_mode):
                    raise TrajectoryConflict("Trajectory storage mode differs")

    @staticmethod
    def _mode(value):
        if value not in ("single_node", "shared_directory"):
            raise ValueError("Trajectory storage mode must be single_node or shared_directory")
        return value

    @staticmethod
    def _registered(marker, mode):
        return (isinstance(marker, dict) and marker.get("schema_version") == 1
                and marker.get("storage_mode", "single_node") == mode)

    @contextmanager
    def _root(self):
        with Directory.root(self.root) as directory:
            if not self._registered(directory.read_json(".storage-root.json"), self.storage_mode):
                raise TrajectoryConflict("Trajectory storage mode differs")
            yield directory

    def _locate(self, root, identity):
        matches = []
        checks = 0
        for tenant in os.listdir(root.fd):
            if tenant.startswith("."):
                continue
            with root.child(tenant) as td:
                try:
                    user = td.child(component(identity.owner_user_id))
                except FileNotFoundError:
                    continue
                with user:
                    for agent in os.listdir(user.fd):
                        checks += 1
                        if checks > 4096:
                            raise TrajectoryConflict("Trajectory ownership lookup budget exhausted")
                        with user.child(agent) as ad:
                            try:
                                conversation = ad.child(identity.conversation_id)
                            except FileNotFoundError:
                                continue
                            with conversation:
                                try:
                                    meta = conversation.read_json("meta.json")
                                except FileNotFoundError as error:
                                    names = os.listdir(conversation.fd)
                                    if any(name != ".lock" and not re.fullmatch(r"\.tmp-[0-9a-f-]{36}", name) for name in names):
                                        raise TrajectoryCorrupt(
                                            "Trajectory directory has files but no manifest"
                                        ) from error
                                    # An initial metadata commit may fail before an execution file exists.
                                    continue
                                self._validate_manifest(meta, identity, tenant, agent)
                                matches.append(
                                    (tenant, component(identity.owner_user_id), agent, identity.conversation_id)
                                )
        if len(matches) > 1:
            raise TrajectoryCorrupt("Conversation has multiple trajectory directories")
        return matches[0] if matches else None

    def _validate_manifest(self, meta, identity, tenant, agent):
        if not isinstance(meta, dict):
            raise TrajectoryCorrupt("Trajectory manifest must be an object")
        if (meta.get("tenant_id"), meta.get("owner_user_id"), meta.get("conversation_id")) != (
            identity.tenant_id,
            identity.owner_user_id,
            identity.conversation_id,
        ):
            raise TrajectoryConflict("Trajectory ownership differs from trusted capture identity")
        if (
            meta.get("schema_version") != 1
            or tenant != component(meta["tenant_id"])
            or agent != (meta.get("agent_id", meta.get("storage_agent_id")) or "_unknown")
            or meta.get("trace_id") != identity.conversation_id
            or not isinstance(meta.get("runs"), list)
        ):
            raise TrajectoryCorrupt("Trajectory manifest identity is invalid")
        for run in meta["runs"]:
            if not isinstance(run, dict):
                raise TrajectoryCorrupt("Trajectory execution metadata must be an object")
            try:
                uuid_string(run["trajectory_id"])
                uuid_string(run["turn_id"])
                if (
                    type(run["confirmed_bytes"]) is not int
                    or run["confirmed_bytes"] < 0
                    or not re.fullmatch(r"[0-9a-f]{64}", run["confirmed_sha256"])
                    or run["capture_state"] not in {"writing", "incomplete", "ready", "expired", "corrupt"}
                    or run["business_status"] not in {"running", "completed", "failed", "cancelled", "interrupted"}
                ):
                    raise TrajectoryCorrupt("Trajectory execution confirmation is invalid")
            except (KeyError, TypeError, ValueError) as error:
                raise TrajectoryCorrupt("Trajectory execution metadata is invalid") from error

    @contextmanager
    def _session(self, identity, *, create=False, blocking=True):
        self.authorize(identity)
        with ExitStack() as stack:
            root = stack.enter_context(self._root())
            path = self._locate(root, identity)
            if path is None:
                if not create:
                    raise FileNotFoundError("Conversation trajectory was not captured")
                # Production supplies a PG conversation row lock. The root lock is only
                # the standalone storage adapter's initialization guard.
                guard = (self.initialization_guard(identity) if self.initialization_guard
                         else root.lock(".storage-root.lock", blocking=blocking))
                with guard:
                    self.authorize(identity)
                    path = self._locate(root, identity)
                    if path is None:
                        path = (component(identity.tenant_id), component(identity.owner_user_id),
                                identity.root_agent_id or "_unknown", identity.conversation_id)
                        with ExitStack() as creation:
                            directory = root
                            for part in path:
                                directory = creation.enter_context(directory.child(part, create=True))
                            with directory.lock(".lock", blocking=blocking):
                                self._save_manifest(directory, self._initial_manifest(identity))
            directory = root
            for part in path:
                directory = stack.enter_context(directory.child(part))
            stack.enter_context(directory.lock(".lock", blocking=blocking))
            self.authorize(identity)
            meta = directory.read_json("meta.json")
            self._validate_manifest(meta, identity, path[0], path[2])
            yield directory

    def _initial_manifest(self, identity):
        now = timestamp(self.clock())
        return {
            "schema_version": 1, "tenant_id": identity.tenant_id,
            "owner_user_id": identity.owner_user_id, "agent_id": identity.root_agent_id,
            "conversation_id": identity.conversation_id, "trace_id": identity.conversation_id,
            "revision": 0, "next_turn_no": 1, "publication_no": 0, "cleanup_version": 0,
            "first_captured_at": now, "last_captured_at": now,
            "captured_from_start": False, "has_uncaptured_history": True,
            "had_capture_gap": False, "had_expired_history": False,
            "expired_execution_count": 0, "earliest_expired_at": None,
            "latest_expired_at": None, "had_manual_cleanup": False,
            **initial_sources(), "runs": [],
        }

    def _save_manifest(self, directory, meta):
        latest = max(meta["runs"], key=lambda run: run["turn_no"], default=None)
        if latest and latest["turn_no"] >= (meta.get("latest_execution") or {}).get("turn_no", 0):
            meta["latest_execution"] = {
                key: latest.get(key) for key in (
                    "trajectory_id", "turn_no", "started_at", "finished_at", "expires_at",
                    "root_agent_id", "root_agent_name", "root_agent_version_no", "root_agent_version_name",
                    "business_status", "capture_state", "publication_no", "cleanup_reason", "file_deleted_at",
                )
            }
        meta["revision"] += 1
        directory.atomic_json("meta.json", meta)

    def manifest(self, identity):
        with self._session(identity) as directory:
            return directory.read_json("meta.json")

    def identities(self, *, owner_user_id=None, conversation_ids=None, tenant_ids=None):
        """Enumerate fixed file identities for internal maintenance, never an HTTP listing."""
        with self._root() as root:
            tenants = os.listdir(root.fd) if tenant_ids is None else [component(t) for t in sorted(tenant_ids)]
            for tenant in tenants:
                if tenant.startswith("."):
                    continue
                try:
                    tenant_directory = root.child(tenant)
                except FileNotFoundError:
                    continue
                with tenant_directory as td:
                    users = [component(owner_user_id)] if owner_user_id is not None else os.listdir(td.fd)
                    for user in users:
                        try:
                            ud = td.child(user)
                        except FileNotFoundError:
                            continue
                        with ud:
                            for agent in os.listdir(ud.fd):
                                with ud.child(agent) as ad:
                                    conversations = conversation_ids if conversation_ids is not None else os.listdir(ad.fd)
                                    for conversation in conversations:
                                        try:
                                            with ad.child(conversation) as cd:
                                                meta = cd.read_json("meta.json")
                                                identity = CaptureIdentity(
                                                    meta["tenant_id"],
                                                    meta["owner_user_id"],
                                                    meta["conversation_id"],
                                                    meta.get("agent_id", meta.get("storage_agent_id")),
                                                )
                                                self._validate_manifest(meta, identity, tenant, agent)
                                                if (
                                                    component(identity.owner_user_id) != user
                                                    or identity.conversation_id != conversation
                                                ):
                                                    raise TrajectoryCorrupt("Trajectory directory identity differs")
                                                yield identity
                                        except FileNotFoundError:
                                            continue
                                        except (OSError, ValueError, KeyError, TrajectoryCorrupt, TrajectoryConflict):
                                            logger.warning("trajectory.maintenance_identity_invalid", exc_info=False)

    def start(self, identity, trajectory_id: str, turn_id: str, *, core_type: str, ingress_ref=None,
              started_at=None, source_message_id=None, turn_no=None):
        uuid_string(trajectory_id)
        uuid_string(turn_id)
        if turn_no is not None and (type(turn_no) is not int or not 1 <= turn_no <= 2147483647):
            raise ValueError("Trajectory turn number must be a positive INT4")
        if source_message_id is not None:
            business_id(source_message_id)
        if core_type not in {"smolagents", "jiuwen"}:
            raise ValueError("Unsupported trajectory Agent Core")
        with self._session(identity, create=True) as directory:
            now = timestamp(started_at or self.clock())
            meta = directory.read_json("meta.json")
            if turn_no is not None and any(r["turn_no"] == turn_no for r in meta["runs"]):
                raise TrajectoryConflict("Trajectory turn number is already registered")
            if any(
                r["trajectory_id"] == trajectory_id or (ingress_ref and r["ingress_ref"] == ingress_ref)
                for r in meta["runs"]
            ):
                raise TrajectoryConflict("Trajectory execution is already registered")
            fd = directory.open(f"{trajectory_id}.otlp.jsonl", os.O_RDWR | os.O_CREAT | os.O_EXCL)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.fsync(fd)
                os.fsync(directory.fd)
                meta["runs"].append(
                    {
                        "trajectory_id": trajectory_id,
                        "turn_id": turn_id,
                        "turn_no": turn_no if turn_no is not None else meta["next_turn_no"],
                        "root_agent_id": identity.root_agent_id,
                        "core_type": core_type,
                        "ingress_ref": ingress_ref,
                        "source_message_id": source_message_id,
                        "started_at": now,
                        "finished_at": None,
                        "expires_at": None,
                        "business_status": "running",
                        "capture_state": "writing",
                        "confirmed_bytes": 0,
                        "confirmed_sha256": hashlib.sha256().hexdigest(),
                        "last_durable_at": None,
                        "last_batch": None,
                        "file_bytes": None,
                        "file_sha256": None,
                        "last_export_seq": "0",
                        "publication_no": None,
                        "safe_error": None,
                        "cleanup_reason": None,
                        "cleanup_marked_at": None,
                        "file_deleted_at": None,
                    }
                )
                meta["next_turn_no"] = max(meta["next_turn_no"], (turn_no or meta["next_turn_no"]) + 1)
                meta["last_captured_at"] = now
                register_source(meta, source_message_id)
                if source_message_id is not None and self.source_query is not None:
                    try:
                        observed = self.source_query(identity, source_message_id)
                        meta.update(verified_sources(meta, observed, source_message_id))
                    except Exception as error:  # noqa: BLE001 - Keep source outages separate from business capture.
                        meta.update(unverified_sources(meta))
                        logger.warning("trajectory.source_verification_failed exception_type=%s", type(error).__name__)
                else:
                    meta.update(unverified_sources(meta))
                self._save_manifest(directory, meta)
                return RunWriter(self, identity, trajectory_id, fd)
            except BaseException:
                os.close(fd)
                raise

    def reconcile(self, identity):
        """Remove abandoned metadata temporaries and unlocked empty orphan files."""
        removed = 0
        with self._session(identity) as directory:
            meta = directory.read_json("meta.json")
            registered = {f"{run['trajectory_id']}.otlp.jsonl" for run in meta["runs"]}
            for name in os.listdir(directory.fd):
                temporary = name.startswith(".tmp-")
                orphan = name.endswith(".otlp.jsonl") and name not in registered
                if not (temporary or orphan):
                    continue
                try:
                    uuid_string(name[5:] if temporary else name.removesuffix(".otlp.jsonl"))
                except ValueError:
                    continue
                try:
                    with directory.lock(name, blocking=False, create=False) as fd:
                        if temporary or os.fstat(fd).st_size == 0:
                            os.unlink(name, dir_fd=directory.fd)
                            removed += 1
                except (OSError, TrajectoryConflict, TrajectoryCorrupt):
                    logger.warning("trajectory.orphan_cleanup_deferred", exc_info=False)
            if removed:
                os.fsync(directory.fd)
        return removed

    @staticmethod
    def _run(meta, trajectory_id):
        for run in meta["runs"]:
            if run["trajectory_id"] == trajectory_id:
                return run
        raise TrajectoryConflict("Trajectory execution is not registered")

    def recover(self, identity, trajectory_id: str):
        """Seal a dead writer's confirmed prefix; never resume the Agent itself."""
        uuid_string(trajectory_id)
        with self._session(identity) as directory:
            meta = directory.read_json("meta.json")
            run = self._run(meta, trajectory_id)
            if run["capture_state"] in {"expired", "corrupt"}:
                raise TrajectoryConflict("Trajectory execution is unavailable")
            try:
                fd = directory.open(f"{trajectory_id}.otlp.jsonl", os.O_RDWR)
            except FileNotFoundError as error:
                run["capture_state"] = "corrupt"
                run["safe_error"] = "confirmed_file_missing"
                meta["had_capture_gap"] = True
                self._save_manifest(directory, meta)
                raise TrajectoryCorrupt("Registered trajectory file is missing") from error
            with os.fdopen(fd, "rb", closefd=True):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise TrajectoryConflict("Trajectory execution still has a writer") from error
                try:
                    actual = prefix_hash(fd, run["confirmed_bytes"])
                    if actual.hexdigest() != run["confirmed_sha256"]:
                        raise TrajectoryCorrupt("Confirmed trajectory checksum differs")
                    if run["publication_no"] is not None and os.fstat(fd).st_size != run["confirmed_bytes"]:
                        raise TrajectoryCorrupt("Published trajectory file size differs")
                    os.ftruncate(fd, run["confirmed_bytes"])
                    os.fsync(fd)
                except TrajectoryCorrupt:
                    run["capture_state"] = "corrupt"
                    run["safe_error"] = "confirmed_prefix_corrupt"
                    meta["had_capture_gap"] = True
                    self._save_manifest(directory, meta)
                    raise
                if run["publication_no"] is None:
                    run["capture_state"] = "incomplete"
                    meta["had_capture_gap"] = True
                    run["safe_error"] = "writer_interrupted"
                    self._publish(meta, run, "interrupted", run["last_durable_at"] or run["started_at"])
                    self._save_manifest(directory, meta)

        self.notify(identity)

    def _publish(self, meta, run, status, finished_at):
        if run["cleanup_reason"] or run["capture_state"] in {"expired", "corrupt"}:
            raise TrajectoryConflict("Trajectory cannot be republished after cleanup or corruption")
        run.update(
            business_status=status,
            finished_at=finished_at,
            expires_at=timestamp(parse_time(finished_at) + timedelta(days=self.retention_days)),
            file_bytes=run["confirmed_bytes"],
            file_sha256=run["confirmed_sha256"],
        )
        if run["capture_state"] == "writing":
            run["capture_state"] = "ready"
        meta["publication_no"] += 1
        run["publication_no"] = meta["publication_no"]

    def cleanup(
        self,
        identity,
        *,
        before_days=None,
        now=None,
        cutoff_at=None,
        after_turn=0,
        scan_limit=1000,
        delete_limit=100,
        lock_held=False,
        deadline=None,
        force_reason=None,
    ):
        """Clean one authorized conversation; the scheduler supplies bounded batches."""
        days = self._days(before_days if before_days is not None else self.retention_days)
        now = now or self.clock()
        cutoff = cutoff_at or now - timedelta(days=days)
        scan_limit, delete_limit = min(1000, scan_limit), min(100, delete_limit)
        result = {
            "deleted_runs": 0,
            "deleted_bytes": 0,
            "skipped_active": 0,
            "pending_runs": 0,
            "failed_runs": 0,
            "scanned_runs": 0,
            "next_turn": None,
        }
        with (
            self._root() as root,
            nullcontext() if lock_held else root.lock(".cleanup.lock", blocking=False),
        ):
            with self._session(identity) as directory:
                meta = directory.read_json("meta.json")
                targets = []
                changed = False
                remaining = sorted(
                    (r for r in meta["runs"] if r["turn_no"] > after_turn),
                    key=lambda r: r["turn_no"],
                )
                last_turn = after_turn
                for run in remaining:
                    if result["scanned_runs"] >= scan_limit or (deadline and time.monotonic() >= deadline):
                        result["next_turn"] = last_turn
                        break
                    result["scanned_runs"] += 1
                    last_turn = run["turn_no"]
                    if (not run["finished_at"] or run["publication_no"] is None) and force_reason != "conversation_deleted":
                        result["skipped_active"] += 1
                        continue
                    expires = None
                    if run["finished_at"] and run["expires_at"]:
                        expires = min(
                            parse_time(run["expires_at"]),
                            parse_time(run["finished_at"]) + timedelta(days=self.retention_days),
                        )
                        if timestamp(expires) != run["expires_at"]:
                            run["expires_at"] = timestamp(expires)
                            changed = True
                    eligible = (
                        bool(force_reason)
                        or expires <= now
                        or (before_days is not None and parse_time(run["finished_at"]) <= cutoff)
                    )
                    if not run["cleanup_reason"] and eligible:
                        run.update(
                            capture_state="expired",
                            cleanup_reason=force_reason or ("manual" if before_days is not None else "retention"),
                            cleanup_marked_at=timestamp(now),
                        )
                        meta["cleanup_version"] += 1
                        meta["had_expired_history"] = True
                        meta["had_manual_cleanup"] |= before_days is not None
                        meta["expired_execution_count"] += 1
                        meta["earliest_expired_at"] = meta["earliest_expired_at"] or timestamp(now)
                        meta["latest_expired_at"] = timestamp(now)
                        changed = True
                    if run["cleanup_reason"] and not run["file_deleted_at"]:
                        targets.append((run["trajectory_id"], run["confirmed_bytes"]))
                if changed:
                    self._save_manifest(directory, meta)
                if self.expire_callback:
                    self.expire_callback(identity, [r["trajectory_id"] for r in meta["runs"] if r.get("cleanup_reason")])
            # Releasing the session lock before taking a run lock avoids lock inversion.
            for position, (trajectory_id, size) in enumerate(targets[:delete_limit]):
                if deadline and time.monotonic() >= deadline:
                    result["pending_runs"] += len(targets[:delete_limit]) - position
                    break
                try:
                    with self._session(identity) as directory:
                        fd = directory.open(f"{trajectory_id}.otlp.jsonl", os.O_RDWR)
                    try:
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            result["pending_runs"] += 1
                            continue
                        with self._session(identity) as directory:
                            meta = directory.read_json("meta.json")
                            run = self._run(meta, trajectory_id)
                            if not run["cleanup_reason"]:
                                raise TrajectoryConflict("Trajectory cleanup marker is missing")
                            os.unlink(f"{trajectory_id}.otlp.jsonl", dir_fd=directory.fd)
                            os.fsync(directory.fd)
                            run["file_deleted_at"] = timestamp(now)
                            self._save_manifest(directory, meta)
                            result["deleted_runs"] += 1
                            result["deleted_bytes"] += size
                    finally:
                        os.close(fd)
                except FileNotFoundError:
                    with self._session(identity) as directory:
                        meta = directory.read_json("meta.json")
                        self._run(meta, trajectory_id)["file_deleted_at"] = timestamp(now)
                        self._save_manifest(directory, meta)
                except OSError:
                    result["failed_runs"] += 1
            result["pending_runs"] += max(0, len(targets) - delete_limit)
            with self._session(identity) as directory:
                meta = directory.read_json("meta.json")
                retained = [
                    run
                    for run in meta["runs"]
                    if not run["file_deleted_at"] or parse_time(run["file_deleted_at"]) + timedelta(days=7) > now
                ]
                if len(retained) != len(meta["runs"]):
                    meta["cleanup_version"] += 1
                    meta["runs"] = retained
                    self._save_manifest(directory, meta)
        return result


class RunWriter:
    """One locked execution file; receipts mean both file and metadata were synced."""

    def __init__(self, store, identity, trajectory_id, fd):
        self.store = store
        self.identity = identity
        self.trajectory_id = trajectory_id
        self.fd = fd
        self._lock = threading.RLock()
        self._hash = hashlib.sha256()
        self._seen = {}
        self._uncertain_batch = None
        self._had_gap = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        with self._lock:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None

    @contextmanager
    def _state(self):
        if self.fd is None:
            raise TrajectoryConflict("Trajectory writer is closed")
        with self.store._session(self.identity) as directory:
            current = os.stat(f"{self.trajectory_id}.otlp.jsonl", dir_fd=directory.fd, follow_symlinks=False)
            opened = os.fstat(self.fd)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise TrajectoryCorrupt("Trajectory file identity changed")
            meta = directory.read_json("meta.json")
            run = self.store._run(meta, self.trajectory_id)
            if self._had_gap and run["capture_state"] in {"writing", "incomplete"}:
                run["capture_state"] = "incomplete"
                run["safe_error"] = "storage_commit_failed"
                meta["had_capture_gap"] = True
            yield directory, meta, run

    def _prepare(self, requests):
        seen = {}
        selected = []
        for request in requests:
            resources = []
            for resource in request.get("resourceSpans", []):
                scopes = []
                for scope in resource.get("scopeSpans", []):
                    spans = []
                    for span in scope.get("spans", []):
                        attrs = {a["key"]: next(iter(a["value"].values())) for a in span.get("attributes", [])}
                        expected = {
                            "tenant.id": self.identity.tenant_id,
                            "nexent.owner_user_id": self.identity.owner_user_id,
                            "conversation.id": self.identity.conversation_id,
                            "session.id": self.identity.conversation_id,
                            "nexent.trace_id": self.identity.conversation_id,
                            "nexent.trajectory_id": self.trajectory_id,
                        }
                        if any(attrs.get(key) != value for key, value in expected.items()):
                            raise TrajectoryConflict("OTLP Span has different capture ownership")
                        key = (span["traceId"], span["spanId"])
                        if (
                            not re.fullmatch(r"[0-9a-f]{32}", key[0])
                            or not re.fullmatch(r"[0-9a-f]{16}", key[1])
                            or int(key[0], 16) == 0
                            or int(key[1], 16) == 0
                        ):
                            raise ValueError("OTLP Span identity is invalid")
                        safe_span = {
                            **span,
                            "attributes": [a for a in span.get("attributes", []) if a["key"] != "nexent.export_seq"],
                        }
                        fingerprint = digest(safe_span)
                        previous = self._seen.get(key, seen.get(key))
                        if previous is not None:
                            if previous != fingerprint:
                                raise TrajectoryConflict("OTLP Span content changed under the same identity")
                            continue
                        seen[key] = fingerprint
                        spans.append(safe_span)
                    if spans:
                        scopes.append({**scope, "spans": spans})
                if scopes:
                    resources.append({**resource, "scopeSpans": scopes})
            if resources:
                selected.append({**request, "resourceSpans": resources})
        if len(self._seen) + len(seen) > 100_000:
            raise TrajectoryConflict("Trajectory deduplication budget exhausted")
        return selected, seen

    def append(self, requests, *, batch_id: str, expected_offset: int):
        uuid_string(batch_id)
        if type(expected_offset) is not int or expected_offset < 0:
            raise ValueError("Trajectory offset must be a non-negative integer")
        requests = list(requests)
        fingerprint = digest(requests)
        with self._lock, self._state() as (directory, meta, run):
            previous = run["last_batch"]
            if self._uncertain_batch:
                uncertain_id, uncertain_seen = self._uncertain_batch
                if previous and previous["batch_id"] == uncertain_id:
                    self._seen.update(uncertain_seen)
                self._uncertain_batch = None
            if previous and previous["batch_id"] == batch_id:
                if previous["sha256"] != fingerprint or previous["expected_offset"] != expected_offset:
                    raise TrajectoryConflict("Trajectory batch retry differs")
                # A prior rename may have succeeded before its directory fsync failed.
                self._hash = prefix_hash(self.fd, run["confirmed_bytes"])
                if self._hash.hexdigest() != run["confirmed_sha256"]:
                    raise TrajectoryCorrupt("Confirmed trajectory checksum differs")
                os.fsync(self.fd)
                os.fsync(directory.fd)
                _, seen = self._prepare(requests)
                self._seen.update(seen)
                return copy.deepcopy(previous["receipt"])
            if run["business_status"] != "running" or run["capture_state"] not in {"writing", "incomplete"}:
                raise TrajectoryConflict("Trajectory execution no longer accepts writes")
            if expected_offset != run["confirmed_bytes"]:
                raise TrajectoryConflict("Trajectory expected offset differs")
            if self._hash.hexdigest() != run["confirmed_sha256"]:
                self._hash = prefix_hash(self.fd, expected_offset)
                if self._hash.hexdigest() != run["confirmed_sha256"]:
                    raise TrajectoryCorrupt("Confirmed trajectory checksum differs")
            selected, seen = self._prepare(requests)
            original = self._hash.copy()
            seq = int(run["last_export_seq"])
            os.ftruncate(self.fd, expected_offset)
            os.lseek(self.fd, expected_offset, os.SEEK_SET)
            size = expected_offset
            try:
                for request in selected:
                    for resource in request["resourceSpans"]:
                        for scope in resource["scopeSpans"]:
                            for span in scope["spans"]:
                                seq += 1
                                span["attributes"].append(
                                    {"key": "nexent.export_seq", "value": {"intValue": str(seq)}}
                                )
                    for chunk in json_chunks(request):
                        write_all(self.fd, chunk)
                        self._hash.update(chunk)
                        size += len(chunk)
                    write_all(self.fd, b"\n")
                    self._hash.update(b"\n")
                    size += 1
                os.fsync(self.fd)
                receipt = {"batch_id": batch_id, "confirmed_bytes": size, "confirmed_sha256": self._hash.hexdigest()}
                run.update(
                    confirmed_bytes=size,
                    confirmed_sha256=self._hash.hexdigest(),
                    last_durable_at=timestamp(self.store.clock()),
                    last_export_seq=str(seq),
                    last_batch={
                        "batch_id": batch_id,
                        "expected_offset": expected_offset,
                        "bytes": size - expected_offset,
                        "sha256": fingerprint,
                        "receipt": receipt,
                    },
                )
                for request in selected:
                    for resource in request["resourceSpans"]:
                        for scope in resource["scopeSpans"]:
                            for span in scope["spans"]:
                                attrs = {item["key"]: item["value"] for item in span.get("attributes", [])}
                                if attrs.get("nexent.trajectory.root", {}).get("boolValue") is not True:
                                    continue
                                raw_version = attrs.get("agent.version_no", {}).get("intValue")
                                valid = (
                                    type(raw_version) is int
                                    or isinstance(raw_version, str)
                                    and re.fullmatch(r"0|[1-9][0-9]{0,18}", raw_version)
                                )
                                version = int(raw_version) if valid else None
                                if version is not None and not 0 <= version <= 2**63 - 1:
                                    version = None
                                name = attrs.get("agent.version_name", {}).get("stringValue")
                                run.update(
                                    root_agent_version_no=version,
                                    root_agent_version_name=(
                                        name if version is not None and isinstance(name, str) else None
                                    ),
                                    root_agent_name=attrs.get("agent.name", {}).get("stringValue") or span.get("name"),
                                )
                self.store._save_manifest(directory, meta)
            except BaseException:
                self._hash = original
                self._uncertain_batch = (batch_id, seen)
                self._had_gap = True
                try:
                    current = directory.read_json("meta.json")
                    current_run = self.store._run(current, self.trajectory_id)
                    current_run["capture_state"] = "incomplete"
                    current_run["safe_error"] = "storage_commit_failed"
                    current["had_capture_gap"] = True
                    self.store._save_manifest(directory, current)
                except (OSError, TrajectoryConflict, TrajectoryCorrupt):
                    # The original write failure remains the observable failure.
                    pass
                raise
            self._seen.update(seen)
            return copy.deepcopy(receipt)

    def finish(self, status: str, *, finished_at=None):
        if status not in {"completed", "failed", "cancelled", "interrupted"}:
            raise ValueError("Invalid trajectory terminal status")
        with self._lock, self._state() as (directory, meta, run):
            if run["publication_no"] is not None:
                if run["business_status"] != status or run["cleanup_reason"]:
                    raise TrajectoryConflict("Trajectory terminal state differs")
                return
            actual = prefix_hash(self.fd, run["confirmed_bytes"])
            if actual.hexdigest() != run["confirmed_sha256"]:
                run["capture_state"] = "corrupt"
                run["safe_error"] = "confirmed_prefix_corrupt"
                meta["had_capture_gap"] = True
                self.store._save_manifest(directory, meta)
                raise TrajectoryCorrupt("Confirmed trajectory checksum differs")
            os.ftruncate(self.fd, run["confirmed_bytes"])
            os.fsync(self.fd)
            self.store._publish(meta, run, status, timestamp(finished_at or self.store.clock()))
            self.store._save_manifest(directory, meta)

        self.store.notify(self.identity)

    def mark_incomplete(self, reason: str):
        if not re.fullmatch(r"[a-z_]{1,64}", reason):
            raise ValueError("Trajectory gap reason must be a safe diagnostic code")
        with self._lock, self._state() as (directory, meta, run):
            if run["capture_state"] in {"expired", "corrupt"}:
                return
            run["capture_state"] = "incomplete"
            run["safe_error"] = reason
            meta["had_capture_gap"] = True
            self.store._save_manifest(directory, meta)
