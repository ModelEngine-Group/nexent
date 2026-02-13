import logging
import re
import base64
from http import HTTPStatus
from typing import List, Optional
from urllib.parse import urlparse, urlunparse, unquote, quote

import httpx
from fastapi import APIRouter, Body, File, Form, Header, HTTPException, Path as PathParam, Query, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from consts.model import ProcessParams
from services.file_management_service import upload_to_minio, upload_files_impl, \
    get_file_url_impl, get_file_stream_impl, delete_file_impl, list_files_impl, \
    preview_file_impl
from utils.file_management_utils import trigger_data_process

logger = logging.getLogger("file_management_app")


def build_content_disposition_header(filename: Optional[str], inline: bool = False) -> str:
    """
    Build a Content-Disposition header that keeps the original filename.

    Args:
        filename: Original filename to include in header
        inline: If True, use 'inline' disposition (for preview); otherwise 'attachment' (for download)

    - ASCII filenames are returned directly.
    - Non-ASCII filenames include both an ASCII fallback and RFC 5987 encoded value
      so modern browsers keep the original name.
    """
    disposition = "inline" if inline else "attachment"
    safe_name = (filename or "download").strip() or "download"

    def _sanitize_ascii(value: str) -> str:
        # Replace problematic characters that break HTTP headers
        # Remove control characters (newlines, carriage returns, tabs, etc.)
        # Remove control characters (0x00-0x1F and 0x7F)
        sanitized = re.sub(r'[\x00-\x1F\x7F]', '', value)
        # Replace problematic characters that break HTTP headers
        sanitized = sanitized.replace("\\", "_").replace('"', "_")
        # Remove leading/trailing spaces and dots (Windows filename restrictions)
        sanitized = sanitized.strip(' .')
        return sanitized if sanitized else "download"

    try:
        safe_name.encode("ascii")
        return f'{disposition}; filename="{_sanitize_ascii(safe_name)}"'
    except UnicodeEncodeError:
        try:
            encoded = quote(safe_name, safe="")
        except Exception:
            # quote failure, fallback to sanitized ASCII only
            logger.warning("Failed to encode filename '%s', using fallback", safe_name)
            return f'{disposition}; filename="{_sanitize_ascii(safe_name)}"'

        fallback = _sanitize_ascii(
            safe_name.encode("ascii", "ignore").decode("ascii") or "download"
        )
        return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Failed to encode filename '%s': %s. Using fallback.",
            safe_name,
            exc,
        )
        return f'{disposition}; filename="download"'

# Create API router
file_management_runtime_router = APIRouter(prefix="/file")
file_management_config_router = APIRouter(prefix="/file")


# Handle preflight requests
@file_management_config_router.options("/{full_path:path}")
async def options_route(full_path: str):
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"detail": "OK"},
    )


@file_management_config_router.post("/upload")
async def upload_files(
        file: List[UploadFile] = File(..., alias="file"),
        destination: str = Form(...,
                                description="Upload destination: 'local' or 'minio'"),
        folder: str = Form(
            "attachments", description="Storage folder path for MinIO (optional)"),
        index_name: Optional[str] = Form(
            None, description="Knowledge base index for conflict resolution")
):
    if not file:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="No files in the request")

    errors, uploaded_file_paths, uploaded_filenames = await upload_files_impl(destination, file, folder, index_name)

    if uploaded_file_paths:
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": f"Files uploaded successfully to {destination}, ready for processing.",
                "uploaded_filenames": uploaded_filenames,
                "uploaded_file_paths": uploaded_file_paths,
                "errors": errors
            }
        )
    else:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="No valid files uploaded")


@file_management_config_router.post("/process")
async def process_files(
        files: List[dict] = Body(
            ..., description="List of file details to process, including path_or_url and filename"),
        chunking_strategy: Optional[str] = Body("basic"),
        index_name: str = Body(...),
        destination: str = Body(...),
        authorization: Optional[str] = Header(None)
):
    """
    Trigger data processing for a list of uploaded files.
    files: List of dicts, each with "path_or_url" and "filename"
    chunking_strategy: chunking strategy, could be chosen from basic/by_title/none
    index_name: index name in elasticsearch
    destination: 'local' or 'minio'
    """
    process_params = ProcessParams(
        chunking_strategy=chunking_strategy,
        source_type=destination,
        index_name=index_name,
        authorization=authorization
    )

    process_result = await trigger_data_process(files, process_params)

    if process_result is None or (isinstance(process_result, dict) and process_result.get("status") == "error"):
        error_message = "Data process service failed"
        if isinstance(process_result, dict) and "message" in process_result:
            error_message = process_result["message"]
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=error_message)

    return JSONResponse(
        status_code=HTTPStatus.CREATED,
        content={
            "message": "Files processing triggered successfully",
            "process_tasks": process_result
        }
    )


@file_management_config_router.get("/download/{object_name:path}")
async def get_storage_file(
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
    expires: int = Query(3600, description="URL validity period (seconds)"),
    filename: Optional[str] = Query(None, description="Original filename for download (optional)")
):
    """
    Get information, download link, or file stream for a single file

    - **object_name**: File object name
    - **download**: Download mode: ignore (default, return file info), stream (return file stream), redirect (redirect to download URL)
    - **expires**: URL validity period in seconds (default 3600)
    - **filename**: Original filename for download (optional, if not provided, will use object_name)

    Returns file information, download link, or file content
    """
    try:
        logger.info(f"[get_storage_file] Route matched! object_name={object_name}, download={download}, filename={filename}")
        if download == "redirect":
            # return a redirect download URL
            result = await get_file_url_impl(object_name=object_name, expires=expires)
            return RedirectResponse(url=result["url"])
        elif download == "stream":
            # return a readable file stream
            file_stream, content_type = await get_file_stream_impl(object_name=object_name)
            logger.info(f"Streaming file: object_name={object_name}, content_type={content_type}")
            
            # Use provided filename or extract from object_name
            download_filename = filename
            if not download_filename:
                # Extract filename from object_name (get the last part after the last slash)
                download_filename = object_name.split("/")[-1] if "/" in object_name else object_name
            
            # Build Content-Disposition header with proper encoding for non-ASCII characters
            content_disposition = build_content_disposition_header(download_filename)
            
            return StreamingResponse(
                file_stream,
                media_type=content_type,
                headers={
                    "Content-Disposition": content_disposition,
                    "Cache-Control": "public, max-age=3600",
                    "ETag": f'"{object_name}"',
                }
            )
        elif download == "base64":
            # Return base64 encoded file content (primarily for images)
            file_stream, content_type = await get_file_stream_impl(object_name=object_name)
            try:
                data = file_stream.read()
            except Exception as exc:
                logger.error("Failed to read file stream for base64: %s", str(exc))
                raise HTTPException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail="Failed to read file content for base64 encoding",
                )

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
            # return file metadata
            return await get_file_url_impl(object_name=object_name, expires=expires)
    except Exception as e:
        logger.error(f"Failed to get file: object_name={object_name}, error={str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file information: {str(e)}"
        )



@file_management_runtime_router.post("/storage")
async def storage_upload_files(
    files: List[UploadFile] = File(..., description="List of files to upload"),
    folder: str = Form(
        "attachments", description="Storage folder path (optional)")
):
    """
    Upload one or more files to MinIO storage

    - **files**: List of files to upload
    - **folder**: Storage folder path (optional, defaults to 'attachments')

    Returns upload results including file information and access URLs
    """
    results = await upload_to_minio(files=files, folder=folder)

    # Return upload results for all files
    return {
        "message": f"Processed {len(results)} files",
        "success_count": sum(1 for r in results if r.get("success", False)),
        "failed_count": sum(1 for r in results if not r.get("success", False)),
        "results": results
    }


@file_management_config_router.get("/storage")
async def get_storage_files(
    prefix: str = Query("", description="File prefix filter"),
    limit: int = Query(100, description="Maximum number of files to return"),
    include_urls: bool = Query(
        True, description="Whether to include presigned URLs")
):
    """
    Get list of files from MinIO storage

    - **prefix**: File prefix filter (optional)
    - **limit**: Maximum number of files to return (default 100)
    - **include_urls**: Whether to include presigned URLs (default True)

    Returns file list and metadata
    """
    try:
        files = await list_files_impl(prefix, limit)
        # Remove URLs if not needed
        if not include_urls:
            for file in files:
                if "url" in file:
                    del file["url"]

        return {
            "total": len(files),
            "files": files
        }
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file list: {str(e)}"
        )


def _ensure_http_scheme(raw_url: str) -> str:
    """
    Ensure the provided Datamate URL has an explicit HTTP or HTTPS scheme.
    """
    candidate = (raw_url or "").strip()
    if not candidate:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="URL cannot be empty"
        )

    parsed = urlparse(candidate)
    if parsed.scheme:
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="URL must start with http:// or https://"
            )
        return candidate

    if candidate.startswith("//"):
        return f"http:{candidate}"

    return f"http://{candidate}"


def _normalize_datamate_download_url(raw_url: str) -> str:
    """
    Normalize Datamate download URL to ensure it follows /data-management/datasets/{datasetId}/files/{fileId}/download
    """
    normalized_source = _ensure_http_scheme(raw_url)
    parsed_url = urlparse(normalized_source)
    path_segments = [segment for segment in parsed_url.path.split("/") if segment]

    if "data-management" not in path_segments:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Invalid Datamate URL: missing 'data-management' segment"
        )

    try:
        dm_index = path_segments.index("data-management")
        datasets_index = path_segments.index("datasets", dm_index)
        dataset_id = path_segments[datasets_index + 1]
        files_index = path_segments.index("files", datasets_index)
        file_id = path_segments[files_index + 1]
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Invalid Datamate URL: unable to parse dataset_id or file_id"
        )

    prefix_segments = path_segments[:dm_index]
    prefix_path = "/" + "/".join(prefix_segments) if prefix_segments else ""
    normalized_path = f"{prefix_path}/data-management/datasets/{dataset_id}/files/{file_id}/download"

    normalized_url = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        normalized_path,
        "",
        "",
        ""
    ))

    return normalized_url


def _build_datamate_url_from_parts(base_url: str, dataset_id: str, file_id: str) -> str:
    """
    Build Datamate download URL from individual parts
    """
    if not base_url:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="base_url is required when dataset_id and file_id are provided"
        )

    base_with_scheme = _ensure_http_scheme(base_url)
    parsed_base = urlparse(base_with_scheme)
    base_prefix = parsed_base.path.rstrip("/")

    if base_prefix and not base_prefix.endswith("/api"):
        if base_prefix.endswith("/"):
            base_prefix = f"{base_prefix}api"
        else:
            base_prefix = f"{base_prefix}/api"
    elif not base_prefix:
        base_prefix = "/api"

    normalized_path = f"{base_prefix}/data-management/datasets/{dataset_id}/files/{file_id}/download"

    return urlunparse((
        parsed_base.scheme,
        parsed_base.netloc,
        normalized_path,
        "",
        "",
        ""
    ))


@file_management_config_router.get("/datamate/download")
async def download_datamate_file(
    url: Optional[str] = Query(None, description="Datamate file URL to download"),
    base_url: Optional[str] = Query(None, description="Datamate base server URL (e.g., host:port)"),
    dataset_id: Optional[str] = Query(None, description="Datamate dataset ID"),
    file_id: Optional[str] = Query(None, description="Datamate file ID"),
    filename: Optional[str] = Query(None, description="Optional filename for download"),
    authorization: Optional[str] = Header(None, alias="Authorization")
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
            logger.info(f"[download_datamate_file] Building URL from parts: base_url={base_url}, dataset_id={dataset_id}, file_id={file_id}")
            normalized_url = _build_datamate_url_from_parts(base_url, dataset_id, file_id)
        else:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Either url or (base_url, dataset_id, file_id) must be provided"
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
                    status_code=HTTPStatus.NOT_FOUND,
                    detail="File not found. Please verify dataset_id and file_id."
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
                    download_filename = path.split('/')[-1] or "download"

            # Build Content-Disposition header with proper encoding for non-ASCII characters
            content_disposition = build_content_disposition_header(download_filename)
            
            return StreamingResponse(
                iter([response.content]),
                media_type=content_type,
                headers={
                    "Content-Disposition": content_disposition
                }
            )
    except httpx.HTTPError as e:
        logger.error(f"Failed to download file from URL {url}: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_GATEWAY,
            detail=f"Failed to download file from URL: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download datamate file: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}"
        )


@file_management_config_router.delete("/storage/{object_name:path}")
async def remove_storage_file(
    object_name: str = PathParam(..., description="File object name to delete")
):
    """
    Delete file from MinIO storage

    - **object_name**: File object name to delete

    Returns deletion operation result
    """
    try:
        await delete_file_impl(object_name=object_name)
        return {
            "success": True,
            "message": f"File {object_name} successfully deleted"
        }
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {str(e)}"
        )


@file_management_config_router.post("/storage/batch-urls")
async def get_storage_file_batch_urls(
    request_data: dict = Body(...,
                              description="JSON containing list of file object names"),
    expires: int = Query(3600, description="URL validity period (seconds)")
):
    """
    Batch get download URLs for multiple files (JSON request)

    - **request_data**: JSON request body containing object_names list
    - **expires**: URL validity period in seconds (default 3600)

    Returns URL and status information for each file
    """
    # Extract object_names from request body
    object_names = request_data.get("object_names", [])
    if not object_names or not isinstance(object_names, list):
        raise HTTPException(
            status_code=400, detail="Request body must contain object_names array")

    results = []

    for object_name in object_names:
        try:
            # Get file URL
            result = get_file_url_impl(
                object_name=object_name, expires=expires)
            results.append({
                "object_name": object_name,
                "success": result["success"],
                "url": result.get("url"),
                "error": result.get("error")
            })
        except Exception as e:
            results.append({
                "object_name": object_name,
                "success": False,
                "error": str(e)
            })

    return {
        "total": len(results),
        "success_count": sum(1 for r in results if r.get("success", False)),
        "failed_count": sum(1 for r in results if not r.get("success", False)),
        "results": results
    }

@file_management_config_router.get("/preview/{object_name:path}")
async def preview_file(
    object_name: str = PathParam(..., description="File object name to preview"),
    filename: Optional[str] = Query(None, description="Original filename for display (optional)")
):
    """
    Preview file inline in browser 
    
    - **object_name**: File object name in storage
    - **filename**: Original filename for Content-Disposition header (optional)
    
    Returns file stream with Content-Disposition: inline for browser preview
    """
    try:
        # Get file stream from preview service
        file_stream, content_type = await preview_file_impl(object_name=object_name)
        
        # Use provided filename or extract from object_name
        display_filename = filename
        if not display_filename:
            display_filename = object_name.split("/")[-1] if "/" in object_name else object_name
        
        # Build Content-Disposition header for inline display
        content_disposition = build_content_disposition_header(display_filename, inline=True)

        return StreamingResponse(
            file_stream,
            media_type=content_type,
            headers={
                "Content-Disposition": content_disposition,
                "Cache-Control": "public, max-age=3600",
                "ETag": f'"{object_name}"',
            }
        )
    
    except Exception as e:
        logger.error(f"[preview_file] Preview failed: object_name={object_name}, error={str(e)}")
        
        # Return appropriate HTTP status based on error type
        if "not found" in str(e).lower() or "does not exist" in str(e).lower():
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"File not found: {object_name}"
            )
        elif "unsupported" in str(e).lower():
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=f"File format not supported for preview: {str(e)}"
            )
        else:
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f"Failed to preview file: {str(e)}"
            )