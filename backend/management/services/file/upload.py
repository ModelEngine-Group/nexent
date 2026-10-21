# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared file upload, source size and Office conversion utilities."""

import logging
import os
import subprocess
from pathlib import Path
import aiofiles
import requests
from fastapi import UploadFile
from nexent.core.concurrency import run_blocking
from consts.const import LIBREOFFICE_PROFILE_DIR
from management.db.file.attachment import get_file_size_from_minio

logger = logging.getLogger("file_management_utils")



async def save_upload_file(file: UploadFile, upload_path: Path) -> bool:
    try:
        async with aiofiles.open(upload_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
        return True
    except Exception as e:
        logger.error(f"Error saving file {file.filename}: {str(e)}")
        return False


def get_file_size(source_type: str, path_or_url: str) -> int:
    """Query the actual size(bytes) of the file."""
    try:
        if source_type == "minio":
            return get_file_size_from_minio(path_or_url)

        elif source_type == "local":
            # For local files, use os.path.getsize to get file size
            if os.path.exists(path_or_url):
                return os.path.getsize(path_or_url)
            else:
                logging.warning(f"File not found at local path: {path_or_url}")
                return 0
        else:
            raise NotImplementedError(f"Unexpected source type: {source_type}")

    except requests.exceptions.RequestException as e:
        logging.error(f"Network error getting file size for URL {path_or_url}: {str(e)}")
        return 0
    except Exception as e:
        logging.error(f"Error getting file size for {path_or_url}: {str(e)}")
        return 0



from data_process.services.conversion import (
    ensure_secure_libreoffice_profile_dir,
    convert_office_to_pdf,
)
