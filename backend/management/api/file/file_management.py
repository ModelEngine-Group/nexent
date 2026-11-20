# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from contracts.object_tickets import InvalidObjectTicket, issue_download_url
from management.api.file.http import ObjectStreamingResponse
from management.services.file.download import byte_chunks, open_preview, read_download

from contracts.errors.exceptions import AppException, FileTooLargeException, NotFoundException, QuotaExceededError, UnauthorizedError, UnsupportedFileTypeException
from management.api.file.http import _build_datamate_url_from_parts, _build_object_etag, _normalize_datamate_download_url, _parse_range_header, build_content_disposition_header
import base64
import logging
import re
from http import HTTPStatus
from typing import Annotated, List, Literal, Optional
from urllib.parse import unquote, urlparse
import httpx
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.errors import StorageError
from contracts.errors.exceptions import ManagementReadBusyError
from fastapi import APIRouter, Body, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from management.utils.knowledge_permission import require_knowledge_base_edit_permission
from contracts.errors.exceptions import AppException, FileTooLargeException, NotFoundException, QuotaExceededError, UnauthorizedError, UnsupportedFileTypeException
from contracts.constants.constants import CONFIG_SERVICE_NAME
from management.services.file.service import (
    check_file_access,
    get_file_url_impl,
    list_files_impl,
    upload_files_impl,
)
from management.services.file.object_deletion import delete_file_impl
from management.services.file.preview import resolve_preview_file
from management.services.monitor.audit import AUDIT_DETAIL_LIST_LIMIT, record_security_event
from management.services.permission.identity.session import get_current_user_id
from management.services.knowledge_base.ingestion import submit_knowledge_files


logger = logging.getLogger("file_management_app")


file_management_config_router = APIRouter(prefix="/file")


@file_management_config_router.options("/{full_path:path}")
async def options_route(full_path: str):
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"detail": "OK"},
    )


@file_management_config_router.post("/upload")
async def upload_files(
    http_request: Request,
    file: List[UploadFile] = File(..., alias="file"),
    destination: Literal["local", "minio"] = Form(..., description="Upload destination: 'local' or 'minio'"),
    folder: str = Form("attachments", description="Storage folder path for MinIO (optional)"),
    index_name: Optional[str] = Form(None, description="Knowledge base index for conflict resolution"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    try:
        if not file:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="No files in the request")

        user_id, tenant_id = get_current_user_id(authorization)
        if index_name:
            require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        upload_result = await upload_files_impl(
            destination,
            file,
            folder,
            index_name,
            user_id,
            uploader_tenant_id=tenant_id,
            upload_owner_service=CONFIG_SERVICE_NAME,
        )
        errors, uploaded_file_paths, uploaded_filenames = upload_result
        quota_status = getattr(upload_result, "quota_status", None)
        lifecycle_fields = (
            "file_id",
            "object_name",
            "original_filename",
            "file_size",
            "status",
            "stage",
            "uploaded_at",
            "error_code",
            "error_message",
            "error_stage",
            "failed_at",
        )
        file_records = [
            {field: record.get(field) for field in lifecycle_fields}
            for record in getattr(upload_result, "file_records", [])
            if isinstance(record, dict)
        ]

        if uploaded_file_paths:
            response_content = {
                "message": f"Files uploaded successfully to {destination}, ready for processing.",
                "uploaded_filenames": uploaded_filenames,
                "uploaded_file_paths": uploaded_file_paths,
                "errors": errors,
                "file_records": file_records,
            }
            if quota_status:
                response_content["quota_status"] = quota_status.get("quota_status")
            # Audit the successful upload with identifiers only (names, count,
            # target index); file content never reaches the log. This is the
            # KB source-file path where storage-quota abuse would show up.
            record_security_event(
                "file_upload",
                request=http_request,
                user_id=user_id,
                tenant_id=tenant_id,
                details={
                    "destination": destination,
                    "index_name": index_name,
                    "files_count": len(uploaded_filenames),
                    "filenames": uploaded_filenames[:AUDIT_DETAIL_LIST_LIMIT],
                },
            )
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content=response_content,
            )
        else:
            # Keep the legacy detail string while exposing per-file failure details for
            # callers that need to render the actual upload error.
            response_content = {
                "message": "No valid files uploaded",
                "detail": "No valid files uploaded",
                "uploaded_filenames": uploaded_filenames,
                "uploaded_file_paths": uploaded_file_paths,
                "errors": errors,
                "file_records": file_records,
            }
            if quota_status:
                response_content["quota_status"] = quota_status.get("quota_status")
            return JSONResponse(
                status_code=HTTPStatus.BAD_REQUEST,
                content=response_content,
            )
    except HTTPException:
        raise
    except AppException:
        raise
    except QuotaExceededError:
        raise
    except (TimeoutError, DeadlineExceeded):
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            content={"message": "File upload error."})
    except Exception as e:
        logger.error(f"File upload error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="File upload error.")


@file_management_config_router.post("/process")
async def process_files(
    files: Annotated[
        List[dict], Body(..., description="List of file details to process, including path_or_url and filename")
    ],
    index_name: Annotated[str, Body(...)],
    destination: Annotated[str, Body(...)],
    chunking_strategy: Annotated[Optional[str], Body(...)] = "basic",
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Admit uploaded files through Management's persistent ingestion pipeline."""
    from infrastructure.agentos_identity import ServicePrincipal

    user_id, tenant_id = get_current_user_id(authorization)
    require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
    process_result = await submit_knowledge_files(
        files, index_name, ServicePrincipal(user_id, tenant_id),
        destination=destination, chunking_strategy=chunking_strategy,
    )
    if not process_result or process_result.get("status") in {"error", "failed"}:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=(process_result or {}).get("message") or "Data process service failed")
    failed_results = [row for row in process_result.get("results", []) if row["status"] == "FAILED"]
    if failed_results:
        return JSONResponse(
            status_code=HTTPStatus.CREATED,
            content={"message": "Files processing partially triggered", "process_tasks": process_result,
                     "failed_files": failed_results},
        )
    return JSONResponse(
        status_code=HTTPStatus.CREATED,
        content={"message": "Files processing triggered successfully", "process_tasks": process_result},
    )


@file_management_config_router.get("/download/{object_name:path}")
async def get_storage_file(
    http_request: Request,
    object_name: str = PathParam(..., description="File object name"),
    download: str = Query(
        "ignore",
        description=(
            "How to get the file: "
            "'ignore' (default, return file info), "
            "'stream' (return file stream), "
            "'redirect' (redirect to download URL), "
            "'base64' (return base64-encoded content for images)."
        ),
    ),
    expires: int = Query(86400, description="URL validity period (seconds)"),
    filename: Optional[str] = Query(None, description="Original filename for download (optional)"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Get information, download link, or file stream for a single file.

    Access control:
    - knowledge_base/*: All authenticated users can access
    - attachments/{user_id}/*: Only the owner (user_id) can access

    - **object_name**: File object name
    - **download**: Download mode: ignore (default, return file info), stream (return file stream), redirect (redirect to download URL)
    - **expires**: URL validity period in seconds (default 86400 = 24 hours)
    - **filename**: Original filename for download (optional, if not provided, will use object_name)

    Returns file information, download link, or file content
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        if not check_file_access(object_name, user_id, tenant_id):
            logger.warning(f"[get_storage_file] Access denied: object_name={object_name}, user_id={user_id}")
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="You don't have permission to access this file"
            )

        logger.info(
            f"[get_storage_file] Route matched! object_name={object_name}, download={download}, filename={filename}"
        )
        if download == "redirect":
            result = await get_file_url_impl(object_name=object_name, expires=expires)
            return RedirectResponse(url=result["url"])
        elif download == "stream":
            file_data, content_type = await read_download(object_name, http_request)
            logger.info(f"Streaming file: object_name={object_name}, content_type={content_type}")

            download_filename = filename
            if not download_filename:
                download_filename = object_name.split("/")[-1] if "/" in object_name else object_name

            content_disposition = build_content_disposition_header(download_filename)

            return StreamingResponse(
                byte_chunks(file_data),
                media_type=content_type,
                headers={
                    "Content-Disposition": content_disposition,
                    "Cache-Control": "public, max-age=3600",
                    "ETag": _build_object_etag(object_name),
                },
            )
        elif download == "base64":
            file_data, content_type = await read_download(object_name, http_request)
            data = file_data

            base64_content = base64.b64encode(data).decode("utf-8")
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "success": True,
                    "base64": base64_content,
                    "content_type": content_type,
                    "object_name": object_name,
                },
            )
        else:
            return await get_file_url_impl(object_name=object_name, expires=expires)
    except HTTPException:
        raise
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except NotFoundException as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="File not found.") from e
    except DeadlineExceeded:
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, content={'message': 'Failed to get file.'})
    except ManagementReadBusyError:
        raise
    except Exception as e:
        logger.error(f"Failed to get file: object_name={object_name}, error={str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to get file.")


@file_management_config_router.get("/storage")
async def get_storage_files(
    prefix: str = Query("", description="File prefix filter"),
    limit: int = Query(100, description="Maximum number of files to return"),
    include_urls: bool = Query(True, description="Whether to include presigned URLs"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Get list of files from MinIO storage.

    Access control:
    - Returns only files the user has permission to access:
      - knowledge_base/*: All authenticated users can access
      - attachments/{user_id}/*: Only the owner's files

    - **prefix**: File prefix filter (optional)
    - **limit**: Maximum number of files to return (default 100)
    - **include_urls**: Whether to include presigned URLs (default True)

    Returns file list and metadata
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        files = await list_files_impl(prefix, limit)

        if user_id:
            filtered_files = [f for f in files if f.get("key") and check_file_access(f.get("key"), user_id, tenant_id)]
        else:
            filtered_files = []

        files = filtered_files

        for file in files:
            if include_urls:
                try:
                    file["url"] = issue_download_url(file["key"])
                except InvalidObjectTicket:
                    pass
            else:
                file.pop("url", None)

        return {"total": len(files), "files": files}
    except HTTPException:
        raise
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Get storage files error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Get storage files error.")


@file_management_config_router.get("/datamate/download")
async def download_datamate_file(
    url: Optional[str] = Query(None, description="Datamate file URL to download"),
    base_url: Optional[str] = Query(None, description="Datamate base server URL (e.g., host:port)"),
    dataset_id: Optional[str] = Query(None, description="Datamate dataset ID"),
    file_id: Optional[str] = Query(None, description="Datamate file ID"),
    filename: Optional[str] = Query(None, description="Optional filename for download"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Download file from Datamate knowledge base via HTTP URL

    - **url**: Full HTTP URL of the file to download (optional)
    - **base_url**: Base server URL (e.g., host:port)
    - **dataset_id**: Datamate dataset ID
    - **file_id**: Datamate file ID
    - **filename**: Optional filename for the download (extracted automatically if not provided)
    - **authorization**: Optional authorizatio  n header to pass to the target URL

    Returns file stream for download
    """
    try:
        if url:
            logger.info(f"[download_datamate_file] Using full URL: {url}")
            normalized_url = _normalize_datamate_download_url(url)
        elif base_url and dataset_id and file_id:
            logger.info(
                f"[download_datamate_file] Building URL from parts: base_url={base_url}, dataset_id={dataset_id}, file_id={file_id}"
            )
            normalized_url = _build_datamate_url_from_parts(base_url, dataset_id, file_id)
        else:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Either url or (base_url, dataset_id, file_id) must be provided",
            )

        logger.info(f"[download_datamate_file] Normalized download URL: {normalized_url}")
        logger.info(f"[download_datamate_file] Authorization header present: {authorization is not None}")

        headers = {}
        if authorization:
            headers["Authorization"] = authorization
            logger.debug(f"[download_datamate_file] Using authorization header: {authorization[:20]}...")
        headers["User-Agent"] = "Nexent-File-Downloader/1.0"

        logger.info(f"[download_datamate_file] Request headers: {list(headers.keys())}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(normalized_url, headers=headers, follow_redirects=True)
            logger.info(f"[download_datamate_file] Response status: {response.status_code}")

            if response.status_code == 404:
                logger.error(f"[download_datamate_file] File not found at URL: {normalized_url}")
                logger.error(f"[download_datamate_file] Response headers: {dict(response.headers)}")
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND, detail="File not found. Please verify dataset_id and file_id."
                )

            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "application/octet-stream")

            download_filename = filename
            if not download_filename:
                content_disposition = response.headers.get("Content-Disposition", "")
                if content_disposition:
                    filename_match = re.search(r'filename="?(.+?)"?$', content_disposition)
                    if filename_match:
                        download_filename = filename_match.group(1)

                if not download_filename:
                    path = unquote(urlparse(normalized_url).path)
                    download_filename = path.split("/")[-1] or "download"

            # Build Content-Disposition header with proper encoding for non-ASCII characters
            content_disposition = build_content_disposition_header(download_filename)

            return StreamingResponse(
                iter([response.content]), media_type=content_type, headers={"Content-Disposition": content_disposition}
            )
    except httpx.HTTPError as e:
        logger.error(f"Failed to download file from URL {url}: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail=f"Failed to download file from URL: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download datamate file: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Failed to download file: {str(e)}")


@file_management_config_router.delete("/storage/{object_name:path}")
async def remove_storage_file(
    object_name: str = PathParam(..., description="File object name to delete"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Delete file from MinIO storage.

    Access control:
    - knowledge-base sources: Require an active ledger row mapped to the requested
      knowledge base and EDIT/CREATOR permission
    - attachments/{user_id}/*: Only the owner (user_id) can delete

    - **object_name**: File object name to delete

    Returns deletion operation result
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        await delete_file_impl(
            object_name=object_name,
            tenant_id=tenant_id,
            updated_by=user_id,
        )
        return {"success": True, "message": f"File {object_name} successfully deleted"}
    except HTTPException:
        raise
    except PermissionError as e:
        logger.warning("[remove_storage_file] Tenant ownership check failed")
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(e))
    except (TimeoutError, DeadlineExceeded):
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Remove storage file error.") from None
    except Exception:
        logger.exception("Remove storage file error")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Remove storage file error.")


@file_management_config_router.post("/storage/batch-urls")
async def get_storage_file_batch_urls(
    request_data: dict = Body(..., description="JSON containing list of file object names"),
    expires: int = Query(3600, description="URL validity period (seconds)"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Batch get download URLs for multiple files (JSON request).

    Access control:
    - knowledge_base/*: All authenticated users can access
    - attachments/{user_id}/*: Only the owner (user_id) can access

    - **request_data**: JSON request body containing object_names list
    - **expires**: URL validity period in seconds (default 86400 = 24 hours)

    Returns URL and status information for each file
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        object_names = request_data.get("object_names", [])
        if not object_names or not isinstance(object_names, list):
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST, detail="Request body must contain object_names array"
            )

        results = []

        for object_name in object_names:
            if not check_file_access(object_name, user_id, tenant_id):
                results.append({"object_name": object_name, "success": False, "error": "Access denied"})
                continue

            try:
                result = await get_file_url_impl(object_name=object_name, expires=expires)
                results.append(
                    {
                        "object_name": object_name,
                        "success": result["success"],
                        "url": result.get("url"),
                        "error": result.get("error"),
                    }
                )
            except Exception as e:
                results.append({"object_name": object_name, "success": False, "error": str(e)})

        return {
            "total": len(results),
            "success_count": sum(1 for r in results if r.get("success", False)),
            "failed_count": sum(1 for r in results if not r.get("success", False)),
            "results": results,
        }
    except HTTPException:
        raise
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Batch URLs error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Batch URLs error.")


@file_management_config_router.get("/preview/{object_name:path}")
async def preview_file(
    http_request: Request,
    object_name: str = PathParam(..., description="File object name to preview"),
    filename: Annotated[Optional[str], Query(description="Original filename for display (optional)")] = None,
    range_header: Annotated[Optional[str], Header(alias="range")] = None,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Preview file inline in browser.

    Access control:
    - knowledge_base/*: All authenticated users can access
    - attachments/{user_id}/*: Only the owner (user_id) can access
    - attachments/asset_owner/{user_id}/*: ASSET_OWNER virtual tenant and owner only

    - **object_name**: File object name in storage
    - **filename**: Original filename for Content-Disposition header (optional)

    Supports HTTP Range requests (RFC 7233) for partial content delivery.
    Returns 206 Partial Content when a valid Range header is present.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        if not check_file_access(object_name, user_id, tenant_id):
            logger.warning(f"[preview_file] Access denied: object_name={object_name}, user_id={user_id}")
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail="You don't have permission to access this file"
            )

        actual_name, content_type, total_size = await resolve_preview_file(object_name=object_name)
    except FileTooLargeException as e:
        logger.warning(f"[preview_file] File too large: object_name={object_name}, error={str(e)}")
        raise HTTPException(status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, detail=str(e))
    except NotFoundException as e:
        logger.error(f"[preview_file] File not found: object_name={object_name}, error={str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File not found: {object_name}")
    except UnsupportedFileTypeException as e:
        logger.error(f"[preview_file] Unsupported file type: object_name={object_name}, error={str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=f"File format not supported for preview: {str(e)}"
        )
    except HTTPException:
        raise
    except UnauthorizedError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except DeadlineExceeded:
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, content={'message': 'Failed to preview file'})
    except Exception as e:
        logger.error(f"[preview_file] Unexpected error: object_name={object_name}, error={str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to preview file")

    display_filename = filename or (object_name.split("/")[-1] if "/" in object_name else object_name)
    content_disposition = build_content_disposition_header(display_filename, inline=True)

    common_headers = {
        "Content-Disposition": content_disposition,
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
        "ETag": _build_object_etag(object_name),
    }

    if total_size == 0:
        return StreamingResponse(
            iter([]),
            status_code=HTTPStatus.OK,
            media_type=content_type,
            headers={
                **common_headers,
                "Content-Length": "0",
            },
        )

    # Parse Range header
    start, end = None, None
    if range_header:
        parsed = _parse_range_header(range_header, total_size)
        if parsed is None:
            return StreamingResponse(
                iter([]),
                status_code=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{total_size}"},
            )
        start, end = parsed

    try:
        if start is not None:
            # 206 Partial Content
            stream = await open_preview(actual_name, http_request, start, end)
            return ObjectStreamingResponse(
                stream,
                status_code=HTTPStatus.PARTIAL_CONTENT,
                media_type=content_type,
                headers={
                    **common_headers,
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(end - start + 1),
                },
            )
        else:
            # 200 Full Content — no Range header present.
            stream = await open_preview(actual_name, http_request)
            return ObjectStreamingResponse(
                stream,
                status_code=HTTPStatus.OK,
                media_type=content_type,
                headers={
                    **common_headers,
                    "Content-Length": str(total_size),
                },
            )
    except NotFoundException as e:
        logger.error(f"[preview_file] File not found when streaming: object_name={object_name}, error={str(e)}")
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File not found: {object_name}")
    except DeadlineExceeded:
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, content={'message': 'Failed to preview file'})
    except ManagementReadBusyError:
        raise
    except StorageError:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File not found: {object_name}") from None
    except Exception as e:
        logger.error(f"[preview_file] Unexpected error when streaming: object_name={object_name}, error={str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to preview file")
