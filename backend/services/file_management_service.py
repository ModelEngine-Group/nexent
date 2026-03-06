import asyncio
import hashlib
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from fastapi import UploadFile

from consts.const import (
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
    get_file_size_from_minio,
    get_file_stream,
    get_file_url,
    list_files,
    upload_fileobj,
)
from services.vectordatabase_service import ElasticSearchService, get_vector_db_core
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.file_management_utils import save_upload_file

from nexent import MessageObserver
from nexent.core.models import OpenAILongContextModel

# Create upload directory
upload_dir = Path(UPLOAD_FOLDER)
upload_dir.mkdir(exist_ok=True)
upload_semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

# Per-file locks prevent duplicate conversions of the same file
_conversion_locks: dict[str, asyncio.Lock] = {}
_conversion_locks_guard = asyncio.Lock()

logger = logging.getLogger("file_management_service")


async def upload_files_impl(destination: str, file: List[UploadFile], folder: str = None, index_name: Optional[str] = None) -> tuple:
    """
    Upload files to local storage or MinIO based on destination.

    Args:
        destination: "local" or "minio"
        file: List of UploadFile objects
        folder: Folder name for MinIO uploads

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
        minio_results = await upload_to_minio(files=file, folder=folder)
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


async def upload_to_minio(files: List[UploadFile], folder: str) -> List[dict]:
    """Helper function to upload files to MinIO and return results."""
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
                prefix=folder
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
    long_text_to_text_model = OpenAILongContextModel(
        observer=MessageObserver(),
        model_id=get_model_name_from_config(main_model_config),
        api_base=main_model_config.get("base_url"),
        api_key=main_model_config.get("api_key"),
        max_context_tokens=main_model_config.get("max_tokens"),
        ssl_verify=main_model_config.get("ssl_verify", True),
    )
    return long_text_to_text_model


async def preview_file_impl(object_name: str) -> Tuple[BytesIO, str]:
    """
    Preview a file by returning its contents as a stream.

    Args:
        object_name: File object name in storage

    Returns:
        Tuple[BytesIO, str]: (file_stream, content_type)
    """
    file_size = get_file_size_from_minio(object_name)
    if file_size > FILE_PREVIEW_SIZE_LIMIT:
        raise FileTooLargeException(
            f"File size {file_size} bytes exceeds the {FILE_PREVIEW_SIZE_LIMIT // (1024 * 1024)} MB preview limit"
        )

    content_type = get_content_type(object_name)

    # PDF, images, and text files - return directly
    if content_type == 'application/pdf' or content_type.startswith('image/') or content_type in ['text/plain', 'text/csv', 'text/markdown']:
        file_stream = get_file_stream(object_name)
        if file_stream is None:
            raise NotFoundException("File not found or failed to read from storage")
        return file_stream, content_type

    # Office documents - convert to PDF with caching
    elif content_type in OFFICE_MIME_TYPES:
        name_without_ext = object_name.rsplit('.', 1)[0] if '.' in object_name else object_name
        hash_suffix = hashlib.md5(object_name.encode()).hexdigest()[:8]
        pdf_object_name = f"preview/converted/{name_without_ext}_{hash_suffix}.pdf"
        temp_pdf_object_name = f"preview/converting/{name_without_ext}_{hash_suffix}.pdf.tmp"

        # Fast path: return from cache without acquiring any lock
        cached_stream = _get_cached_pdf_stream(pdf_object_name)
        if cached_stream is not None:
            return cached_stream, 'application/pdf'

        # Slow path: convert with locking
        file_stream = await _convert_office_to_cached_pdf(object_name, pdf_object_name, temp_pdf_object_name)
        return file_stream, 'application/pdf'

    # Unsupported file type
    else:
        raise UnsupportedFileTypeException(f"Unsupported file type for preview: {content_type}")


def _get_cached_pdf_stream(pdf_object_name: str) -> Optional[BytesIO]:
    """
    Return the cached PDF stream if available, or None if missing or corrupted.

    If the file exists but cannot be read, the corrupted entry is deleted so
    a subsequent call will trigger a fresh conversion.
    """
    if file_exists(pdf_object_name):
        file_stream = get_file_stream(pdf_object_name)
        if file_stream is None:
            logger.warning(f"Corrupted cache detected (cannot read), deleting: {pdf_object_name}")
            delete_file(pdf_object_name)
            return None
        return file_stream
    return None


async def _convert_office_to_cached_pdf(
    object_name: str,
    pdf_object_name: str,
    temp_pdf_object_name: str,
) -> BytesIO:
    """
    Convert an Office document to PDF and store the result in MinIO.

    Args:
        object_name: Source Office file path in MinIO
        pdf_object_name: Final cached PDF path in MinIO
        temp_pdf_object_name: Temporary PDF path used during conversion

    Returns:
        BytesIO stream of the converted PDF
    """
    # Get or create a lock for this specific file to prevent duplicate conversions
    async with _conversion_locks_guard:
        if object_name not in _conversion_locks:
            _conversion_locks[object_name] = asyncio.Lock()
        file_lock = _conversion_locks[object_name]

    async with file_lock:
        # Double-check: another request may have completed the conversion while we waited
        cached_stream = _get_cached_pdf_stream(pdf_object_name)
        if cached_stream is not None:
            return cached_stream

        # Conversion semaphore is enforced inside the data-process service
        try:
            # Request conversion: data-process downloads, converts, uploads to temp path, validates
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{DATA_PROCESS_SERVICE}/tasks/convert_to_pdf",
                    data={
                        "object_name": object_name,
                        "pdf_object_name": temp_pdf_object_name,
                    },
                )
            if response.status_code != 200:
                raise Exception(
                    f"data-process conversion returned {response.status_code}: {response.text}"
                )

            # Atomic move from temp to final location, then clean up temp
            copy_result = copy_file(source_object=temp_pdf_object_name, dest_object=pdf_object_name)
            if not copy_result.get('success'):
                raise Exception(f"Failed to finalize PDF cache: {copy_result.get('error', 'Unknown error')}")
            delete_file(temp_pdf_object_name)

        except Exception as e:
            if file_exists(temp_pdf_object_name):
                delete_file(temp_pdf_object_name)
            logger.error(f"Office conversion failed: {str(e)}")
            raise OfficeConversionException(f"Failed to convert Office document to PDF: {str(e)}") from e
        finally:
            # Clean up the file lock (prevents memory leak for many unique files)
            async with _conversion_locks_guard:
                _conversion_locks.pop(object_name, None)

    file_stream = get_file_stream(pdf_object_name)
    if file_stream is None:
        raise NotFoundException("Converted PDF not found or failed to read from storage")
    return file_stream
