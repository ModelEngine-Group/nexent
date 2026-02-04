import asyncio
import logging
import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import UploadFile

from consts.const import UPLOAD_FOLDER, MAX_CONCURRENT_UPLOADS, MODEL_CONFIG_MAPPING
from database.attachment_db import (
    upload_file,
    upload_fileobj,
    get_file_url,
    get_content_type,
    get_file_stream,
    delete_file,
    list_files
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
    # Get MIME type directly
    content_type = get_content_type(object_name)
    
    # PDF, images, and text files - return directly
    if content_type == 'application/pdf' or content_type.startswith('image/') or content_type in ['text/plain', 'text/csv', 'text/markdown']:
        return await get_file_stream_impl(object_name)
    
    # Office documents - convert to PDF with caching
    elif 'officedocument' in content_type or 'msword' in content_type or 'ms-excel' in content_type or 'ms-powerpoint' in content_type:
        
        # Generate deterministic PDF path for caching
        safe_name = object_name.replace('/', '_').replace('\\', '_')
        name_without_ext = safe_name.rsplit('.', 1)[0] if '.' in safe_name else safe_name
        pdf_object_name = f"converted/temp_{name_without_ext}.pdf"
        
        # Check if converted PDF already exists in MinIO
        try:
            pdf_stream, pdf_content_type = await get_file_stream_impl(pdf_object_name)
            return pdf_stream, pdf_content_type
        except Exception:
            pass  # Cache miss, will convert
        
        # Convert Office to PDF
        temp_dir = None
        try:
            # Create temporary directory for conversion
            temp_dir = tempfile.mkdtemp(prefix='office_convert_')
            
            # Download original file from MinIO
            original_stream, _ = await get_file_stream_impl(object_name)
            original_filename = os.path.basename(object_name)
            input_path = os.path.join(temp_dir, original_filename)
            
            # Write to temporary file
            with open(input_path, 'wb') as f:
                f.write(original_stream.read())
            
            # Convert to PDF using LibreOffice
            pdf_path = await convert_office_to_pdf(input_path, temp_dir, timeout=30)
            
            # Upload converted PDF to MinIO
            result = upload_file(file_path=pdf_path, object_name=pdf_object_name)
            if not result.get('success'):
                raise Exception(f"Failed to upload converted PDF: {result.get('error', 'Unknown error')}")
            
        except Exception as e:
            logger.error(f"Office conversion failed: {str(e)}")
            raise Exception(f"Failed to convert Office document to PDF: {str(e)}")
        
        finally:
            # Clean up temporary directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    import shutil
                    shutil.rmtree(temp_dir)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp directory: {cleanup_error}")
        
        # Return converted PDF from MinIO (same path as cache hit)
        return await get_file_stream_impl(pdf_object_name)
    
    # Unsupported file type
    else:
        raise Exception(f"Unsupported file type for preview: {content_type}")


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

    # Run LibreOffice conversion
    # --headless: run without GUI
    # --convert-to pdf: output format
    # --outdir: output directory
    cmd = [
        'libreoffice',
        '--headless',
        '--convert-to', 'pdf',
        '--outdir', output_dir,
        input_path
    ]
    
    try:
        # Run conversion with timeout
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown conversion error"
            logger.error(f"LibreOffice conversion failed: {error_msg}")
            raise Exception(f"Office to PDF conversion failed: {error_msg}")
        
        # Find generated PDF file
        input_filename = os.path.basename(input_path)
        pdf_filename = os.path.splitext(input_filename)[0] + '.pdf'
        pdf_path = os.path.join(output_dir, pdf_filename)
        
        if not os.path.exists(pdf_path):
            raise Exception(f"Converted PDF not found: {pdf_path}")
        
        return pdf_path
        
    except subprocess.TimeoutExpired:
        logger.error(f"Office to PDF conversion timeout after {timeout}s: {input_path}")
        raise Exception(f"Office to PDF conversion timeout (>{timeout}s)")
    except Exception as e:
        logger.error(f"Office to PDF conversion error: {str(e)}")
        raise