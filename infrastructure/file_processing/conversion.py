# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


import logging
import os
import subprocess
from pathlib import Path

from nexent.core.concurrency import run_blocking

from infrastructure.file_processing.process import run_conversion_process

logger = logging.getLogger("management.services.file.upload")


def ensure_secure_libreoffice_profile_dir(profile_dir: str) -> Path:
    """Create the shared LibreOffice profile directory with owner-only permissions."""
    profile_path = Path(profile_dir).expanduser().resolve()
    profile_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(profile_path, 0o700)
    return profile_path


def convert_office_to_pdf_sync(
    input_path: str,
    output_dir: str,
    timeout: int = 30,
    *,
    profile_dir: str,
    cancelled=None,
) -> str:
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
        profile_uri = ensure_secure_libreoffice_profile_dir(profile_dir).as_uri()
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
            "--convert-to",
            "pdf",
            "--outdir",
            output_dir,
            input_path,
        ]
        return run_conversion_process(cmd, timeout=timeout, cancelled=cancelled)

    try:
        result = _run_libreoffice_conversion()

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown conversion error"
            logger.error(f"LibreOffice conversion failed: {error_msg}")
            raise RuntimeError(f"Office to PDF conversion failed: {error_msg}")

        # Find generated PDF file
        input_filename = os.path.basename(input_path)
        pdf_filename = os.path.splitext(input_filename)[0] + ".pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)

        if not os.path.exists(pdf_path):
            raise RuntimeError(f"Converted PDF not found: {pdf_path}")

        return pdf_path

    except subprocess.TimeoutExpired:
        logger.error(f"Office to PDF conversion timeout after {timeout}s: {input_path}")
        raise TimeoutError(f"Office to PDF conversion timeout (>{timeout}s)")

    except FileNotFoundError as e:
        # LibreOffice executable not found in PATH
        logger.error(f"LibreOffice not available: {e!s}")
        raise FileNotFoundError(
            "LibreOffice is not installed or not available in PATH. "
        ) from e


async def convert_office_to_pdf(
    input_path: str, output_dir: str, timeout: int = 30, *, profile_dir: str
) -> str:
    """Run the same converter through the service-owned blocking lane."""
    return await run_blocking(
        "libreoffice-conversion",
        convert_office_to_pdf_sync,
        input_path,
        output_dir,
        timeout,
        profile_dir=profile_dir,
        lane="control-io",
        owner="config",
    )
