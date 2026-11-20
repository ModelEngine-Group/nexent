# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared file upload, source size and Office conversion utilities."""

import logging
import os
import subprocess

import requests
from contracts.constants.environment import LIBREOFFICE_PROFILE_DIR
from nexent.core.concurrency import run_blocking

from infrastructure.file_reads import read_attachment_size

logger = logging.getLogger("file_management_utils")



def get_file_size(source_type: str, path_or_url: str) -> int:
    """Query the actual size(bytes) of the file."""
    try:
        if source_type == "minio":
            return read_attachment_size(path_or_url)

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



from infrastructure.file_processing.conversion import (
    convert_office_to_pdf as _convert_office_to_pdf,
)
from infrastructure.file_processing.conversion import (
    ensure_secure_libreoffice_profile_dir,
)


async def convert_office_to_pdf(input_path: str, output_dir: str, timeout: int = 30) -> str:
    """Bind Management configuration to the infrastructure converter."""
    return await _convert_office_to_pdf(input_path, output_dir, timeout, profile_dir=LIBREOFFICE_PROFILE_DIR)
