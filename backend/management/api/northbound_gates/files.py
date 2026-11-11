# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound gate for conversation file download.

The partner contract locks ``download`` to ``ignore`` and ``stream``: the
``redirect`` mode hands out a MinIO presigned URL (internal topology) and
``base64`` inlines the whole object, and neither belongs in the partner
contract. The lock is declared on the signature — the manifest's
``params_lock`` is the gateway-side pre-check, this pattern is the second
layer (§5.8 example three).

The gate shares the same service implementations as the internal route
(``check_file_access`` + ``get_file_url_impl`` / ``get_file_stream_impl``);
it does not call the internal handler so the response shaping stays per
contract: info mode goes through the northbound envelope, and a stream is
exempt from the envelope by contract — a byte stream cannot and should not
be wrapped in JSON (§5.4).
"""

from typing import Callable, Optional

from fastapi import APIRouter, Depends, Path as PathParam, Query
from fastapi.responses import StreamingResponse

from contracts.authentication import AuthenticatedIdentity
from contracts.errors.exceptions import ForbiddenError
from management.services.permission.identity.dependency import unified_identity
from management.services.permission.identity.gate_policies import (
    northbound_envelope_factory,
)

nb_file_router = APIRouter(prefix="/nb/v1/file", tags=["northbound-gates"])


@nb_file_router.get("/download/{object_name:path}")
async def nb_get_storage_file(
    object_name: str = PathParam(..., description="File object name"),
    download: str = Query("ignore", pattern="^(ignore|stream)$", description="Download mode"),
    expires: int = Query(86400, description="URL validity period (seconds)"),
    filename: Optional[str] = Query(None, description="Original filename for download (optional)"),
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
):
    """Download one file: info (ignore) or byte stream (stream).

    Ownership and access control reuse the internal route's service
    implementation; failures are domain exceptions translated by the shared
    registry, so the partner sees the three-field error body.
    """
    # Imported here so the gate module does not pull the MinIO stack at import
    # time and stubbed test apps keep working.
    from management.services.file.access import check_file_access
    from management.services.file.service import get_file_stream_impl, get_file_url_impl
    from management.utils.file_http import _build_object_etag, build_content_disposition_header

    if not check_file_access(object_name, ctx.user_id, ctx.tenant_id):
        raise ForbiddenError("You don't have permission to access this file")

    if download == "stream":
        file_stream, content_type = await get_file_stream_impl(object_name=object_name)
        download_filename = filename
        if not download_filename:
            download_filename = object_name.split("/")[-1] if "/" in object_name else object_name
        # Stream responses are envelope-exempt: pass the bytes through.
        return StreamingResponse(
            file_stream,
            media_type=content_type,
            headers={
                "Content-Disposition": build_content_disposition_header(download_filename),
                "Cache-Control": "public, max-age=3600",
                "ETag": _build_object_etag(object_name),
            },
        )

    # ignore mode: file information through the northbound envelope.
    result = await get_file_url_impl(object_name=object_name, expires=expires)
    return envelope(result)
