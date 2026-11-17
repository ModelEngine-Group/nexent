# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Descriptor-relative file operations and bounded JSON encoding for trajectories."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class TrajectoryConflict(RuntimeError):
    """A writer, identity, mount or idempotency precondition conflicts."""


class TrajectoryCorrupt(RuntimeError):
    """A previously confirmed file or manifest failed validation."""


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("Trajectory write made no progress")
        view = view[written:]


def json_chunks(value, depth: int = 0) -> Iterator[bytes]:
    """Escape string slices independently so a large body needs no encoded copy."""
    if depth > 64:
        raise ValueError("Trajectory JSON nesting exceeds 64 levels")
    if isinstance(value, str):
        yield b'"'
        for start in range(0, len(value), 16384):
            yield json.dumps(value[start : start + 16384], ensure_ascii=False)[1:-1].encode("utf-8")
        yield b'"'
    elif value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Trajectory JSON numbers must be finite")
        yield json.dumps(value, allow_nan=False).encode("ascii")
    elif isinstance(value, Mapping):
        yield b"{"
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Trajectory JSON keys must be strings")
        for index, key in enumerate(sorted(value)):
            if index:
                yield b","
            yield from json_chunks(key, depth + 1)
            yield b":"
            yield from json_chunks(value[key], depth + 1)
        yield b"}"
    elif isinstance(value, (list, tuple)):
        yield b"["
        for index, item in enumerate(value):
            if index:
                yield b","
            yield from json_chunks(item, depth + 1)
        yield b"]"
    else:
        raise ValueError("Unsupported trajectory JSON value")


def digest(value) -> str:
    result = hashlib.sha256()
    for chunk in json_chunks(value):
        result.update(chunk)
    return result.hexdigest()


def prefix_hash(fd: int, size: int):
    result = hashlib.sha256()
    position = 0
    while position < size:
        chunk = os.pread(fd, min(65536, size - position), position)
        if not chunk:
            raise TrajectoryCorrupt("Confirmed trajectory prefix is missing")
        position += len(chunk)
        result.update(chunk)
    return result


class Directory:
    """Pin each directory by descriptor and never follow a symlink."""

    def __init__(self, fd: int):
        self.fd = fd

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    @classmethod
    def root(cls, path: Path, *, create: bool = False):
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("Trajectory root must be an absolute normalized path")
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return cls(fd)
        except BaseException:
            os.close(fd)
            raise

    def child(self, name: str, *, create: bool = False):
        if not name or name in {".", ".."} or "/" in name or "\0" in name:
            raise ValueError("Invalid trajectory path component")
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=self.fd)
                os.fsync(self.fd)
            except FileExistsError:
                pass
        return Directory(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd))

    def open(self, name: str, flags: int) -> int:
        if not name or name in {".", ".."} or "/" in name or "\0" in name:
            raise ValueError("Invalid trajectory file name")
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(fd)
            raise TrajectoryCorrupt("Trajectory file is not a private regular file")
        return fd

    def read_json(self, name: str):
        fd = self.open(name, os.O_RDONLY)
        try:
            if os.fstat(fd).st_size > 16 * 1024 * 1024:
                raise TrajectoryCorrupt("Trajectory manifest exceeds the metadata budget")
            with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as handle:
                return json.load(handle)
        except (ValueError, UnicodeError) as error:
            raise TrajectoryCorrupt("Trajectory metadata is invalid") from error
        finally:
            os.close(fd)

    def atomic_json(self, name: str, value) -> None:
        temporary = f".tmp-{uuid4()}"
        fd = self.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            for chunk in json_chunks(value):
                write_all(fd, chunk)
            write_all(fd, b"\n")
            os.fsync(fd)
            os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass

    @contextmanager
    def lock(self, name: str, *, blocking: bool = True, create: bool = True):
        fd = self.open(name, os.O_RDWR | (os.O_CREAT if create else 0))
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as error:
                raise TrajectoryConflict("Trajectory file is already locked") from error
            yield fd
        finally:
            os.close(fd)
