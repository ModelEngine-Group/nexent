# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded, revision-pinned object reads shared by StorageInterface consumers."""

import hashlib

from .errors import InvalidInput
from .models import ObjectRef


def read_verified_object(objects, ref, *, sha256, limit, context):
    if (
        not isinstance(ref, ObjectRef)
        or ref.version is None
        or type(limit) is not int
        or limit <= 0
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(char not in "0123456789abcdef" for char in sha256)
    ):
        raise InvalidInput()
    context.remaining()
    metadata = objects.stat(ref, context=context)
    if (
        metadata.ref != ref
        or type(metadata.size) is not int
        or not 0 <= metadata.size <= limit
        or metadata.sha256 not in {None, sha256}
    ):
        raise InvalidInput()
    parts, size = [], 0
    with objects.open_read(ref, context=context) as stream:
        while True:
            context.remaining()
            part = stream.read(min(1024 * 1024, limit - size + 1))
            if not part:
                break
            if not isinstance(part, bytes):
                raise InvalidInput()
            size += len(part)
            if size > limit:
                raise InvalidInput()
            parts.append(part)
    context.remaining()
    content = b"".join(parts)
    if size != metadata.size or hashlib.sha256(content).hexdigest() != sha256:
        raise InvalidInput()
    return content
