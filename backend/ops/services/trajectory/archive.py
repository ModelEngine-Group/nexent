# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Open only authorized, published and checksum-confirmed OTLP prefixes."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import timedelta

from infrastructure.trace.trajectory_io import (
    TrajectoryConflict,
    TrajectoryCorrupt,
    prefix_hash,
)
from infrastructure.trace.trajectory_sources import (
    unverified_sources,
    verified_sources,
)
from infrastructure.trace.trajectory_store import (
    CaptureIdentity,
    parse_time,
    timestamp,
    uuid_string,
)

from .cache import ByteCache
from .primitives import QueryError

logger = logging.getLogger(__name__)


def identity(row):
    return CaptureIdentity(
        row["tenant_id"], row["user_id"], row["conversation_id"], row.get("agent_id")
    )


def storage_error(error):
    if isinstance(error, TrajectoryCorrupt):
        return QueryError("trajectory_corrupt", 503)
    if isinstance(error, PermissionError):
        return QueryError("trajectory_not_found", 404)
    if isinstance(error, TrajectoryConflict):
        message = str(error)
        if "ownership differs" in message.lower():
            return QueryError("trajectory_not_found", 404)
        return QueryError(
            "lookup_unavailable" if "budget" in message else "storage_busy",
            503,
            retry_after=2,
        )
    return QueryError("storage_unavailable", 503, retry_after=2)


class Archive:
    def __init__(self, store, *, source_query=None):
        self.store = store
        self.source_query = source_query
        self._checksums = ByteCache(1024 * 1024, ttl=60)

    def _verify(self, fd, run):
        """Reuse verification only while the pinned regular file is unchanged."""
        info = os.fstat(fd)
        size = run["confirmed_bytes"]
        if info.st_size != size:
            raise TrajectoryCorrupt("Published trajectory size differs")
        key = (
            info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, run["confirmed_sha256"],
        )
        if self._checksums.get(key) is None:
            if prefix_hash(fd, size).hexdigest() != run["confirmed_sha256"]:
                raise TrajectoryCorrupt("Published trajectory checksum differs")
            after = os.fstat(fd)
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            ):
                raise TrajectoryCorrupt("Published trajectory changed during verification")
            self._checksums.put(key, True, 512)

    def manifest(self, row, *, persist_retention=True):
        meta = self._manifest(row, persist_retention=persist_retention)
        if (
            meta is not None
            and meta.get("source_coverage_version") == 1
            and self.source_query is not None
        ):
            try:
                meta.update(
                    verified_sources(meta, self.source_query(identity(row), None))
                )
            except Exception as error:  # noqa: BLE001 - Unknown source coverage does not hide readable archives.
                meta.update(unverified_sources(meta))
                logger.warning(
                    "trajectory.source_verification_failed exception_type=%s",
                    type(error).__name__,
                )
        return meta

    def _manifest(self, row, *, persist_retention=True):
        try:
            with self.store._session(identity(row), read_only=True) as directory:
                meta = directory.read_json("meta.json")
                changed = False
                for run in meta["runs"]:
                    if run.get("expires_at") and run.get("finished_at"):
                        expiry = min(
                            parse_time(run["expires_at"]),
                            parse_time(run["finished_at"])
                            + timedelta(days=self.store.retention_days),
                        )
                        if expiry != parse_time(run["expires_at"]):
                            run["expires_at"] = timestamp(expiry)
                            changed = True
            if changed and persist_retention:
                # Persist a shorter retention period without making a historical GET
                # wait for an unrelated writer. Maintenance also tightens these bounds.
                try:
                    with self.store._session(identity(row), blocking=False) as directory:
                        current = directory.read_json("meta.json")
                        expiries = {run["trajectory_id"]: run.get("expires_at") for run in meta["runs"]}
                        for run in current["runs"]:
                            expiry = expiries.get(run["trajectory_id"])
                            if expiry and run.get("expires_at") and parse_time(expiry) < parse_time(run["expires_at"]):
                                run["expires_at"] = expiry
                        self.store._save_manifest(directory, current)
                except TrajectoryConflict as error:
                    if "already locked" not in str(error):
                        raise
            return meta
        except FileNotFoundError:
            # Verify the root separately; a lost mount is never reported as uncaptured.
            try:
                with self.store._root():
                    return None
            except (OSError, TrajectoryConflict, TrajectoryCorrupt) as error:
                raise storage_error(error) from error
        except (OSError, TrajectoryConflict, TrajectoryCorrupt) as error:
            raise storage_error(error) from error

    def available(self, run):
        if run.get("cleanup_reason") or run["capture_state"] == "expired":
            return "expired"
        if run.get("expires_at"):
            expiry = parse_time(run["expires_at"])
            if run.get("finished_at"):
                expiry = min(expiry, parse_time(run["finished_at"]) + timedelta(days=self.store.retention_days))
            if expiry <= self.store.clock():
                return "expired"
        if run["capture_state"] == "corrupt":
            return "corrupt"
        if run.get("publication_no") is None:
            return "unarchived"
        return "partial" if run["capture_state"] == "incomplete" else "available"

    def run(self, meta, run_id, expected=None):
        uuid_string(run_id)
        run = (
            next((r for r in meta["runs"] if r["trajectory_id"] == run_id), None)
            if meta
            else None
        )
        if not run:
            raise QueryError("trajectory_not_found", 404)
        state = self.available(run)
        if state == "expired":
            raise QueryError("content_expired", 410)
        if expected and (
            meta["cleanup_version"] != expected["cleanup"]
            or run.get("publication_no", 0) is None
            or run["publication_no"] > expected["publication"]
            or run["confirmed_sha256"] != expected["hash"]
        ):
            raise QueryError("snapshot_reset", 409)
        if state == "corrupt":
            raise QueryError("trajectory_corrupt", 503)
        if state == "unarchived":
            raise QueryError("trajectory_unarchived", 409)
        return run

    @contextmanager
    def opened(self, row, run_id, budget, expected=None):
        fd = None
        try:
            with self.store._session(identity(row), read_only=True) as directory:
                meta = directory.read_json("meta.json")
                run = self.run(meta, run_id, expected)
                fd = directory.open(f"{run_id}.otlp.jsonl", os.O_RDONLY)
            size = run["confirmed_bytes"]
            budget.check(size=size)
            self._verify(fd, run)
            yield fd, meta, run
            budget.check(size=size)
            self._verify(fd, run)
        except FileNotFoundError as error:
            raise QueryError("trajectory_corrupt", 503) from error
        except (OSError, TrajectoryConflict, TrajectoryCorrupt) as error:
            raise storage_error(error) from error
        finally:
            if fd is not None:
                os.close(fd)
