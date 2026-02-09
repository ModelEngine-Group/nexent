import io
import os
import uuid
from datetime import datetime
from typing import Any, BinaryIO, Dict, List, Optional

from .client import minio_client


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


def upload_file(file_path: str, object_name: Optional[str] = None, bucket: Optional[str] = None) -> Dict[str, Any]:
    """
    Upload local file to MinIO

    Args:
        file_path: Local file path
        object_name: Object name, if not specified will be auto-generated
        bucket: Bucket name, if not specified will use default bucket

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
    response = {"success": success, "object_name": object_name, "file_name": os.path.basename(file_path),
                "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                "content_type": get_content_type(file_path), "upload_time": datetime.now().isoformat()}

    if success:
        response["url"] = result
    else:
        response["error"] = result

    return response


def upload_fileobj(
        file_obj: BinaryIO,
        file_name: str,
        bucket: Optional[str] = None,
        prefix: str = "attachments"
) -> Dict[str, Any]:
    """
    Upload file object to MinIO

    Args:
        file_obj: File object
        file_name: File name
        bucket: Bucket name, if not specified will use default bucket
        prefix: Object name prefix, default is "attachments"

    Returns:
        Dict[str, Any]: Upload result, containing success flag, URL and error message (if any)
    """
    # Generate object name
    object_name = generate_object_name(file_name, prefix=prefix)

    # Get current position
    current_pos = file_obj.tell()

    # Calculate file size
    file_obj.seek(0, os.SEEK_END)
    file_size = file_obj.tell()

    # Reset to original position
    file_obj.seek(current_pos)

    # Upload file
    success, result = minio_client.upload_fileobj(
        file_obj, object_name, bucket)

    # Build response
    response = {"success": success, "object_name": object_name, "file_name": file_name, "file_size": file_size,
                "content_type": get_content_type(file_name), "upload_time": datetime.now().isoformat()}

    if success:
        response["url"] = result
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
    success, result = minio_client.download_file(
        object_name, file_path, bucket)

    # Build response
    response = {"success": success,
                "object_name": object_name, "file_path": file_path}

    if not success:
        response["error"] = result

    return response


def get_file_url(object_name: str, bucket: Optional[str] = None, expires: int = 3600) -> Dict[str, Any]:
    """
    Get presigned URL for file

    Args:
        object_name: Object name
        bucket: Bucket name, if not specified will use default bucket
        expires: URL expiration time in seconds

    Returns:
        Dict[str, Any]: Result containing success flag, URL and error message (if any)
    """
    # Get presigned URL
    success, result = minio_client.get_file_url(object_name, bucket, expires)

    # Build response
    response = {"success": success,
                "object_name": object_name, "expires_in": expires}

    if success:
        response["url"] = result
    else:
        response["error"] = result

    return response


def get_file_size(object_name: str, bucket: Optional[str] = None) -> int:
    """
    Get file size by object name
    """
    bucket = bucket or minio_client.storage_config.default_bucket
    return minio_client.get_file_size(object_name, bucket)


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
        return minio_client.file_exists(object_name, bucket)
    except Exception:
        return False


def copy_file(source_object: str, dest_object: str, bucket: Optional[str] = None) -> Dict[str, Any]:
    """
    Copy a file within the same bucket (atomic operation in MinIO).
    
    Args:
        source_object: Source object name
        dest_object: Destination object name
        bucket: Bucket name, if not specified will use default bucket
        
    Returns:
        Dict[str, Any]: Result containing success flag and error message (if any)
    """
    success, result = minio_client.copy_file(source_object, dest_object, bucket)
    if success:
        return {"success": True, "object_name": result}
    else:
        return {"success": False, "error": result}


def list_files(prefix: str = "", bucket: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List files in bucket

    Args:
        prefix: Prefix filter
        bucket: Bucket name, if not specified will use default bucket

    Returns:
        List[Dict[str, Any]]: List of file information
    """
    # Get file list
    files = minio_client.list_files(prefix, bucket)

    # Enhance file information
    for file in files:
        file["content_type"] = get_content_type(file["key"])

        # Get presigned URL (valid for 1 hour)
        success, url = minio_client.get_file_url(file["key"], bucket, 3600)
        if success:
            file["url"] = url

    return files


def delete_file(object_name: str, bucket: Optional[str] = None) -> Dict[str, Any]:
    """
    Delete file

    Args:
        object_name: Object name
        bucket: Bucket name, if not specified will use default bucket

    Returns:
        Dict[str, Any]: Delete result, containing success flag and error message (if any)
    """
    if not bucket:
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


def get_content_type(file_path: str) -> str:
    """
    Get content type based on file extension

    Args:
        file_path: File path or name

    Returns:
        str: Content type
    """
    # File extension to MIME type mapping
    mime_types = {'.jpg': 'image/jpeg',
                  '.jpeg': 'image/jpeg',
                  '.png': 'image/png',
                  '.gif': 'image/gif',
                  '.bmp': 'image/bmp',
                  '.webp': 'image/webp',
                  '.svg': 'image/svg+xml',
                  '.pdf': 'application/pdf',
                  '.doc': 'application/msword',
                  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                  '.xls': 'application/vnd.ms-excel',
                  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                  '.ppt': 'application/vnd.ms-powerpoint',
                  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                  '.txt': 'text/plain',
                  '.csv': 'text/csv',
                  '.md': 'text/markdown',
                  '.html': 'text/html',
                  '.htm': 'text/html',
                  '.json': 'application/json',
                  '.xml': 'application/xml',
                  '.zip': 'application/zip',
                  '.rar': 'application/x-rar-compressed',
                  '.tar': 'application/x-tar',
                  '.gz': 'application/gzip',
                  '.mp3': 'audio/mpeg',
                  '.mp4': 'video/mp4',
                  '.avi': 'video/x-msvideo',
                  '.mov': 'video/quicktime',
                  '.wmv': 'video/x-ms-wmv'}

    # Get file extension
    _, ext = os.path.splitext(file_path.lower())

    # Return corresponding MIME type, if no match return generic binary type
    return mime_types.get(ext, 'application/octet-stream')
