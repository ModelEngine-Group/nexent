# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Private, file-backed trajectory imports independent of captured conversations."""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from infrastructure.observability.trajectory_io import (
    Directory,
    TrajectoryConflict,
    TrajectoryCorrupt,
    write_all,
)
from infrastructure.observability.trajectory_store import component

from .archive import storage_error
from .exchange import CHUNK, ExchangeLimits, import_archive
from .primitives import Budget, QueryError


def configured_store():
    from contracts.constants import environment as config

    from .exchange import configured_limits

    return SavedImports(
        config.TRAJECTORY_ROOT_DIR,
        limits=configured_limits(),
        candidates=config.TRAJECTORY_QUERY_MAX_CANDIDATES,
    )


class SavedImports:
    def __init__(self, root, *, limits=None, candidates=10000):
        self.root = Path(root)
        self.limits = limits or ExchangeLimits()
        self.candidates = candidates

    def _budget(self):
        return Budget(max_bytes=self.limits.unpacked_bytes, seconds=self.limits.seconds)

    @staticmethod
    def _id(value):
        try:
            if str(UUID(value)) != value:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as error:
            raise QueryError("import_not_found", 404) from error
        return value

    @contextmanager
    def _lock(self, owner):
        # Publish the stable lock inode exclusively before opening it for locking.
        try:
            fd = owner.open(".lock", os.O_RDWR | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            pass
        else:
            os.close(fd)
            os.fsync(owner.fd)
        with owner.lock(".lock", blocking=False, create=False):
            yield

    @contextmanager
    def _owner(self, actor, budget):
        if actor.role not in {"OPS", "SU"}:
            raise QueryError("administrator_required", 403)
        if not actor.user_id or not actor.tenant_id:
            raise QueryError("unauthenticated", 401)
        try:
            with (
                Directory.root(self.root, create=True) as root,
                root.child(".imports", create=True) as imports,
                imports.child(component(actor.tenant_id), create=True) as tenant,
                tenant.child(component(actor.user_id), create=True) as owner,
                self._lock(owner),
            ):
                budget.check()
                self._sweep(owner, budget)
                yield owner
        except QueryError:
            raise
        except FileNotFoundError as error:
            raise QueryError("import_not_found", 404) from error
        except TrajectoryConflict as error:
            raise QueryError("import_store_busy", 503) from error
        except (TrajectoryCorrupt, ValueError, KeyError, TypeError) as error:
            raise QueryError("invalid_saved_import", 422) from error
        except OSError as error:
            raise storage_error(error) from error

    @staticmethod
    def _remove(owner, name):
        with owner.child(name) as directory:
            for child in os.listdir(directory.fd):
                # Imports contain only flat management files, never extracted ZIP paths.
                os.unlink(child, dir_fd=directory.fd)
            os.fsync(directory.fd)
        os.rmdir(name, dir_fd=owner.fd)
        os.fsync(owner.fd)

    def _sweep(self, owner, budget):
        for name in os.listdir(owner.fd):
            budget.check()
            if name.startswith((".pending-", ".trash-")):
                try:
                    self._id(name.split("-", 1)[1])
                except QueryError:
                    continue
                self._remove(owner, name)

    @staticmethod
    def _record(directory, actor, import_id):
        record = directory.read_json("record.json")
        item = record["item"]
        if (
            record.get("schema_version") != 1
            or record.get("tenant_id") != actor.tenant_id
            or record.get("user_id") != actor.user_id
            or item["import_id"] != import_id
            or type(item["size_bytes"]) is not int
            or item["size_bytes"] < 0
            or not isinstance(item.get("row"), dict)
            or not isinstance(item.get("filename"), str)
            or not isinstance(item.get("imported_at"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
        ):
            raise TrajectoryCorrupt("Invalid saved import record")
        return record

    def create(self, actor, stream, filename):
        budget = self._budget()
        # Validate before creating a visible record. The upload file remains request-owned.
        trajectory = import_archive(stream, limits=self.limits)
        budget.check()
        import_id = str(uuid4())
        item = {
            "import_id": import_id,
            "filename": "".join(
                char
                for char in (filename or "trajectory.zip")
                .replace("\\", "/")
                .split("/")[-1]
                if char.isprintable()
            )[:255]
            or "trajectory.zip",
            "imported_at": datetime.now(UTC).isoformat(),
            "size_bytes": 0,
            "row": trajectory["row"],
        }
        pending = f".pending-{import_id}"
        with self._owner(actor, budget) as owner:
            try:
                with owner.child(pending, create=True) as directory:
                    fd = directory.open(
                        "archive.zip", os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    )
                    try:
                        stream.seek(0)
                        digest = hashlib.sha256()
                        while chunk := stream.read(CHUNK):
                            budget.check()
                            item["size_bytes"] += len(chunk)
                            if item["size_bytes"] > self.limits.compressed_bytes:
                                raise QueryError("archive_too_large", 413)
                            write_all(fd, chunk)
                            digest.update(chunk)
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    directory.atomic_json(
                        "record.json",
                        {
                            "schema_version": 1,
                            "tenant_id": actor.tenant_id,
                            "user_id": actor.user_id,
                            "sha256": digest.hexdigest(),
                            "item": item,
                        },
                    )
                budget.check()
                os.rename(pending, import_id, src_dir_fd=owner.fd, dst_dir_fd=owner.fd)
                os.fsync(owner.fd)
            finally:
                try:
                    self._remove(owner, pending)
                except FileNotFoundError:
                    pass
        return {"item": item, "trajectory": trajectory}

    def list(self, actor, page=1, page_size=20):
        if (
            type(page) is not int
            or type(page_size) is not int
            or page < 1
            or not 1 <= page_size <= 100
        ):
            raise QueryError("invalid_parameters", 422)
        budget, items = self._budget(), []
        with self._owner(actor, budget) as owner:
            for name in os.listdir(owner.fd):
                budget.check()
                if name.startswith("."):
                    continue
                self._id(name)
                with owner.child(name) as directory:
                    item = self._record(directory, actor, name)["item"]
                    budget.check(retained=len(json.dumps(item).encode()) * 4 + 256)
                    items.append(item)
                if len(items) > self.candidates:
                    raise QueryError("query_budget_exceeded", 503)
        items.sort(
            key=lambda item: (item["imported_at"], item["import_id"]), reverse=True
        )
        start = (page - 1) * page_size
        return {
            "items": items[start : start + page_size],
            "total": len(items),
            "page": page,
            "page_size": page_size,
        }

    def read(self, actor, import_id):
        self._id(import_id)
        budget = self._budget()
        with self._owner(actor, budget) as owner, owner.child(import_id) as directory:
            record = self._record(directory, actor, import_id)
            fd = directory.open("archive.zip", os.O_RDONLY)
        # The fixed descriptor keeps a concurrent delete from replacing the bytes being read.
        with os.fdopen(fd, "rb") as stream:
            digest, size = hashlib.sha256(), 0
            while chunk := stream.read(CHUNK):
                budget.check()
                size += len(chunk)
                if size > self.limits.compressed_bytes:
                    raise QueryError("archive_too_large", 413)
                digest.update(chunk)
            if (
                size != record["item"]["size_bytes"]
                or digest.hexdigest() != record["sha256"]
            ):
                raise QueryError("invalid_saved_import", 422)
            stream.seek(0)
            trajectory = import_archive(stream, limits=self.limits)
        budget.check()
        return {"item": record["item"], "trajectory": trajectory}

    def delete(self, actor, import_id):
        self._id(import_id)
        budget = self._budget()
        with self._owner(actor, budget) as owner:
            try:
                with owner.child(import_id) as directory:
                    self._record(directory, actor, import_id)
                trash = f".trash-{import_id}"
                os.rename(import_id, trash, src_dir_fd=owner.fd, dst_dir_fd=owner.fd)
                os.fsync(owner.fd)
            except FileNotFoundError:
                return {"deleted": True}
            self._remove(owner, trash)
        return {"deleted": True}
