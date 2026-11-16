# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Image source I/O; managed objects are read through exact ObjectStore bindings."""

import base64
from urllib.parse import urlsplit

import aiohttp
from contracts.constants import environment
from nexent.multi_modal.utils import parse_s3_url
from nexent.storage.errors import InvalidInput
from nexent.storage.models import ObjectRef

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


def read_object_image(url, *, user_id, tenant_id, context):
    """The caller authorizes the key; this port grants no sibling reads or writes."""
    bucket, key = parse_s3_url(url)
    if bucket != environment.MINIO_DEFAULT_BUCKET:
        raise InvalidInput()
    objects = bind_source_objects(tenant_id, user_id, key, bucket, writable=False)
    try:
        metadata = objects.stat(ObjectRef("files", key), context=context)
        with objects.open_read(metadata.ref, context=context) as stream:
            blocks = []
            while True:
                context.remaining()
                block = stream.read(1024 * 1024)
                if not block:
                    break
                blocks.append(block)
            return b"".join(blocks)
    finally:
        objects.close()
