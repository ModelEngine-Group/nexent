# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exclusive local mirrors of already confirmed object sources."""

import hashlib
import os
import re
from pathlib import Path
from tempfile import SpooledTemporaryFile

from nexent.storage.errors import Conflict, ScopeDenied


def local_source_location(root, file_id, filename):
    if not isinstance(file_id, str) or not re.fullmatch(r"[0-9a-f]{32}", file_id):
        raise ScopeDenied()
    filename = os.path.basename(filename.replace("\\", "/"))
    if filename in {"", ".", ".."}:
        raise ScopeDenied()
    root = Path(root).resolve()
    path = root / "knowledge" / file_id / filename
    if not path.resolve().is_relative_to(root) or len(str(path)) > 2048:
        raise ScopeDenied()
    return path


def describe_local_upload(stream, *, context):
    position = stream.tell()
    digest, size = hashlib.sha256(), 0
    try:
        stream.seek(0)
        while chunk := stream.read(1024 * 1024):
            context.remaining()
            size += len(chunk)
            digest.update(chunk)
        return size, digest.hexdigest()
    finally:
        stream.seek(position)


def open_staged_local_source(record, root, context):
    path = local_source_location(root, record["stage_id"], record["original_filename"])
    if str(path) != record["local_source_path"] or path.resolve() != path:
        raise ScopeDenied()
    size = record["file_size"]
    if type(size) is not int or size < 0:
        raise ScopeDenied()
    output = SpooledTemporaryFile(max_size=size + 1, mode="w+b")  # noqa: SIM115 - Caller owns the returned memory stream.
    try:
        actual, digest = 0, hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                context.remaining()
                actual += len(chunk)
                if actual > size:
                    raise Conflict()
                digest.update(chunk)
                output.write(chunk)
        context.remaining()
        if actual != size or digest.hexdigest() != record["source_sha256"]:
            raise Conflict()
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise


def discard_local_source(path, root):
    path, root = Path(path), Path(root).resolve()
    if (
        not path.resolve().is_relative_to(root)
        or path.parent.parent.name != "knowledge"
        or not re.fullmatch(r"[0-9a-f]{32}", path.parent.name)
    ):
        raise ScopeDenied()
    path.unlink(missing_ok=True)
    path.parent.rmdir()


def copy_local_source(
    stream, root, file_id, filename, *, expected_size, expected_sha256, context
):
    if (
        not isinstance(file_id, str)
        or not re.fullmatch(r"[0-9a-f]{32}", file_id)
        or type(expected_size) is not int
        or expected_size < 0
    ):
        raise ScopeDenied()
    path = local_source_location(root, file_id, filename)
    directory = path.parent
    context.remaining()
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise Conflict() from None
    try:
        position = stream.tell()
        stream.seek(0)
        digest, size = hashlib.sha256(), 0
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as output:
            while chunk := stream.read(1024 * 1024):
                context.remaining()
                size += len(chunk)
                if size > expected_size:
                    raise Conflict()
                digest.update(chunk)
                output.write(chunk)
        stream.seek(position)
        context.remaining()
        if size != expected_size or digest.hexdigest() != expected_sha256:
            raise Conflict()
        return path
    except BaseException:
        discard_local_source(path, root)
        raise
