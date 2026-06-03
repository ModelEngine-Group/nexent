import asyncio
import hashlib
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from fastapi import UploadFile

from consts.const import (
    ASSET_OWNER_ATTACHMENTS_PREFIX,
    ASSET_OWNER_TENANT_ID,
    DATA_PROCESS_SERVICE,
    FILE_PREVIEW_SIZE_LIMIT,
    MAX_CONCURRENT_UPLOADS,
    MODEL_CONFIG_MAPPING,
    OFFICE_MIME_TYPES,
    UPLOAD_FOLDER,
)
from consts.exceptions import FileTooLargeException, NotFoundException, OfficeConversionException, UnsupportedFileTypeException
from database.attachment_db import (
    copy_file,
    delete_file,
    file_exists,
    get_content_type,
    get_file_range,
    get_file_size_from_minio,
    get_file_stream,
    get_file_stream_raw,
    get_file_url,
    list_files,
    upload_fileobj,
)
from services.vectordatabase_service import ElasticSearchService, get_vector_db_core
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.file_management_utils import save_upload_file

from nexent import MessageObserver
from nexent.multi_modal.utils import parse_s3_url
from nexent.core.models import OpenAILongContextModel

# Create upload directory
upload_dir = Path(UPLOAD_FOLDER)
upload_dir.mkdir(exist_ok=True)
upload_semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

# Per-file locks prevent duplicate conversions of the same file
_conversion_locks: dict[str, asyncio.Lock] = {}
_conversion_locks_guard = asyncio.Lock()

logger = logging.getLogger("file_management_service")


def resolve_minio_upload_folder(
    folder: Optional[str],
    user_id: Optional[str] = None,
    uploader_tenant_id: Optional[str] = None,
) -> str:
    """Map caller context to the MinIO object prefix used for uploads.

    Resolution order (first match wins):
    1. Asset-owner tenant → ``attachments/asset_owner/{user_id}``
    2. ``folder == "knowledge_base"`` → shared ``knowledge_base`` prefix
    3. Otherwise → per-user ``attachments/{user_id}`` when ``user_id`` is set
    4. Legacy fallback → ``folder`` if provided, else ``attachments``

    Access control for reads is enforced separately; this function only
    chooses the storage prefix.

    Args:
        folder: Requested folder hint (e.g. ``"knowledge_base"`` or a legacy path).
        user_id: Uploader user ID; required for user-scoped attachment paths.
        uploader_tenant_id: Uploader tenant ID; asset-owner tenants use a dedicated prefix.

    Returns:
        Resolved MinIO folder prefix (no leading or trailing slash).
    """
    if uploader_tenant_id == ASSET_OWNER_TENANT_ID:
        return f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/{user_id}"

    if folder == "knowledge_base":
        return "knowledge_base"

    if user_id:
        return f"attachments/{user_id}"

    return folder or "attachments"


def check_file_access(
    object_name: str,
    user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
) -> bool:
    """
    Check if user has permission to access the file.

    Access rules:
    - knowledge_base/*: All authenticated users can access
    - attachments/{user_id}/*: Only the owner (user_id) can access
    - images_in_attachments/*: All authenticated users can access
    - preview/*: Accessible if the original file is accessible

    Args:
        object_name: File object name in storage
        user_id: Current user ID

    Returns:
        True if access is allowed, False otherwise
    """
    if not user_id:
        return False

    if object_name.startswith(ASSET_OWNER_ATTACHMENTS_PREFIX):
        return caller_tenant_id == ASSET_OWNER_TENANT_ID

    if object_name.startswith("knowledge_base/"):
        # Knowledge base files: all authenticated users can access
        return True

    if object_name.startswith("images_in_attachments/"):
        # Extracted image files used by knowledge-base image chunks.
        # Keep them readable for authenticated users to avoid broken image citations.
        return True

    # Check if file is in user's attachments folder
    # Pattern: attachments/{user_id}/*
    if object_name.startswith(f"attachments/{user_id}/"):
        return True

    # For backward compatibility, allow access to files in root attachments folder
    # Pattern: attachments/{filename} (no user_id subfolder)
    if object_name.startswith("attachments/") and "/" not in object_name.replace("attachments/", "", 1):
        # Old format: attachments/filename (no subdirectory)
        # Allow access for backward compatibility
        return True

    return False


def check_file_access_batch(
    object_names: List[str],
    user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
) -> Dict[str, bool]:
    """
    Batch check file access permissions.

    Args:
        object_names: List of file object names
        user_id: Current user ID
        caller_tenant_id: Caller's tenant ID for ASSET_OWNER path checks

    Returns:
        Dict mapping object_name to access permission (True/False)
    """
    return {
        obj_name: check_file_access(obj_name, user_id, caller_tenant_id)
        for obj_name in object_names
    }


def validate_s3_url_access(
    object_name: str,
    user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
) -> None:
    """
    Validate if user has permission to access the S3 URL.

    Args:
        object_name: File object name in storage (extracted from S3 URL)
        user_id: Current user ID

    Raises:
        PermissionError: If user doesn't have permission to access the file
    """
    if not user_id:
        raise PermissionError("User authentication required to access files")

    if not check_file_access(object_name, user_id, caller_tenant_id):
        logger.warning(
            f"[validate_s3_url_access] Access denied: object_name={object_name}, user_id={user_id}")
        raise PermissionError(
            f"Access denied: You don't have permission to access this file ({object_name})")


def validate_urls_access(
    urls: List[str],
    user_id: Optional[str],
    caller_tenant_id: Optional[str] = None,
) -> None:
    """
    Validate if user has permission to access the given URLs.

    Supports S3 URLs (s3://bucket/key or /bucket/key format).

    Args:
        urls: List of URLs to validate (S3, HTTP, or HTTPS)
        user_id: Current user ID

    Raises:
        PermissionError: If user doesn't have permission to access any of the files
    """
    if not urls:
        return

    for url in urls:
        if not url:
            continue

        # Only validate S3 URLs (MinIO storage)
        # HTTP/HTTPS URLs are external resources and are not subject to MinIO access control
        if url.startswith("s3://"):
            try:
                _, object_name = parse_s3_url(url)
                validate_s3_url_access(object_name, user_id, caller_tenant_id)
            except ValueError as e:
                logger.warning(
                    f"[validate_urls_access] Failed to parse S3 URL: {url}, error: {e}")
                raise PermissionError(f"Invalid S3 URL format: {url}")
        elif url.startswith("/") and not url.startswith("//"):
            # Handle /bucket/key format (absolute path style)
            parts = url.strip("/").split("/", 1)
            if len(parts) == 2:
                bucket, object_name = parts
                validate_s3_url_access(object_name, user_id, caller_tenant_id)


async def upload_files_impl(
    destination: str,
    file: List[UploadFile],
    folder: str = None,
    index_name: Optional[str] = None,
    user_id: Optional[str] = None,
    uploader_tenant_id: Optional[str] = None,
) -> tuple:
    """
    Upload files to local storage or MinIO based on destination.

    Args:
        destination: "local" or "minio"
        file: List of UploadFile objects
        folder: Folder name for MinIO uploads
        index_name: Knowledge base index for conflict resolution
        user_id: User ID for attachment path isolation
        uploader_tenant_id: Uploader tenant ID (ASSET_OWNER uses dedicated prefix)

    Returns:
        tuple: (errors, uploaded_file_paths, uploaded_filenames)
    """
    uploaded_filenames = []
    uploaded_file_paths = []
    errors = []
    if destination == "local":
        async with upload_semaphore:
            for f in file:
                if not f:
                    continue

                safe_filename = os.path.basename(f.filename or "")
                upload_path = upload_dir / safe_filename
                absolute_path = upload_path.absolute()

                # Save file
                if await save_upload_file(f, upload_path):
                    uploaded_filenames.append(safe_filename)
                    uploaded_file_paths.append(str(absolute_path))
                    logger.info(f"Successfully saved file: {safe_filename}")
                else:
                    errors.append(f"Failed to save file: {f.filename}")

    elif destination == "minio":
        actual_folder = resolve_minio_upload_folder(
            folder, user_id, uploader_tenant_id)
        minio_results = await upload_to_minio(files=file, folder=actual_folder)
        for result in minio_results:
            if result.get("success"):
                uploaded_filenames.append(result.get("file_name"))
                uploaded_file_paths.append(result.get("object_name"))
            else:
                file_name = result.get('file_name')
                error_msg = result.get('error', 'Unknown error')
                errors.append(f"Failed to upload {file_name}: {error_msg}")

        # Resolve filename conflicts against existing KB documents by renaming (e.g., name -> name_1)
        if index_name:
            try:
                vdb_core = get_vector_db_core()
                existing = await ElasticSearchService.list_files(index_name, include_chunks=False, vdb_core=vdb_core)
                existing_files = existing.get(
                    "files", []) if isinstance(existing, dict) else []
                # Prefer 'file' field; fall back to 'filename' if present
                existing_names = set()
                for item in existing_files:
                    name = (item.get("file") or item.get(
                        "filename") or "").strip()
                    if name:
                        existing_names.add(name.lower())

                def make_unique_names(original_names: List[str], taken_lower: set) -> List[str]:
                    unique_list: List[str] = []
                    local_taken = set(taken_lower)
                    for original in original_names:
                        base, ext = os.path.splitext(original or "")
                        candidate = original or ""
                        if not candidate:
                            unique_list.append(candidate)
                            continue
                        suffix = 1
                        # Ensure case-insensitive uniqueness
                        while candidate.lower() in local_taken:
                            candidate = f"{base}_{suffix}{ext}"
                            suffix += 1
                        unique_list.append(candidate)
                        local_taken.add(candidate.lower())
                    return unique_list

                uploaded_filenames[:] = make_unique_names(
                    uploaded_filenames, existing_names)
            except Exception as e:
                logger.warning(
                    f"Failed to resolve filename conflicts for index '{index_name}': {str(e)}")
    else:
        raise Exception("Invalid destination. Must be 'local' or 'minio'.")
    return errors, uploaded_file_paths, uploaded_filenames


async def upload_to_minio(
    files: List[UploadFile],
    folder: str,
    user_id: Optional[str] = None,
    uploader_tenant_id: Optional[str] = None,
) -> List[dict]:
    """
    Helper function to upload files to MinIO and return results.

    Args:
        files: List of files to upload
        folder: Storage folder path or resolved MinIO prefix
        user_id: User ID for attachment path isolation when folder is generic
        uploader_tenant_id: Uploader tenant ID for ASSET_OWNER attachment prefix

    Returns:
        List of upload results
    """
    actual_folder = resolve_minio_upload_folder(
        folder, user_id, uploader_tenant_id)
    results = []
    for f in files:
        try:
            # Read file content
            file_content = await f.read()

            # Convert file content to BytesIO object
            file_obj = BytesIO(file_content)

            # Upload file
            result = upload_fileobj(
                file_obj=file_obj,
                file_name=f.filename or "",
                prefix=actual_folder,
                file_size=len(file_content)
            )

            # Reset file pointer for potential re-reading
            await f.seek(0)
            results.append(result)

        except Exception as e:
            # Log single file upload failure but continue processing other files
            logger.error(
                f"Failed to upload file {f.filename}: {e}", exc_info=True)
            results.append({
                "success": False,
                "file_name": f.filename,
                "error": "An error occurred while processing the file."
            })
    return results


async def get_file_url_impl(object_name: str, expires: int):
    result = get_file_url(object_name=object_name, expires=expires)
    if not result["success"]:
        raise Exception(
            f"File does not exist or cannot be accessed: {result.get('error', 'Unknown error')}")
    return result


async def get_file_stream_impl(object_name: str):
    file_stream = get_file_stream(object_name=object_name)
    if file_stream is None:
        raise Exception("File not found or failed to read from storage")
    content_type = get_content_type(object_name)
    return file_stream, content_type


async def delete_file_impl(object_name: str):
    result = delete_file(object_name=object_name)
    if not result["success"]:
        raise Exception(
            f"File does not exist or deletion failed: {result.get('error', 'Unknown error')}")
    return result


async def list_files_impl(prefix: str, limit: Optional[int] = None):
    files = list_files(prefix=prefix)
    if limit:
        files = files[:limit]
    return files


def get_llm_model(tenant_id: str):
    # Get the tenant config
    main_model_config = tenant_config_manager.get_model_config(
        key=MODEL_CONFIG_MAPPING["llm"], tenant_id=tenant_id)
    timeout_seconds = main_model_config.get(
        "timeout_seconds") if main_model_config else None
    long_text_to_text_model = OpenAILongContextModel(
        observer=MessageObserver(),
        model_id=get_model_name_from_config(main_model_config),
        api_base=main_model_config.get("base_url"),
        api_key=main_model_config.get("api_key"),
        max_context_tokens=main_model_config.get("max_tokens"),
        ssl_verify=main_model_config.get("ssl_verify", True),
        timeout_seconds=timeout_seconds,
    )
    return long_text_to_text_model


async def resolve_preview_file(object_name: str) -> Tuple[str, str, int]:
    """
    Resolve the actual object name, content type, and total size for preview.

    Args:
        object_name: File object name in storage

    Returns:
        Tuple[str, str, int]: (actual_object_name, content_type, total_size)
    """
    if not file_exists(object_name):
        raise NotFoundException(f"File not found: {object_name}")

    file_size = get_file_size_from_minio(object_name)
    if file_size > FILE_PREVIEW_SIZE_LIMIT:
        raise FileTooLargeException(
            f"File size {file_size} bytes exceeds the {FILE_PREVIEW_SIZE_LIMIT // (1024 * 1024)} MB preview limit"
        )

    content_type = get_content_type(object_name)

    # PDF, images, and text files - return directly
    if content_type == 'application/pdf' or content_type.startswith('image/') or content_type in ['text/plain', 'text/csv', 'text/markdown']:
        return object_name, content_type, file_size

    # Office documents - convert to PDF with caching
    elif content_type in OFFICE_MIME_TYPES:
        name_without_ext = object_name.rsplit(
            '.', 1)[0] if '.' in object_name else object_name
        hash_suffix = hashlib.md5(object_name.encode()).hexdigest()[:8]
        pdf_object_name = f"preview/converted/{name_without_ext}_{hash_suffix}.pdf"
        temp_pdf_object_name = f"preview/converting/{name_without_ext}_{hash_suffix}.pdf.tmp"

        # Trigger conversion if cache is missing or corrupted
        if not _is_pdf_cache_valid(pdf_object_name):
            await _convert_office_to_cached_pdf(object_name, pdf_object_name, temp_pdf_object_name)

        pdf_size = get_file_size_from_minio(pdf_object_name)
        return pdf_object_name, 'application/pdf', pdf_size

    # Unsupported file type
    else:
        raise UnsupportedFileTypeException(
            f"Unsupported file type for preview: {content_type}")


def get_preview_stream(actual_object_name: str, start: Optional[int] = None, end: Optional[int] = None):
    """
    Fetch a preview stream for the given object, optionally limited to a byte range.

    Args:
        actual_object_name: Resolved object name (after Office conversion if needed)
        start: Start byte offset (inclusive). Must be provided together with end.
        end: End byte offset (inclusive), matching HTTP Range semantics.

    Returns:
        Raw boto3 Body stream
    """
    if (start is None) != (end is None):
        raise ValueError("start and end must be provided together")

    if start is None:
        stream = get_file_stream_raw(actual_object_name)
    else:
        stream = get_file_range(actual_object_name, start, end)

    if stream is None:
        raise NotFoundException(
            "File not found or failed to read from storage")
    return stream


def _is_pdf_cache_valid(pdf_object_name: str) -> bool:
    """
    Check whether a cached PDF exists and is readable.
    """
    if not file_exists(pdf_object_name):
        return False

    # Verify the cached file is readable by fetching a small range
    stream = get_file_range(pdf_object_name, 0, 0)
    if stream is None:
        logger.warning(
            f"Corrupted cache detected (cannot read), deleting: {pdf_object_name}")
        delete_file(pdf_object_name)
        return False

    close_fn = getattr(stream, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception as e:
            logger.warning(
                f"Failed to close cache probe stream for {pdf_object_name}: {str(e)}")

    return True


async def _convert_office_to_cached_pdf(
    object_name: str,
    pdf_object_name: str,
    temp_pdf_object_name: str,
) -> None:
    """
    Convert an Office document to PDF and store the result in MinIO.

    Args:
        object_name: Source Office file path in MinIO
        pdf_object_name: Final cached PDF path in MinIO
        temp_pdf_object_name: Temporary PDF path used during conversion
    """
    # Get or create a lock for this specific file to prevent duplicate conversions
    async with _conversion_locks_guard:
        if object_name not in _conversion_locks:
            _conversion_locks[object_name] = asyncio.Lock()
        file_lock = _conversion_locks[object_name]

    try:
        async with file_lock:
            # Double-check: another request may have completed the conversion while we waited
            if _is_pdf_cache_valid(pdf_object_name):
                return

            # Conversion semaphore is enforced inside the data-process service
            try:
                # Request conversion: data-process downloads, converts, uploads to temp path, validates
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{DATA_PROCESS_SERVICE}/tasks/convert_to_pdf",
                        data={
                            "object_name": object_name,
                            "pdf_object_name": temp_pdf_object_name,
                        },
                    )
                if response.status_code != 200:
                    logger.error(
                        "Office conversion failed with non-200 response: object=%s, status=%s, body=%s",
                        object_name,
                        response.status_code,
                        response.text,
                    )
                    raise RuntimeError(
                        f"Conversion service returned status {response.status_code}"
                    )

                # Atomic move from temp to final location, then clean up temp
                copy_result = copy_file(
                    source_object=temp_pdf_object_name, dest_object=pdf_object_name)
                if not copy_result.get('success'):
                    logger.error(
                        "Failed to finalize converted PDF cache: object=%s, temp=%s, dest=%s, error=%s",
                        object_name,
                        temp_pdf_object_name,
                        pdf_object_name,
                        copy_result.get('error', 'Unknown error'),
                    )
                    raise RuntimeError(
                        "Failed to finalize converted PDF cache")
                delete_file(temp_pdf_object_name)

            except Exception as e:
                if file_exists(temp_pdf_object_name):
                    delete_file(temp_pdf_object_name)
                logger.error(f"Office conversion failed: {str(e)}")
                if isinstance(e, OfficeConversionException):
                    raise
                raise OfficeConversionException(
                    "Office file conversion failed") from e
    finally:
        # Clean up the file lock (prevents memory leak for many unique files)
        async with _conversion_locks_guard:
            _conversion_locks.pop(object_name, None)
