# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound gate for conversation file download.

The partner contract locks ``download`` to ``ignore`` and ``stream``: the
``redirect`` mode hands out a MinIO presigned URL (internal topology) and
``base64`` inlines the whole object, and neither belongs in the partner
contract. The lock is declared on the signature (``Query(pattern=...)``),
which is the enforced pre-check for this capability (§5.8 example three).

The gate shares the same service implementations as the internal route
(``check_file_access`` + ``get_file_url_impl`` / ``get_file_stream_impl``);
it does not call the internal handler so the response shaping stays per
contract: info mode goes through the northbound envelope, and a stream is
exempt from the envelope by contract — a byte stream cannot and should not
be wrapped in JSON (§5.4).
"""

from typing import Callable, Optional

from fastapi import APIRouter, Depends, Path as PathParam, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from contracts.authentication import AuthenticatedIdentity
from contracts.northbound_exposure import nb_exposed
from contracts.errors.exceptions import ForbiddenError, NotFoundException
from management.services.permission.identity.dependency import unified_identity
from management.services.permission.identity.gate_policies import (
    northbound_envelope_factory,
)
from management.utils.domain_errors import domain_error_body
from management.utils.request_context import get_request_id

nb_file_router = APIRouter(prefix="/nb/v1/file", tags=["northbound-gates"])


def _error_response(exc: Exception, request) -> JSONResponse:
    """Translate a domain exception into the three-field northbound error body."""
    body = domain_error_body(exc, get_request_id(request))
    if body is not None:
        return JSONResponse(status_code=body["status"], content=body)
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
            "status": 500,
            "requestId": get_request_id(request),
        },
    )


@nb_file_router.get("/download/{object_name:path}")
@nb_exposed("file.download")
async def nb_get_storage_file(
    request: Request,
    object_name: str = PathParam(..., description="File object name"),
    download: str = Query("ignore", pattern="^(ignore|stream)$", description="Download mode"),
    expires: int = Query(86400, ge=1, le=604800, description="URL validity period (seconds, 1..604800)"),
    filename: Optional[str] = Query(None, description="Original filename for download (optional)"),
    ctx: AuthenticatedIdentity = Depends(unified_identity),
    envelope: Callable = Depends(northbound_envelope_factory),
):
    """Download one file: info (ignore) or byte stream (stream).

    Ownership and access control reuse the internal route's service
    implementation; domain failures are translated by the shared registry
    into the three-field error body (403 for foreign objects, 404 for
    missing ones in both modes).

    Info mode signs against the external endpoint (partner direct links);
    stream mode iterates the raw storage body in chunks so neither the
    event loop nor memory carries the whole object.
    """
    # Late import: keeps the MinIO stack out of module import time.
    from management.services.file.access import check_file_access
    from management.services.file.service import get_file_stream_raw_impl, get_file_url_impl
    from management.api.file.http import _build_object_etag, build_content_disposition_header

    if not check_file_access(object_name, ctx.user_id, ctx.tenant_id):
        return _error_response(
            ForbiddenError("You don't have permission to access this file"), request
        )

    if download == "stream":
        try:
            file_stream, content_type = await get_file_stream_raw_impl(object_name=object_name)
        except Exception as exc:
            return _error_response(exc, request)
        download_filename = filename
        if not download_filename:
            download_filename = object_name.split("/")[-1] if "/" in object_name else object_name

        def iter_chunks():
            # Sync iterator: StreamingResponse runs each next() in the framework
            # threadpool, so blocking storage reads never stall the event loop.
            # finally closes the body on completion, error and client disconnect.
            try:
                while True:
                    chunk = file_stream.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                file_stream.close()

        # Streams are envelope-exempt. Authenticated partner bytes must never
        # enter a shared cache: the gateway forwards this header verbatim and
        # key revocation cannot invalidate a cached copy.
        return StreamingResponse(
            iter_chunks(),
            media_type=content_type,
            headers={
                "Content-Disposition": build_content_disposition_header(download_filename),
                "Cache-Control": "private, no-store",
                "ETag": _build_object_etag(object_name),
            },
        )

    # Presigning skips storage, so check existence here to avoid 200 + dead URL.
    # The probe is a synchronous MinIO round trip; keep it off the event loop.
    from management.db.file.attachment import get_file_size_from_minio_strict

    if await run_in_threadpool(get_file_size_from_minio_strict, object_name) is None:
        return _error_response(NotFoundException("Storage object does not exist"), request)
    try:
        # Partner direct links need the external signing authority; internal
        # proxy consumers keep the default internal authority (same-origin).
        result = await get_file_url_impl(object_name=object_name, expires=expires, external=True)
    except Exception as exc:
        return _error_response(exc, request)
    return envelope(result)
