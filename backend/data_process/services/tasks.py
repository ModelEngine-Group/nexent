# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import concurrent.futures
import logging
import os
import shutil
import tempfile
import threading
import time
from typing import Any

import redis
from celery import states
from contracts.constants.constants import MAX_CONCURRENT_CONVERSIONS
from contracts.constants.environment import (
    REDIS_BACKEND_URL,
    REDIS_URL,
)
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, OfficeConversionException
from contracts.errors.ingestion import classify_ingestion_exception
from contracts.knowledge import BatchTaskRequest
from data_process.app import app as celery_app
from data_process.tasks import submit_process_forward_chain
from data_process.utils import (
    get_all_task_ids_from_redis,
    get_task_info,
)
from data_process.utils import get_task_details as get_task_details_info
from management.db.file.attachment import (
    delete_file,
    file_exists,
    get_file_stream,
    upload_file,
)
from management.services.file.upload import convert_office_to_pdf

from infrastructure.file_reads import read_attachment_size

# Limit concurrent LibreOffice processes to avoid resource exhaustion
_conversion_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CONVERSIONS)

# Configure logging
logger = logging.getLogger("data_process.service")


class DataProcessService:
    def __init__(self):
        """Initialize the DataProcessService

        Args:
            num_workers: Number of worker processes for data processing
        """
        # Initialize components in a modular way
        self._init_redis_client()


        self._inspector = None
        self._inspector_last_time = 0
        # 5 minutes - inspector is expensive to create (ping all workers)
        self._inspector_ttl = 300
        self._inspector_lock = None
        self._inspector_lock = threading.Lock()

    def _init_redis_client(self):
        """Initializes the Redis client and connection pool."""
        self.redis_pool = None
        self.redis_client = None
        try:
            redis_url = REDIS_BACKEND_URL
            if redis_url:
                self.redis_pool = redis.ConnectionPool.from_url(
                    redis_url,
                    max_connections=50,
                    decode_responses=True
                )
                self.redis_client = redis.Redis(
                    connection_pool=self.redis_pool)
                logger.info("Redis client initialized successfully.")
            else:
                logger.warning(
                    "REDIS_BACKEND_URL not set, Redis client not initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Redis client: {e!s}")

    async def start(self):
        """Start the data processing service"""
        logger.info("Data processing service started")

    async def stop(self):
        """Stop the data processing service"""
        logger.info("Data processing service stopped")

    def _get_celery_inspector(self):
        """Get Celery inspector (cached for performance)"""
        with self._inspector_lock:
            now = time.time()
            if self._inspector and now - self._inspector_last_time < self._inspector_ttl:
                return self._inspector
            if not celery_app.conf.broker_url or not celery_app.conf.result_backend:
                celery_app.conf.broker_url = REDIS_URL
                celery_app.conf.result_backend = REDIS_BACKEND_URL
                logger.warning(
                    f"Celery broker URL is not configured properly, reconfiguring to {celery_app.conf.broker_url}")
            try:
                inspector = celery_app.control.inspect()
                self._inspector = inspector
                self._inspector_last_time = now
                self._inspector_init_time = now
                return inspector
            except Exception as e:
                self._inspector = None
                raise Exception(
                    f"Failed to create inspector with celery_app: {e!s}")

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID (async)"""
        return await get_task_info(task_id)

    async def get_task_details(self, task_id: str) -> dict[str, Any] | None:
        """Get detailed task information, including the stored result."""
        return await get_task_details_info(task_id)

    async def get_all_tasks(self, filter: bool = True) -> list[dict[str, Any]]:
        """Get all tasks

        Args:
            filter: Whether to filter out useless task (i.e. process_and_forward) with no index_name and tast_name

        Returns:
            List[Dict[str, Any]]: List of all tasks
        """
        all_tasks = []
        try:
            self._get_celery_inspector()

            # Collect task IDs from different sources and keep runtime metadata
            task_ids = set()
            runtime_task_meta: dict[str, dict[str, Any]] = {}

            def _normalize_runtime_meta(task: dict[str, Any]) -> dict[str, Any]:
                task_name_full = task.get('name', '') or ''
                task_name = task_name_full.split(
                    '.')[-1] if task_name_full else ''
                kwargs = task.get('kwargs') or {}
                if isinstance(kwargs, str):
                    try:
                        import json as _json
                        kwargs = _json.loads(kwargs)
                    except Exception:
                        kwargs = {}
                if not isinstance(kwargs, dict):
                    kwargs = {}
                return {
                    'task_name': task_name,
                    'index_name': kwargs.get('index_name', ''),
                    'path_or_url': kwargs.get('source', ''),
                    'original_filename': kwargs.get('original_filename', ''),
                    'file_id': kwargs.get('file_id'),
                }

            celery_start = time.time()

            # Use short timeout for inspector since workers can respond in ~0.1s
            # Default 1s timeout is unnecessary and causes delay
            short_timeout = 0.2

            def get_active():
                t = time.time()
                # Create fresh inspector with short timeout for each call
                short_inspector = celery_app.control.inspect(
                    timeout=short_timeout)
                result = short_inspector.active()
                elapsed = time.time() - t
                logger.info(
                    f"[get_all_tasks] inspector.active() took {elapsed:.3f}s")
                return result if result else {}

            def get_reserved():
                t = time.time()
                short_inspector = celery_app.control.inspect(
                    timeout=short_timeout)
                result = short_inspector.reserved()
                elapsed = time.time() - t
                logger.info(
                    f"[get_all_tasks] inspector.reserved() took {elapsed:.3f}s")
                return result if result else {}

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_active = executor.submit(get_active)
                future_reserved = executor.submit(get_reserved)
                active_tasks_dict = future_active.result(
                    timeout=short_timeout + 0.5)
                reserved_tasks_dict = future_reserved.result(
                    timeout=short_timeout + 0.5)
            celery_duration = time.time() - celery_start
            if celery_duration > 0.5:
                logger.warning(
                    f"[get_all_tasks] Inspector took {celery_duration:.3f}s (expected <0.5s)")
            if active_tasks_dict:
                for worker, tasks in active_tasks_dict.items():
                    for task in tasks:
                        task_id = task.get('id')
                        if task_id:
                            task_ids.add(task_id)
                            runtime_task_meta[task_id] = _normalize_runtime_meta(
                                task)
            if reserved_tasks_dict:
                for worker, tasks in reserved_tasks_dict.items():
                    for task in tasks:
                        task_id = task.get('id')
                        if task_id:
                            task_ids.add(task_id)
                            # Keep active metadata if already present
                            runtime_task_meta.setdefault(
                                task_id, _normalize_runtime_meta(task))

            # Get task IDs from Redis backend (covers completed/failed tasks within expiry)
            try:
                redis_task_ids = get_all_task_ids_from_redis(self.redis_client)
                for task_id in redis_task_ids:
                    task_ids.add(task_id)
            except Exception as redis_error:
                logger.warning(
                    f"Failed to query Redis for stored task IDs: {redis_error!s}")

            task_id_list = list(task_ids)
            # Batch fetch all task info
            tasks = [get_task_info(task_id) for task_id in task_id_list]
            all_task_infos = await asyncio.gather(*tasks, return_exceptions=True)
            for idx, task_info in enumerate(all_task_infos):
                if isinstance(task_info, Exception):
                    logger.warning(
                        f"Failed to get status for a task: {task_info}")
                    continue
                task_id = task_id_list[idx]
                runtime_meta = runtime_task_meta.get(task_id, {})
                # Backfill runtime info for pending/reserved tasks that do not have result metadata yet
                if runtime_meta:
                    if not task_info.get('task_name') and runtime_meta.get('task_name'):
                        task_info['task_name'] = runtime_meta.get('task_name')
                    if not task_info.get('index_name') and runtime_meta.get('index_name'):
                        task_info['index_name'] = runtime_meta.get(
                            'index_name')
                    if not task_info.get('path_or_url') and runtime_meta.get('path_or_url'):
                        task_info['path_or_url'] = runtime_meta.get(
                            'path_or_url')
                    if not task_info.get('original_filename') and runtime_meta.get('original_filename'):
                        task_info['original_filename'] = runtime_meta.get(
                            'original_filename')
                    if not task_info.get('file_id') and runtime_meta.get('file_id'):
                        task_info['file_id'] = runtime_meta.get('file_id')

                if filter and not (task_info.get('index_name') and task_info.get('task_name')):
                    # Keep user-visible queued tasks even before worker updates task meta.
                    if task_info.get('task_name') not in {'process', 'forward', 'process_and_forward'}:
                        continue
                    if not task_info.get('index_name'):
                        continue
                all_tasks.append(task_info)
        except Exception as e:
            logger.error(f"Error retrieving all tasks: {e!s}")
            all_tasks = []

        return all_tasks

    async def get_index_tasks(self, index_name: str, filter: bool = True) -> list[dict[str, Any]]:
        """Get all active tasks for a specific index

        Args:
            index_name: Name of the index to filter tasks for

        Returns:
            List[Dict[str, Any]]: Tasks for the specified index
        """
        task_list = await self.get_all_tasks(filter)
        # May got multiple tasks for the same index
        return [task for task in task_list if task.get('index_name') == index_name]


    async def create_batch_tasks_impl(self, authorization: str | None, request: BatchTaskRequest):
        task_ids = []
        results = []

        def config_value(source_config: Any, key: str, default: Any = None) -> Any:
            if isinstance(source_config, dict):
                return source_config.get(key, default)
            return getattr(source_config, key, default)

        def build_failure_result(source_config: dict, error: object) -> dict:
            classified = classify_ingestion_exception(error, "TASK_SUBMIT")
            return {
                "file_id": config_value(source_config, "file_id"),
                "source": config_value(source_config, "source"),
                "original_filename": config_value(source_config, "original_filename"),
                "status": "FAILED",
                "error_code": classified.error_code,
                "error_message": classified.error_message,
            }

        # Create individual tasks for each source
        for source_config in request.sources:
            # Extract parameters
            source = config_value(source_config, 'source')
            source_type = config_value(source_config, 'source_type')
            chunking_strategy = config_value(source_config, 'chunking_strategy')
            index_name = config_value(source_config, 'index_name')
            original_filename = config_value(source_config, 'original_filename')
            embedding_model_id = config_value(source_config, 'embedding_model_id')
            tenant_id = config_value(source_config, 'tenant_id')
            file_id = config_value(source_config, 'file_id')
            telemetry_context = config_value(source_config, 'telemetry_context') or {}

            # Validate required fields
            if not source:
                logger.error(
                    f"Missing required field 'source' in source config: {source_config}")
                results.append(build_failure_result(
                    source_config,
                    AppException(
                        ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
                        "Missing required field 'source'",
                    ),
                ))
                continue
            if not index_name:
                logger.error(
                    f"Missing required field 'index_name' in source config: {source_config}")
                results.append(build_failure_result(
                    source_config,
                    AppException(
                        ErrorCode.COMMON_MISSING_REQUIRED_FIELD,
                        "Missing required field 'index_name'",
                    ),
                ))
                continue

            chain_kwargs = dict(
                source=source,
                source_type=source_type,
                chunking_strategy=chunking_strategy,
                index_name=index_name,
                original_filename=original_filename,
                authorization=authorization,
                embedding_model_id=embedding_model_id,
                tenant_id=tenant_id,
                telemetry_context=telemetry_context,
            )
            if file_id is not None:
                chain_kwargs["file_id"] = file_id
            try:
                chain_id = submit_process_forward_chain(**chain_kwargs)
            except Exception as exc:
                logger.exception(
                    "Failed to enqueue process-forward chain for source: %s", source)
                results.append(build_failure_result(
                    source_config, f"Failed to enqueue process-forward chain: {exc}"))
                continue
            if not chain_id:
                logger.error(
                    f"Failed to enqueue process-forward chain for source: {source}")
                results.append(build_failure_result(
                    source_config, "Failed to enqueue process-forward chain"))
                continue

            task_ids.append(chain_id)
            results.append({
                "file_id": file_id,
                "source": source,
                "original_filename": original_filename,
                "status": "SUBMITTED",
                "task_id": chain_id,
            })
            logger.debug(f"Created task {chain_id} for source: {source}")

        failed_count = len(results) - len(task_ids)
        if failed_count == 0:
            status = "success"
        elif task_ids:
            status = "partial_success"
        else:
            status = "failed"
        logger.info(
            "Created %s individual tasks for batch processing; %s failed",
            len(task_ids),
            failed_count,
        )
        return {
            "status": status,
            "task_ids": task_ids,
            "results": results,
            "submitted_count": len(task_ids),
            "failed_count": failed_count,
        }


    async def convert_office_to_pdf_impl(self, object_name: str, pdf_object_name: str) -> None:
        """Full conversion pipeline: download -> convert -> upload -> validate -> cleanup.

        All five steps run inside data-process so that LibreOffice only needs to be
        installed in this container.

        Args:
            object_name: Source Office file path in MinIO.
            pdf_object_name: Destination PDF path in MinIO (final, not temp).
        """
        async with _conversion_semaphore:
            temp_dir = None
            try:
                temp_dir = tempfile.mkdtemp(prefix='office_convert_')

                # Step 1: Download original Office file from MinIO
                original_stream = get_file_stream(object_name)
                if original_stream is None:
                    raise OfficeConversionException(
                        f"Source file not found in storage: {object_name}")

                original_filename = os.path.basename(object_name)
                input_path = os.path.join(temp_dir, original_filename)
                with open(input_path, 'wb') as f:
                    while chunk := original_stream.read(1024 * 1024):
                        f.write(chunk)

                # Step 2: Local conversion using LibreOffice
                try:
                    pdf_path = await convert_office_to_pdf(input_path, temp_dir, timeout=30)
                except Exception as exc:
                    raise OfficeConversionException(
                        f"LibreOffice conversion failed: {exc}") from exc

                # Step 3: Upload converted PDF to MinIO
                result = upload_file(file_path=pdf_path,
                                     object_name=pdf_object_name)
                if not result.get('success'):
                    raise OfficeConversionException(
                        f"Failed to upload PDF to MinIO: {result.get('error', 'Unknown error')}"
                    )

                # Step 4: Validate the uploaded PDF (header check + minimum size)
                remote_size = read_attachment_size(pdf_object_name)
                if remote_size <= 0:
                    raise OfficeConversionException(
                        "PDF validation failed: cannot read remote file size")
                if remote_size < 100:
                    raise OfficeConversionException(
                        f"PDF validation failed: file too small ({remote_size} bytes)"
                    )
                remote_stream = get_file_stream(pdf_object_name)
                if remote_stream is None:
                    raise OfficeConversionException(
                        "PDF validation failed: cannot read uploaded file")
                try:
                    header = remote_stream.read(5)
                finally:
                    try:
                        remote_stream.close()
                    except Exception:
                        pass
                if not header.startswith(b'%PDF-'):
                    raise OfficeConversionException(
                        "PDF validation failed: invalid PDF header")

            except OfficeConversionException:
                # Clean up any partially-uploaded remote PDF so a future retry starts clean
                if file_exists(pdf_object_name):
                    delete_file(pdf_object_name)
                raise
            except Exception as exc:
                raise OfficeConversionException(
                    f"Unexpected error during conversion: {exc}") from exc
            finally:
                # Step 5: Clean up local temporary directory
                if temp_dir and os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception as cleanup_err:
                        logger.warning(
                            f"Failed to cleanup temp dir '{temp_dir}': {cleanup_err}")

    def convert_celery_states_to_custom(self, process_celery_state: str | None, forward_celery_state: str | None) -> str:
        """Map Celery task states to a custom frontend state string.

        This implements the business logic that was previously in the app layer.
        """
        if process_celery_state == states.FAILURE:
            return "PROCESS_FAILED"
        if forward_celery_state == states.FAILURE:
            return "FORWARD_FAILED"

        if process_celery_state == states.SUCCESS and forward_celery_state == states.SUCCESS:
            return "COMPLETED"

        forward_state_map = {
            states.PENDING: "WAIT_FOR_FORWARDING",
            states.STARTED: "FORWARDING",
            states.SUCCESS: "COMPLETED",
            states.FAILURE: "FORWARD_FAILED",
        }
        process_state_map = {
            states.PENDING: "WAIT_FOR_PROCESSING",
            states.STARTED: "PROCESSING",
            states.SUCCESS: "WAIT_FOR_FORWARDING",
            states.FAILURE: "PROCESS_FAILED",
        }

        if forward_celery_state:
            return forward_state_map.get(forward_celery_state, "WAIT_FOR_FORWARDING")
        if process_celery_state:
            return process_state_map.get(process_celery_state, "WAIT_FOR_PROCESSING")
        return "WAIT_FOR_PROCESSING"


# Global instance to be shared across modules
# This avoids creating multiple instances and loading CLIP model multiple times
_data_process_service = None


def get_data_process_service():
    """Get or create the global DataProcessService instance (lazy initialization)"""
    global _data_process_service
    if _data_process_service is None:
        _data_process_service = DataProcessService()
    return _data_process_service
