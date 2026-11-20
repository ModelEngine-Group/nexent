# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Stable extension-based file types shared without storage initialization."""

import os


def get_content_type(file_path: str) -> str:
    """
    Get content type based on file extension

    Args:
        file_path: File path or name

    Returns:
        str: Content type
    """
    # File extension to MIME type mapping
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".json": "application/json",
        ".epub": "application/epub",
        ".xml": "application/xml",
        ".zip": "application/zip",
        ".rar": "application/x-rar-compressed",
        ".tar": "application/x-tar",
        ".gz": "application/gzip",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".wmv": "video/x-ms-wmv",
    }

    # Get file extension
    _, ext = os.path.splitext(file_path.lower())

    # Return corresponding MIME type, if no match return generic binary type
    return mime_types.get(ext, "application/octet-stream")
