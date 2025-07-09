import logging
import os
from pathlib import Path
from typing import List
import traceback

import aiofiles
import httpx
from fastapi import UploadFile
import requests

from consts.const import DATA_PROCESS_SERVICE
from consts.model import ProcessParams

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


async def trigger_data_process(file_paths: List[str], process_params: ProcessParams):
    """Trigger data processing service to handle uploaded files"""
    try:
        if not file_paths:
            return None

        # Build source data list
        if len(file_paths) == 1:
            # Single file request
            payload = {"source": file_paths[0], "source_type": "file",
                "chunking_strategy": process_params.chunking_strategy, "index_name": process_params.index_name}

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(f"{DATA_PROCESS_SERVICE}/tasks", json=payload, timeout=30.0)

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
            for file_path in file_paths:
                source = {"source": file_path, "source_type": "file", "index_name": process_params.index_name}

                sources.append(source)

            payload = {"sources": sources}

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(f"{DATA_PROCESS_SERVICE}/tasks/batch", json=payload, timeout=30.0)

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
        
        logger.info(f"Found {len(tasks_list)} tasks for index '{index_name}'")
        if not tasks_list:
            logger.warning(f"No tasks found for index '{index_name}'")
            return {}
        
        # Dictionary to store file statuses: {path_or_url: {process_state, forward_state, timestamps}}
        file_states = {}
        for task_info in tasks_list:
            # No need to check index_name since get_index_tasks already filters by it
            task_path_or_url = task_info.get('path_or_url', '')
            task_name = task_info.get('task_name', '')
            task_status = task_info.get('status', '')
            task_created_at = task_info.get('created_at', 0)
            task_id = task_info.get('id', '')
            if task_path_or_url:
                # Initialize file state if not exists
                if task_path_or_url not in file_states:
                    file_states[task_path_or_url] = {
                        'process_state': '',
                        'forward_state': '',
                        'latest_process_created_at': 0,
                        'latest_forward_created_at': 0,
                        'latest_task_id': ''
                    }
                file_state = file_states[task_path_or_url]
                # Process task
                if task_name == 'process' and task_created_at > file_state['latest_process_created_at']:
                    file_state['latest_process_created_at'] = task_created_at
                    file_state['process_state'] = task_status
                    file_state['latest_task_id'] = task_id
                # Forward task
                elif task_name == 'forward' and task_created_at > file_state['latest_forward_created_at']:
                    file_state['latest_forward_created_at'] = task_created_at
                    file_state['forward_state'] = task_status
                    file_state['latest_task_id'] = task_id
        result = {}
        for path_or_url, file_state in file_states.items():
            custom_state = _convert_to_custom_state(
                process_celery_state=file_state['process_state'] or '',
                forward_celery_state=file_state['forward_state'] or ''
            )
            result[path_or_url] = {
                'state': custom_state,
                'latest_task_id': file_state['latest_task_id'] or ''
            }
        return result
    except Exception as e:
        logger.error(f"Error getting all files status for index {index_name}, details: {str(e)} {traceback.format_exc()}")
        return {}  # Return empty dict on error


def _convert_to_custom_state(process_celery_state: str, forward_celery_state: str) -> str:
    """
    Convert Celery task state to frontend representation
    
    Args:
        process_celery_state: Process task Celery state
        forward_celery_state: Forward task Celery state
        
    Returns:
        Converted state for frontend, value set:
        - WAIT_FOR_PROCESSING
        - PROCESSING
        - WAIT_FOR_FORWARDING
        - FORWARDING
        - COMPLETED
        - PROCESS_FAILED
        - FORWARD_FAILED
    """
    from celery import states
    
    # Handle failure states first
    if process_celery_state == states.FAILURE:
        return "PROCESS_FAILED"
    if forward_celery_state == states.FAILURE:
        return "FORWARD_FAILED"
    
    # Handle completed state - both must be SUCCESS
    if process_celery_state == states.SUCCESS and forward_celery_state == states.SUCCESS:
        return "COMPLETED"
    
    # Handle case where nothing has started
    if not process_celery_state and not forward_celery_state:
        return "WAIT_FOR_PROCESSING"
    
    # Define state mappings with SUCCESS included
    forward_state_map = {
        states.PENDING: "WAIT_FOR_FORWARDING",
        states.STARTED: "FORWARDING",
        states.SUCCESS: "COMPLETED",
        states.FAILURE: "FORWARD_FAILED",
    }
    process_state_map = {
        states.PENDING: "WAIT_FOR_PROCESSING", 
        states.STARTED: "PROCESSING",
        states.SUCCESS: "WAIT_FOR_FORWARDING",  # Process done, waiting for forward
        states.FAILURE: "PROCESS_FAILED",
    }
    
    # Determine current state based on progress
    if forward_celery_state:
        # Forward task exists, use its state with fallback
        return forward_state_map.get(forward_celery_state, "WAIT_FOR_FORWARDING")
    elif process_celery_state:
        # Only process task exists, use its state with fallback
        return process_state_map.get(process_celery_state, "WAIT_FOR_PROCESSING")
    else:
        # Fallback case
        return "WAIT_FOR_PROCESSING"
    

def get_file_size(source_type: str, path_or_url: str) -> int:
        """Query the actual size(bytes) of the file"""
        try:
            if source_type == "url":
                # For URL type, use requests library to get file size
                response = requests.head(path_or_url)
                if 'content-length' in response.headers:
                    return int(response.headers['content-length'])
                return 0
            elif source_type == "file":
                # For local files, use os.path.getsize to get file size
                return os.path.getsize(path_or_url)
            else:
                raise NotImplementedError(f"Unexpected source type: {source_type}")
        except Exception as e:
            logger.error(f"Error getting file size for {path_or_url}: {str(e)}")
            return 0