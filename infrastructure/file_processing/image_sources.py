# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Image source I/O; managed objects are read through exact ObjectStore bindings."""

import base64
import hashlib
from urllib.parse import urlsplit

import aiohttp
from contracts.agentos_knowledge import ObjectReference
from contracts.constants import environment
from nexent.multi_modal.utils import parse_s3_url
from nexent.storage.errors import InvalidInput
from nexent.storage.models import ObjectRef, Revision

from infrastructure.object_storage.composition import bind_source_objects


async def read_inline_or_web_image(url, *, context):
    context.remaining()
    if url.startswith("data:image"):
        return base64.b64decode(url.split(",", 1)[1])
    if urlsplit(url).scheme.lower() not in {"http", "https"} or url.lower().endswith(".svg"):
        raise InvalidInput()
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=context.remaining()), trust_env=True,
    ) as session, session.get(url, max_redirects=10) as response:
        if response.status != 200:
            raise InvalidInput()
        return await response.read()


def _logical_image(url):
    bucket, key = parse_s3_url(url)
    if bucket != environment.MINIO_DEFAULT_BUCKET:
        raise InvalidInput()
    return ObjectRef("files", key)


def _read_image(ref, *, user_id, tenant_id, context, role, max_bytes=None):
    context.remaining()
    objects = bind_source_objects(tenant_id, user_id, ref.key, environment.MINIO_DEFAULT_BUCKET,
                                 writable=False, role=role)
    try:
        metadata = objects.stat(ref, context=context)
        if (type(metadata.size) is not int or metadata.size < 0 or metadata.ref.version is None
            or max_bytes is not None and metadata.size > max_bytes
            or metadata.ref.space != ref.space or metadata.ref.key != ref.key
            or ref.version is not None and metadata.ref != ref):
            raise InvalidInput()
        with objects.open_read(metadata.ref, context=context) as stream:
            blocks, size = [], 0
            while True:
                context.remaining()
                block = stream.read(min(1024 * 1024, metadata.size - size + 1))
                if not block:
                    break
                if not isinstance(block, bytes):
                    raise InvalidInput()
                size += len(block)
                if size > metadata.size:
                    raise InvalidInput()
                blocks.append(block)
            if size != metadata.size:
                raise InvalidInput()
            context.remaining()
            return metadata, b"".join(blocks)
    finally:
        objects.close()


def read_object_image(url, *, user_id, tenant_id, context, role="management"):
    """The caller authorizes the key; this port grants no sibling reads or writes."""
    return _read_image(_logical_image(url), user_id=user_id, tenant_id=tenant_id, context=context, role=role)[1]


def pin_object_image(url, *, user_id, tenant_id, context, max_bytes=None):
    metadata, raw = _read_image(_logical_image(url), user_id=user_id, tenant_id=tenant_id,
                                context=context, role="management", max_bytes=max_bytes)
    digest = hashlib.sha256(raw).hexdigest()
    if metadata.sha256 not in {None, digest}:
        raise InvalidInput()
    return ObjectReference(space=metadata.ref.space, key=metadata.ref.key,
                            version=metadata.ref.version.value, sha256=digest)


def read_pinned_object_image(reference, *, user_id, tenant_id, context):
    if not isinstance(reference, ObjectReference) or reference.space != "files":
        raise InvalidInput()
    reference = ObjectReference.model_validate(reference.model_dump())
    ref = ObjectRef(reference.space, reference.key, Revision(reference.version))
    metadata, raw = _read_image(ref, user_id=user_id, tenant_id=tenant_id, context=context, role="runtime")
    if metadata.sha256 not in {None, reference.sha256} or hashlib.sha256(raw).hexdigest() != reference.sha256:
        raise InvalidInput()
    return raw
