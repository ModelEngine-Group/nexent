import asyncio
import logging
import os
import subprocess
import traceback
from pathlib import Path
from typing import List

import aiofiles
import httpx
import requests
from fastapi import UploadFile

from consts.const import DATA_PROCESS_SERVICE
from consts.model import ProcessParams
from database.attachment_db import get_file_size
from utils.auth_utils import get_current_user_id
from utils.config_utils import tenant_config_manager

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


async def trigger_data_process(files: List[dict], process_params: ProcessParams):
    """Trigger data processing service to handle uploaded files"""
    try:
        if not files:
            return None

        # Get chunking size according to the embedding model
        embedding_model_id = None
        tenant_id = None
        try:
            _, tenant_id = get_current_user_id(process_params.authorization)
            # Get embedding model ID from tenant config
            tenant_config = tenant_config_manager.load_config(tenant_id)
            embedding_model_id_str = tenant_config.get("EMBEDDING_ID") if tenant_config else None
            if embedding_model_id_str:
                embedding_model_id = int(embedding_model_id_str)
        except Exception as e:
            logger.warning(f"Failed to get embedding model ID for tenant: {e}")

        # Build headers with authorization
        headers = {
            "Authorization": f"Bearer {process_params.authorization}"
        }

        # Build source data list
        if len(files) == 1:
            # Single file request
            file_details = files[0]
            payload = {
                "source": file_details.get("path_or_url"),
                "source_type": process_params.source_type,
                "chunking_strategy": process_params.chunking_strategy,
                "index_name": process_params.index_name,
                "original_filename": file_details.get("filename"),
                "embedding_model_id": embedding_model_id,
                "tenant_id": tenant_id
            }

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(f"{DATA_PROCESS_SERVICE}/tasks", headers=headers, json=payload, timeout=30.0)

                if response.status_code == 201:
                    return response.json()
                else:
                    logger.error(
                        "Error from data process service: %s - %s", response,
                        response.text if hasattr(response, 'text') else 'No response text')
                    return {"status": "error", "code": response.status_code,
                        "message": f"Data process service error: {response.status_code}"}
            except httpx.RequestError as e:
                logger.error("Failed to connect to data process service: %s", str(e))
                return {"status": "error", "code": "CONNECTION_ERROR",
                    "message": f"Failed to connect to data process service: {str(e)}"}

        else:
            # Batch file request
            sources = []
            for file_details in files:
                source = {
                    "source": file_details.get("path_or_url"),
                    "source_type": process_params.source_type,
                    "chunking_strategy": process_params.chunking_strategy,
                    "index_name": process_params.index_name,
                    "original_filename": file_details.get("filename"),
                    "embedding_model_id": embedding_model_id,
                    "tenant_id": tenant_id
                }
                sources.append(source)

            payload = {"sources": sources}

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(f"{DATA_PROCESS_SERVICE}/tasks/batch", headers=headers, json=payload, timeout=30.0)

                if response.status_code == 201:
                    return response.json()
                else:
                    logger.error(
                        "Error from data process service: %s - %s", response,
                        response.text if hasattr(response, 'text') else 'No response text')
                    return {"status": "error", "code": response.status_code,
                        "message": f"Data process service error: {response.status_code}"}
            except httpx.RequestError as e:
                logger.error("Failed to connect to data process service: %s", str(e))
                return {"status": "error", "code": "CONNECTION_ERROR",
                    "message": f"Failed to connect to data process service: {str(e)}"}
    except Exception as e:
        logger.error("Error triggering data process: %s", str(e))
        return {"status": "error", "code": "INTERNAL_ERROR", "message": f"Internal error: {str(e)}"}


async def get_all_files_status(index_name: str):
    """
    Get status for all files according to index_name, matching corresponding tasks, 
    and then convert to custom state
    
    Args:
        index_name: Index name to filter tasks
        
    Returns:
        Dictionary with path_or_url as keys and dict values: {state, latest_task_id}
    """
    try:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{DATA_PROCESS_SERVICE}/tasks/indices/{index_name}", timeout=10.0)
            if response.status_code == 200:
                tasks_list = response.json()
            else:
                logger.error(f"Error from data process service: {response.status_code} - {response.text}")
                return {}
        except Exception as e:
            logger.error(f"Failed to connect to data process service: {str(e)}")
            return {}
        
        logging.debug(f"Found {len(tasks_list)} tasks for index '{index_name}'")
        if not tasks_list:
            logger.warning(f"No tasks found for index '{index_name}'")
            return {}
        
        # Dictionary to store file statuses:
        # {path_or_url: {process_state, forward_state, timestamps, progress fields}}
        file_states = {}
        for task_info in tasks_list:
            # No need to check index_name since get_index_tasks already filters by it
            task_path_or_url = task_info.get('path_or_url', '')
            task_name = task_info.get('task_name', '')
            task_status = task_info.get('status', '')
            task_created_at = task_info.get('created_at', 0)
            task_id = task_info.get('id', '')
            original_filename = task_info.get('original_filename', '')
            source_type = task_info.get('source_type', '')
            if task_path_or_url:
                # Initialize file state if not exists
                if task_path_or_url not in file_states:
                    file_states[task_path_or_url] = {
                        'process_state': '',
                        'forward_state': '',
                        'latest_process_created_at': 0,
                        'latest_forward_created_at': 0,
                        'latest_task_id': '',
                        'original_filename': '',
                        'source_type': '',
                        # Optional progress fields provided by data-process service
                        'processed_chunks': None,
                        'total_chunks': None,
                    }
                file_state = file_states[task_path_or_url]
                # Process task
                if task_name == 'process' and task_created_at > file_state['latest_process_created_at']:
                    file_state['latest_process_created_at'] = task_created_at
                    file_state['process_state'] = task_status
                    file_state['latest_task_id'] = task_id
                    file_state['original_filename'] = original_filename
                    file_state['source_type'] = source_type
                    # Update optional progress metrics if present
                    file_state['processed_chunks'] = task_info.get(
                        'processed_chunks', file_state.get('processed_chunks'))
                    file_state['total_chunks'] = task_info.get(
                        'total_chunks', file_state.get('total_chunks'))
                # Forward task
                elif task_name == 'forward' and task_created_at > file_state['latest_forward_created_at']:
                    file_state['latest_forward_created_at'] = task_created_at
                    file_state['forward_state'] = task_status
                    file_state['latest_task_id'] = task_id
                    file_state['original_filename'] = original_filename
                    file_state['source_type'] = source_type
                    # Forward tasks may also carry progress metrics
                    file_state['processed_chunks'] = task_info.get(
                        'processed_chunks', file_state.get('processed_chunks'))
                    file_state['total_chunks'] = task_info.get(
                        'total_chunks', file_state.get('total_chunks'))
        result = {}
        for path_or_url, file_state in file_states.items():
            # Call remote state conversion API so this service no longer depends on Celery
            custom_state = await _convert_to_custom_state(
                process_celery_state=file_state['process_state'] or '',
                forward_celery_state=file_state['forward_state'] or ''
            )
            # Try to get progress from Redis - always check Redis for real-time progress
            # especially when task is in progress (FORWARDING or PROCESSING)
            processed_chunks = file_state.get('processed_chunks')
            total_chunks = file_state.get('total_chunks')
            task_id = file_state['latest_task_id'] or ''

            # Always try to get latest progress from Redis if task_id exists
            # Redis has the most up-to-date progress during vectorization
            if task_id:
                try:
                    from services.redis_service import get_redis_service
                    redis_service = get_redis_service()
                    progress_info = redis_service.get_progress_info(task_id)
                    if progress_info:
                        # Use Redis progress as primary source (it's updated in real-time)
                        redis_processed = progress_info.get('processed_chunks')
                        redis_total = progress_info.get('total_chunks')
                        if redis_processed is not None:
                            processed_chunks = redis_processed
                        if redis_total is not None:
                            total_chunks = redis_total
                        logger.debug(
                            f"Retrieved progress from Redis for task {task_id}: {processed_chunks}/{total_chunks}")
                    else:
                        logger.debug(
                            f"No progress info in Redis for task {task_id}, using task state values: {processed_chunks}/{total_chunks}")
                except Exception as e:
                    logger.debug(
                        f"Failed to get progress from Redis for task {task_id}: {str(e)}")

            result[path_or_url] = {
                'state': custom_state,
                'latest_task_id': task_id,
                'original_filename': file_state['original_filename'] or '',
                'source_type': file_state['source_type'] or '',
                # Expose optional progress metrics for downstream consumers
                'processed_chunks': processed_chunks,
                'total_chunks': total_chunks,
            }
        return result
    except Exception as e:
        logger.error(f"Error getting all files status for index {index_name}, details: {str(e)} {traceback.format_exc()}")
        return {}  # Return empty dict on error


async def _convert_to_custom_state(process_celery_state: str, forward_celery_state: str) -> str:
    """Delegates Celery-state conversion to the data-process service.

    This removes the direct dependency on the *celery* package for callers of
    `file_management_utils`.
    """
    try:
        payload = {
            "process_state": process_celery_state,
            "forward_state": forward_celery_state,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(f"{DATA_PROCESS_SERVICE}/tasks/convert_state", json=payload, timeout=5.0)

        if response.status_code == 200:
            return response.json().get("state", "WAIT_FOR_PROCESSING")
        else:
            logger.warning(
                "State conversion service error: %s - %s", response.status_code, response.text
            )
    except Exception as e:
        logger.warning("Failed to convert state via service: %s", str(e))

    # Fallback mapping without Celery dependency (string comparison only)
    success = "SUCCESS"
    failure = "FAILURE"
    pending = "PENDING"
    started = "STARTED"

    if process_celery_state == failure:
        return "PROCESS_FAILED"
    if forward_celery_state == failure:
        return "FORWARD_FAILED"
    if process_celery_state == success and forward_celery_state == success:
        return "COMPLETED"
    if not process_celery_state and not forward_celery_state:
        return "WAIT_FOR_PROCESSING"

    forward_state_map = {
        pending: "WAIT_FOR_FORWARDING",
        started: "FORWARDING",
        success: "COMPLETED",
        failure: "FORWARD_FAILED",
    }
    process_state_map = {
        pending: "WAIT_FOR_PROCESSING",
        started: "PROCESSING",
        success: "WAIT_FOR_FORWARDING",
        failure: "PROCESS_FAILED",
    }

    if forward_celery_state:
        return forward_state_map.get(forward_celery_state, "WAIT_FOR_FORWARDING")
    if process_celery_state:
        return process_state_map.get(process_celery_state, "WAIT_FOR_PROCESSING")
    return "WAIT_FOR_PROCESSING"


def get_file_size(source_type: str, path_or_url: str) -> int:
    """Query the actual size(bytes) of the file."""
    try:
        if source_type == "minio":
            return get_file_size(path_or_url)

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
        cmd = [
            'libreoffice',
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', output_dir,
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
        result = await asyncio.to_thread(_run_libreoffice_conversion)
        
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


