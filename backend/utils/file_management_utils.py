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
from database.attachment_db import get_file_size_from_minio

logger = logging.getLogger("file_management_utils")

def ensure_secure_libreoffice_profile_dir(profile_dir: str) -> Path:
    """Create the shared LibreOffice profile directory with owner-only permissions."""
    profile_path = Path(profile_dir).expanduser().resolve()
    profile_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(profile_path, 0o700)
    return profile_path


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


async def convert_office_to_pdf(input_path: str, output_dir: str, timeout: int = 30) -> str:
    """
    Convert Office document to PDF using LibreOffice.

    Args:
        input_path: Path to input Office file
        output_dir: Directory for output PDF file
        timeout: Conversion timeout in seconds (default: 30s)

    Returns:
        str: Path to generated PDF file
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    def _run_libreoffice_conversion():
        """Synchronous LibreOffice conversion to run in thread executor."""
        profile_uri = ensure_secure_libreoffice_profile_dir(
            LIBREOFFICE_PROFILE_DIR
        ).as_uri()
        cmd = [
            "soffice",
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--norestore",
            "--invisible",
            "--nolockcheck",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            input_path
        ]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

    try:
        # Run blocking subprocess in thread executor to avoid blocking event loop
        result = await run_blocking(
            "libreoffice-conversion",
            _run_libreoffice_conversion,
            lane="control-io",
            owner="config",
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown conversion error"
            logger.error(f"LibreOffice conversion failed: {error_msg}")
            raise RuntimeError(f"Office to PDF conversion failed: {error_msg}")

        # Find generated PDF file
        input_filename = os.path.basename(input_path)
        pdf_filename = os.path.splitext(input_filename)[0] + '.pdf'
        pdf_path = os.path.join(output_dir, pdf_filename)

        if not os.path.exists(pdf_path):
            raise RuntimeError(f"Converted PDF not found: {pdf_path}")

        return pdf_path

    except subprocess.TimeoutExpired:
        logger.error(f"Office to PDF conversion timeout after {timeout}s: {input_path}")
        raise TimeoutError(f"Office to PDF conversion timeout (>{timeout}s)")

    except FileNotFoundError as e:
        # LibreOffice executable not found in PATH
        logger.error(f"LibreOffice not available: {str(e)}")
        raise FileNotFoundError(
            "LibreOffice is not installed or not available in PATH. "
        ) from e
