# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import io
import os
import uuid
from datetime import datetime
from typing import Any, BinaryIO, Dict, Optional

from contracts import file_types
from contracts.constants.constants import S3_URL_PREFIX
from contracts.object_tickets import InvalidObjectTicket, issue_download_url
from nexent.storage.errors import StorageError

from infrastructure.attachment_upload import put_attachment
from infrastructure.object_storage.client import minio_client
from infrastructure.object_storage.read_access import (
    normalize_object_location,
)
from infrastructure.trace.knowledge import (
    set_span_attributes,
    trace_knowledge_operation,
)


def build_s3_url(object_name: str, bucket: Optional[str] = None) -> str:
    """
    Build an s3://bucket/key style URL from an object name (or passthrough if already s3://).
    """
    if not object_name:
        return ""

    if object_name.startswith(S3_URL_PREFIX):
        return object_name

    if object_name.startswith("/"):
        path = object_name.lstrip("/")
        parts = path.split("/", 1)
        if len(parts) == 2:
            return f"{S3_URL_PREFIX}{parts[0]}/{parts[1]}"
        return f"{S3_URL_PREFIX}{parts[0]}/"

    resolved_bucket = bucket or minio_client.default_bucket
    if resolved_bucket:
        return f"{S3_URL_PREFIX}{resolved_bucket}/{object_name}"
    return f"{S3_URL_PREFIX}{object_name}"


def generate_object_name(file_name: str, prefix: str = "attachments") -> str:
    """
    Generate a unique object name

    Args:
        file_name: Original file name
        prefix: Object name prefix

    Returns:
        str: Generated object name
    """
    # Get file extension
    _, ext = os.path.splitext(file_name)
    # Generate unique ID
    unique_id = uuid.uuid4().hex
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    # Combine object name
    return f"{prefix}/{timestamp}_{unique_id}{ext}"


def upload_file(
    file_path: str,
    object_name: Optional[str] = None,
    bucket: Optional[str] = None,
    generate_presigned_url: bool = True,
    presigned_url_expires: int = 86400,
) -> Dict[str, Any]:
    """
    Upload local file to MinIO

    Args:
        file_path: Local file path
        object_name: Object name, if not specified will be auto-generated
        bucket: Bucket name, if not specified will use default bucket
        generate_presigned_url: Whether to generate presigned URL for external access (default True)
        presigned_url_expires: Expiration time in seconds for presigned URL (default 86400 = 24 hours)

    Returns:
        Dict[str, Any]: Upload result, containing success flag, URL and error message (if any)
    """
    # If object name not specified, generate one
    if object_name is None:
        file_name = os.path.basename(file_path)
        object_name = generate_object_name(file_name)

    # Upload file
    success, result = minio_client.upload_file(file_path, object_name, bucket)

    # Build response
    response = {
        "success": success,
        "object_name": object_name,
        "file_name": os.path.basename(file_path),
        "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        "content_type": file_types.get_content_type(file_path),
        "upload_time": datetime.now().isoformat(),
    }

    if success:
        response["url"] = result
        # Generate presigned URL for external access if requested
        if generate_presigned_url:
            try:
                response["presigned_url"] = issue_download_url(object_name, presigned_url_expires, bucket=bucket)
            except InvalidObjectTicket:
                pass
    else:
        response["error"] = result

    return response


@trace_knowledge_operation("knowledge.minio.upload", "minio.upload")
def upload_fileobj(
    file_obj: BinaryIO,
    file_name: str,
    bucket: Optional[str] = None,
    prefix: str = "attachments",
    generate_presigned_url: bool = True,
    presigned_url_expires: int = 86400,
    file_size: Optional[int] = None,
    object_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Upload file object to MinIO

    Args:
        file_obj: File object
        file_name: File name
        bucket: Bucket name, if not specified will use default bucket
        prefix: Object name prefix, default is "attachments"
        generate_presigned_url: Whether to generate presigned URL for external access (default True)
        presigned_url_expires: Expiration time in seconds for presigned URL (default 86400 = 24 hours)
        file_size: Pre-calculated file size in bytes. If not provided, will be calculated internally.

    Returns:
        Dict[str, Any]: Upload result, containing success flag, URL and error message (if any)
    """
    # Generate object name when the caller did not pre-allocate one.
    object_name = object_name or generate_object_name(file_name, prefix=prefix)

    # Calculate file size if not provided
    if file_size is None:
        try:
            current_pos = file_obj.tell()
            file_obj.seek(0, os.SEEK_END)
            file_size = file_obj.tell()
            file_obj.seek(0)  # Seek to beginning for upload
        except (ValueError, IOError):
            file_size = 0
            file_obj.seek(0)  # Try to seek to beginning anyway

    # Upload file
    content_type = file_types.get_content_type(file_name)
    try:
        result = put_attachment(file_obj, object_name, bucket, content_type="application/octet-stream", size=file_size)
        success = True
    except StorageError as error:
        success, result = False, str(error)
    set_span_attributes(file_size_bytes=file_size, stage="minio.upload")

    # Restore original position (if file is still open)
    try:
        file_obj.seek(0)
    except (ValueError, IOError):
        pass  # File is closed, ignore

    # Build response
    response = {
        "success": success,
        "object_name": object_name,
        "file_name": file_name,
        "file_size": file_size,
        "content_type": content_type,
        "upload_time": datetime.now().isoformat(),
    }

    if success:
        response["url"] = result
        # Generate presigned URL for external access if requested
        if generate_presigned_url:
            try:
                response["presigned_url"] = issue_download_url(object_name, presigned_url_expires, bucket=bucket)
            except InvalidObjectTicket:
                pass
    else:
        response["error"] = result

    return response


def download_file(object_name: str, file_path: str, bucket: Optional[str] = None) -> Dict[str, Any]:
    """
    Download file from MinIO to local

    Args:
        object_name: Object name
        file_path: Local save path
        bucket: Bucket name, if not specified will use default bucket

    Returns:
        Dict[str, Any]: Download result, containing success flag and error message (if any)
    """
    # Download file
    success, result = minio_client.download_file(object_name, file_path, bucket)

    # Build response
    response = {"success": success, "object_name": object_name, "file_path": file_path}

    if not success:
        response["error"] = result

    return response


def file_exists(object_name: str, bucket: Optional[str] = None) -> bool:
    """
    Check if a file exists in the bucket.

    Args:
        object_name: Object name in storage
        bucket: Bucket name, if not specified will use default bucket

    Returns:
        bool: True if file exists, False otherwise
    """
    try:
        object_name, bucket = normalize_object_location(object_name, bucket)
        return minio_client.file_exists(object_name, bucket)
    except Exception:
        return False


def delete_file(object_name: str, bucket: Optional[str] = None) -> Dict[str, Any]:
    """
    Delete file

    Args:
        object_name: Object name
        bucket: Bucket name, if not specified will use default bucket

    Returns:
        Dict[str, Any]: Delete result, containing success flag and error message (if any)
    """
    object_name, bucket = normalize_object_location(object_name, bucket)
    if not bucket:
        minio_client._ensure_initialized()
        bucket = minio_client.storage_config.default_bucket
    success, result = minio_client.delete_file(object_name, bucket)

    response = {"success": success, "object_name": object_name}

    if not success:
        response["error"] = result

    return response


def get_file_stream(object_name: str, bucket: Optional[str] = None) -> Optional[BinaryIO]:
    """
    Get file binary stream from MinIO storage

    Args:
        object_name: Object name in MinIO
        bucket: Bucket name, if not specified use default bucket

    Returns:
        Optional[BinaryIO]: Standard BinaryIO stream object, or None if failed
    """
    object_name, bucket = normalize_object_location(object_name, bucket)
    success, result = minio_client.get_file_stream(object_name, bucket)
    if not success:
        return None

    # Read all data from StreamingBody and wrap it in BytesIO for BinaryIO compatibility
    try:
        binary_data = result.read()
        result.close()  # Close the original stream
        return io.BytesIO(binary_data)
    except Exception:
        return None
