# Concurrency control
import asyncio
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from fastapi import UploadFile

from consts.const import UPLOAD_FOLDER, MAX_CONCURRENT_UPLOADS
from database.attachment_db import upload_fileobj, get_file_url, get_content_type, get_file_stream, delete_file, \
    list_files
from utils.file_management_utils import save_upload_file

# Create upload directory
upload_dir = Path(UPLOAD_FOLDER)
upload_dir.mkdir(exist_ok=True)
upload_semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

logger = logging.getLogger("file_management_service")


async def upload_files_impl(destination: str, file: List[UploadFile], folder: str = None) -> tuple:
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
