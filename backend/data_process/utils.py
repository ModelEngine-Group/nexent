"""
Utility functions for Celery tasks
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import redis
from celery.result import AsyncResult

from .app import app as celery_app

logger = logging.getLogger("data_process.utils")


def get_all_task_ids_from_redis(redis_client: redis.Redis) -> List[str]:
    """
    Get all task IDs from Redis backend

    Returns:
        List of task IDs found in Redis
    """
    task_ids = []
    try:
        # Get all keys matching Celery result pattern
        result_keys = redis_client.keys('celery-task-meta-*')

        # Extract task IDs from keys
        for key in result_keys:
            if isinstance(key, bytes):
                key = key.decode('utf-8')

            # Extract task ID from key format: celery-task-meta-<task_id>
            if key.startswith('celery-task-meta-'):
                task_id = key.replace('celery-task-meta-', '')
                task_ids.append(task_id)

        logger.debug(f"Found {len(task_ids)} task IDs in Redis")
    except Exception as e:
        logger.warning(f"Failed to get task IDs from Redis: {str(e)}")

    return task_ids


async def get_task_info(task_id: str) -> Dict[str, Any]:
    """
    Get task status and metadata

    Args:
        task_id: Celery task ID

    Returns:
        Task status information
    """
    loop = asyncio.get_running_loop()

    def sync_get():
        result = AsyncResult(task_id, app=celery_app)

        # Get current time for updated_at if not available
        current_time = time.time()

        # Construct basic status information
        status_info = {
            'id': task_id,
            'index_name': '',
            'task_name': '',
            'path_or_url': '',
            'original_filename': '',
            'status': result.status if result.status else 'PENDING',
            'created_at': current_time,
            'updated_at': current_time,
            'error': None
        }

        # Check if result backend is available
        backend_available = True
        try:
            status = result.status
            if status:
                status_info['status'] = status
        except AttributeError as e:
            if 'DisabledBackend' in str(e):
                logger.warning(
                    f"Result backend is disabled for task {task_id}: {str(e)}")
                backend_available = False
                status_info['error'] = "Result backend disabled - cannot retrieve task status"
            else:
                logger.warning(f"Backend error for task {task_id}: {str(e)}")
                backend_available = False
                status_info['error'] = f"Backend error: {str(e)}"
        except Exception as e:
            logger.warning(
                f"Error accessing task status for {task_id}: {str(e)}")
            backend_available = False
            status_info['error'] = f"Status access error: {str(e)}"

        # If backend is available, try to get metadata
        if backend_available:
            try:
                # Add metadata from task state
                if result.info:
                    if isinstance(result.info, dict):
                        # For successful tasks, the result may contain metadata
                        metadata = result.info

                        # Get task_name from metadata if available
                        if 'task_name' in metadata:
                            status_info['task_name'] = metadata['task_name']

                        # Add timestamps if available
                        if 'start_time' in metadata:
                            status_info['created_at'] = metadata['start_time']

                        # Extract index_name from metadata
                        if 'index_name' in metadata:
                            status_info['index_name'] = metadata['index_name']

                        if 'source' in metadata:
                            status_info['path_or_url'] = metadata['source']

                        if 'original_filename' in metadata:
                            status_info['original_filename'] = metadata['original_filename']
                # Add error information for failed tasks
                if result.failed():
                    try:
                        info = str(result.info)
                        error_json = None
                        if isinstance(info, str):
                            try:
                                error_json = json.loads(info)
                            except Exception as e:
                                logger.error(
                                    f"Failed to load result.info as a json: {str(e)}")
                                error_json = None
                        else:
                            logger.warning(
                                f"Cannot parse result.info into a string: {type(result.info)}")

                        if error_json:
                            if error_json.get('message') is not None:
                                status_info['error'] = error_json.get(
                                    'message')
                            if error_json.get('index_name') is not None:
                                status_info['index_name'] = error_json.get(
                                    'index_name')
                            if error_json.get('task_name') is not None:
                                status_info['task_name'] = error_json.get(
                                    'task_name')
                            if error_json.get('source') is not None:
                                status_info['path_or_url'] = error_json.get(
                                    'source')
                            if error_json.get('original_filename') is not None:
                                status_info['original_filename'] = error_json.get(
                                    'original_filename')
                        else:
                            # fallback: compatible with previous format
                            status_info['error'] = str(
                                result.result) if result.result else "Unknown error"
                    except Exception as e:
                        logger.warning(
                            f"Could not parse error info for task {task_id}, falling back. Error: {e}")
                        status_info['error'] = str(
                            result.result) if result.result else "Unknown error"
                    logger.debug(
                        f"Task {task_id} failed with error: {status_info['error']}")

                # Add result information for successful tasks
                if result.successful() and result.result:
                    if isinstance(result.result, dict):
                        # Include specific result fields that are useful for API
                        for key in ['chunks_count', 'processing_time', 'storage_time', 'es_result']:
                            if key in result.result:
                                status_info[key] = result.result[key]
            except Exception as e:
                logger.warning(
                    f"Error getting metadata for task {task_id}: {str(e)}")
                status_info['error'] = f"Metadata access error: {str(e)}"
        logger.debug(
            f"Task {task_id} status: {status_info['status']}, index: {status_info['index_name']}, task_name: {status_info['task_name']}")
        return status_info
    try:
        return await loop.run_in_executor(None, sync_get)
    except ValueError as e:
        if "Exception information must include the exception type" in str(e):
            logger.warning(
                f"Task {task_id} has legacy bad exception format, marking as FAILURE for forced update.")
            return {
                'id': task_id,
                'status': 'FAILURE',
                'created_at': '',
                'updated_at': '',
                'error': 'Legacy task error: exception type missing, forcibly marked as FAILURE.',
                'index_name': '',
                'task_name': '',
                'path_or_url': '',
                'original_filename': '',
            }
        else:
            logger.error(f"Error getting status for task {task_id}: {str(e)}")
            return {
                'id': task_id,
                'status': 'FAILURE',
                'created_at': '',
                'updated_at': '',
                'error': f"Cannot retrieve task status: {str(e)}",
                'index_name': '',
                'task_name': '',
                'path_or_url': '',
                'original_filename': '',
            }
    except Exception as e:
        logger.warning(f"Error getting status for task {task_id}: {str(e)}")
        # Return minimal information if task status cannot be retrieved
        return {
            'id': task_id,
            'status': 'FAILURE',
            'created_at': "",
            'updated_at': "",
            'error': f"Cannot retrieve task status: {str(e)}",
            'index_name': '',
            'task_name': '',
            'path_or_url': '',
            'original_filename': '',
        }


async def get_task_details(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed task information

    Args:
        task_id: Celery task ID

    Returns:
        Detailed task information or None if not found
    """
    task_info = await get_task_info(task_id)
    loop = asyncio.get_running_loop()

    def sync_result():
        result = AsyncResult(task_id, app=celery_app)
        if result.successful() and result.result:
            if isinstance(result.result, dict):
                if 'chunks_count' in result.result:
                    task_info['chunks_count'] = result.result['chunks_count']
                if 'processing_time' in result.result:
                    task_info['processing_time'] = result.result['processing_time']
                if 'storage_time' in result.result:
                    task_info['storage_time'] = result.result['storage_time']
                if 'es_result' in result.result:
                    task_info['es_result'] = result.result['es_result']
                task_info['result'] = result.result
        return task_info
    return await loop.run_in_executor(None, sync_result)
