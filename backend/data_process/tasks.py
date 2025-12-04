"""
Celery tasks for data processing and vector storage
"""
import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import aiohttp
import ray
from celery import Task, chain, states
from celery.exceptions import Retry

from consts.const import ELASTICSEARCH_SERVICE
from utils.file_management_utils import get_file_size
from services.redis_service import get_redis_service
from .app import app
from .ray_actors import DataProcessorRayActor
from consts.const import (
    REDIS_BACKEND_URL,
    FORWARD_REDIS_RETRY_DELAY_S,
    FORWARD_REDIS_RETRY_MAX,
    DISABLE_RAY_DASHBOARD,
    ROOT_DIR,
)


logger = logging.getLogger("data_process.tasks")

# Thread lock for initializing Ray to prevent race conditions
ray_init_lock = threading.Lock()

ROOT_DIR_DISPLAY = ROOT_DIR or "{ROOT_DIR}"

# Internationalized error guide for user-friendly messages
# Keys are stable error codes; each contains translations for supported languages.
ERROR_GUIDE = {
    "ray_init_failed": {
        "zh": {
            "message": "Ray集群初始化失败",
            "solution": "请升级到最新版本并尝试重新部署",
        },
        "en": {
            "message": "Failed to initialize Ray cluster",
            "solution": "Please upgrade to the latest image version and redeploy.",
        },
    },
    "no_valid_chunks": {
        "zh": {
            "message": "数据处理内核无法从文档中提取有效文本",
            "solution": "请确保文档内容非纯图像",
        },
        "en": {
            "message": "The data processing kernel could not extract valid text from the document",
            "solution": "Please ensure the document format is supported and the content is not purely images.",
        },
    },
    "vector_service_busy": {
        "zh": {
            "message": "向量化模型服务繁忙，无法获取文本向量",
            "solution": "请更换模型服务提供商，或稍后重试",
        },
        "en": {
            "message": "Vectorization model service is busy and cannot return vectors",
            "solution": "Please switch the model service provider or try again later.",
        },
    },
    "es_bulk_failed": {
        "zh": {
            "message": "向量录入数据库错误",
            "solution": f"请确保{ROOT_DIR_DISPLAY}/nexent/docker/elasticsearch/ 路径拥有完整写入权限，且存储空间与内存充足",
        },
        "en": {
            "message": "Failed to write vectors into the database",
            "solution": "Please ensure the Elasticsearch data path has sufficient disk space and write permissions.",
        },
    },
    "embedding_chunks_exceed_limit": {
        "zh": {
            "message": "当前切片数量超过向量化模型并行度",
            "solution": "请增加切片大小以减少切片数量后再试",
        },
        "en": {
            "message": "The current chunk count exceeds the embedding model concurrency limit",
            "solution": "Please increase the chunk size to reduce the number of chunks and try again.",
        },
    },
}


def get_error_template(key: str, lang: str = "zh") -> Optional[Dict[str, str]]:
    """Return localized error template for the given key."""
    template = ERROR_GUIDE.get(key)
    if not template:
        return None
    if lang in template:
        return template[lang]
    # Fallback to Chinese if specific language is not available
    return template.get("zh") or next(iter(template.values()))


def build_friendly_reason_from_key(key: str, lang: str = "zh") -> str:
    """
    Build a friendly_reason string from ERROR_GUIDE.

    This is used only for internal storage; the app layer will split message
    and solution for frontend display.
    """
    tpl = get_error_template(key, lang)
    if not tpl:
        return ""
    message = tpl.get("message") or ""
    solution = tpl.get("solution") or ""
    if solution:
        return f"{message}。建议：{solution}"
    return message


def enrich_error_reason(reason: str) -> Optional[str]:
    if not reason:
        return None
    if "Failed to initialize Ray for Celery worker" in reason:
        return build_friendly_reason_from_key("ray_init_failed")
    return None


def save_error_to_redis(task_id: str, error_reason: str, start_time: float):
    """
    Save error information to Redis

    Args:
        task_id: Celery task ID
        error_reason: Short error reason summary
        start_time: Task start timestamp (unused, kept for compatibility)
    """
    if not task_id:
        logger.warning("Cannot save error info: task_id is empty")
        return
    if not error_reason:
        logger.warning(
            f"Cannot save error info for task {task_id}: error_reason is empty")
        return
    try:
        redis_service = get_redis_service()
        success = redis_service.save_error_info(task_id, error_reason)
        if success:
            logger.info(
                f"Successfully saved error info for task {task_id}: {error_reason[:100]}...")
        else:
            logger.warning(
                f"Failed to save error info for task {task_id}: save_error_info returned False")
    except Exception as e:
        logger.error(
            f"Failed to save error info to Redis for task {task_id}: {str(e)}", exc_info=True)


def init_ray_in_worker():
    """
    Initializes Ray within a Celery worker, ensuring it is done only once.
    This function is designed to be called from within a task.
    """
    if ray.is_initialized():
        logger.debug("Ray is already initialized.")
        return

    logger.info("Ray not initialized. Initializing Ray for Celery worker...")
    try:
        # `configure_logging=False` prevents Ray from setting up its own loggers,
        # which can interfere with Celery's logging.
        # `faulthandler=False` is critical to prevent the
        # `AttributeError: 'LoggingProxy' object has no attribute 'fileno'`
        # error when running inside a Celery worker.
        # We also explicitly control the Ray dashboard behavior here to ensure
        # that Celery workers respect the global DISABLE_RAY_DASHBOARD setting.
        ray.init(
            configure_logging=False,
            faulthandler=False,
            include_dashboard=not DISABLE_RAY_DASHBOARD,
        )
        logger.info("Ray initialized successfully for Celery worker.")
    except Exception as e:
        logger.error(f"Failed to initialize Ray for Celery worker: {e}")
        raise RuntimeError("Failed to initialize Ray for Celery worker") from e


def run_async(coro):
    """
    Safely run async coroutine in Celery task context
    Handles existing event loops and avoids conflicts
    """
    try:
        # Check if we're already in an async context
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, safe to use asyncio.run
            return asyncio.run(coro)

        # We're in an existing event loop context
        if loop.is_running():
            # Try to use nest_asyncio for compatibility
            try:
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(coro)
            except ImportError:
                logger.warning(
                    "nest_asyncio not available, creating new thread for async operation")
                # Fallback: run in a new thread
                import concurrent.futures

                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(coro)
                    finally:
                        new_loop.close()
                        asyncio.set_event_loop(None)

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    return future.result()
        else:
            # Loop exists but not running, safe to use run_until_complete
            return loop.run_until_complete(coro)

    except Exception as e:
        logger.error(f"Error running async coroutine: {str(e)}")
        raise


# Initialize the data processing core LAZILY
# This will be initialized on first task run by a worker process
def get_ray_actor() -> Any:
    """
    Creates a new, anonymous DataProcessorRayActor instance for each call.
    This allows for parallel execution of data processing tasks, with each
    task running in its own actor.
    """
    with ray_init_lock:
        init_ray_in_worker()
    actor = DataProcessorRayActor.remote()

    logger.debug(
        "Successfully created a new DataProcessorRayActor for a task.")
    return actor


class LoggingTask(Task):
    """Base task class with enhanced logging"""

    def on_success(self, retval, task_id, args, kwargs):
        """Log successful task completion"""
        logger.debug(f"Task {self.name}[{task_id}] completed successfully")
        return super().on_success(retval, task_id, args, kwargs)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Log task failure with enhanced error handling"""
        logger.error(f"Task {self.name}[{task_id}] failed: {exc}")
        # Log exception details for debugging
        if hasattr(exc, '__class__'):
            exc_type = exc.__class__.__name__
            exc_msg = str(exc)
            logger.error(f"Exception type: {exc_type}, message: {exc_msg}")
        # Let Celery handle the exception serialization automatically
        return super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Log task retry"""
        logger.warning(f"Task {self.name}[{task_id}] retrying: {exc}")
        return super().on_retry(exc, task_id, args, kwargs, einfo)


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.process', queue='process_q')
def process(
        self,
        source: str,
        source_type: str,
        chunking_strategy: str = "basic",
        index_name: Optional[str] = None,
        original_filename: Optional[str] = None,
        embedding_model_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        **params
) -> Dict:
    """
    Process a file and extract text/chunks

    Args:
        source: Source file path, URL, or text content
        source_type: Type of source ("local", "minio")
        chunking_strategy: Strategy for chunking the document
        index_name: Name of the index (for metadata)
        original_filename: The original name of the file
        embedding_model_id: Embedding model ID for chunk size configuration
        tenant_id: Tenant ID for retrieving model configuration
        **params: Additional parameters
    """
    start_time = time.time()
    task_id = self.request.id

    logger.info(
        f"[{self.request.id}] PROCESS TASK: source_type: {source_type}")

    self.update_state(
        state=states.STARTED,
        meta={
            'source': source,
            'source_type': source_type,
            'index_name': index_name,
            'original_filename': original_filename,
            'task_name': 'process',
            'start_time': start_time,
            'stage': 'extracting_text'
        }
    )
    # Get the data processor instance
    actor = get_ray_actor()

    try:
        # Process the file based on the source type
        file_size_mb = 0
        if source_type == "local":
            # Check file existence and size for optimization
            if not os.path.exists(source):
                raise FileNotFoundError(f"File does not exist: {source}")

            file_size = os.path.getsize(source)
            file_size_mb = file_size / (1024 * 1024)

            logger.info(
                f"[{self.request.id}] PROCESS TASK: File size: {file_size_mb:.2f}MB")

            # The unified actor call, mapping 'file' source_type to 'local' destination
            # Submit Ray work and WAIT for processing to complete
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Submitting Ray processing for source='{source}', strategy='{chunking_strategy}', destination='{source_type}', model_id={embedding_model_id}")
            chunks_ref = actor.process_file.remote(
                source,
                chunking_strategy,
                destination=source_type,
                task_id=task_id,
                model_id=embedding_model_id,
                tenant_id=tenant_id,
                **params
            )
            # Wait for Ray processing to complete (this keeps task in STARTED/"PROCESSING" state)
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Waiting for Ray processing to complete...")
            chunks = ray.get(chunks_ref)
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Ray processing completed, got {len(chunks) if chunks else 0} chunks")

            # Persist chunks into Redis via Ray (synchronous to ensure data is ready before forward task)
            redis_key = f"dp:{task_id}:chunks"
            actor.store_chunks_in_redis.remote(redis_key, chunks)
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Stored chunks in Redis at key '{redis_key}'")

            end_time = time.time()
            elapsed_time = end_time - start_time
            processing_speed = file_size_mb / \
                elapsed_time if file_size_mb > 0 and elapsed_time > 0 else 0
            logger.info(
                f"[{self.request.id}] PROCESS TASK: File processing completed. Processing speed {processing_speed:.2f} MB/s")

        elif source_type == "minio":
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Processing from URL: {source}")

            # For URL source, core.py expects a non-local destination to trigger URL fetching
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Submitting Ray processing for URL='{source}', strategy='{chunking_strategy}', destination='{source_type}', model_id={embedding_model_id}")
            chunks_ref = actor.process_file.remote(
                source,
                chunking_strategy,
                destination=source_type,
                task_id=task_id,
                model_id=embedding_model_id,
                tenant_id=tenant_id,
                **params
            )
            # Wait for Ray processing to complete (this keeps task in STARTED/"PROCESSING" state)
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Waiting for Ray processing to complete...")
            chunks = ray.get(chunks_ref)
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Ray processing completed, got {len(chunks) if chunks else 0} chunks")

            # Persist chunks into Redis via Ray (synchronous to ensure data is ready before forward task)
            redis_key = f"dp:{task_id}:chunks"
            actor.store_chunks_in_redis.remote(redis_key, chunks)
            logger.info(
                f"[{self.request.id}] PROCESS TASK: Stored chunks in Redis at key '{redis_key}'")

            end_time = time.time()
            elapsed_time = end_time - start_time
            logger.info(
                f"[{self.request.id}] PROCESS TASK: URL processing completed in {elapsed_time:.2f}s")

        else:
            # For other source types, implement accordingly
            raise NotImplementedError(
                f"Source type '{source_type}' not yet supported")

        chunk_count = len(chunks) if chunks else 0
        if chunk_count == 0:
            friendly_reason = build_friendly_reason_from_key("no_valid_chunks")
            raise Exception(json.dumps({
                "message": "Ray processing completed but produced 0 chunks",
                "index_name": index_name,
                "task_name": "process",
                "source": source,
                "original_filename": original_filename,
                "friendly_reason": friendly_reason
            }, ensure_ascii=False))

        # Update task state to SUCCESS after Ray processing completes
        # This transitions from STARTED (PROCESSING) to SUCCESS (WAIT_FOR_FORWARDING)
        self.update_state(
            state=states.SUCCESS,
            meta={
                'chunks_count': len(chunks) if chunks else 0,
                'processing_time': elapsed_time,
                'source': source,
                'index_name': index_name,
                'original_filename': original_filename,
                'task_name': 'process',
                'stage': 'text_extracted',
                'file_size_mb': file_size_mb,
                'processing_speed_mb_s': file_size_mb / elapsed_time if file_size_mb > 0 and elapsed_time > 0 else 0
            }
        )

        logger.info(
            f"[{self.request.id}] PROCESS TASK: Processing complete, waiting for forward task")

        # Prepare data for the next task in the chain; pass redis_key
        returned_data = {
            'redis_key': f"dp:{task_id}:chunks",
            'chunks': None,
            'source': source,
            'index_name': index_name,
            'original_filename': original_filename,
            'task_id': task_id
        }

        return returned_data

    except Exception as e:
        logger.error(f"Error processing file {source}: {str(e)}")
        # task_id is already defined at the start of the function
        try:
            # Try to parse the exception as JSON (it might be our custom JSON error)
            error_message = str(e)
            friendly_reason = None
            parsed_error = None

            try:
                parsed_error = json.loads(error_message)
                if isinstance(parsed_error, dict):
                    error_message = parsed_error.get("message", error_message)
                    friendly_reason = parsed_error.get("friendly_reason")
                    logger.debug(
                        f"Parsed JSON error for task {task_id}: friendly_reason={friendly_reason}"
                    )
            except (json.JSONDecodeError, TypeError):
                # Not a JSON string, use as-is
                logger.debug(
                    f"Exception is not JSON format for task {task_id}, using raw message"
                )

            # Build error_info for re-raising
            error_info = {
                "message": error_message,
                "index_name": index_name,
                "task_name": "process",
                "source": source,
                "original_filename": original_filename,
            }
            if friendly_reason:
                error_info["friendly_reason"] = friendly_reason

            # Determine friendly reason for storage
            if not friendly_reason:
                friendly_reason = enrich_error_reason(error_message)
            reason_to_store = friendly_reason or error_message
            if len(reason_to_store) > 200:
                reason_to_store = reason_to_store[:200] + "..."

            # Save error info to Redis BEFORE re-raising
            logger.info(
                f"Attempting to save error info for task {task_id} with reason: {reason_to_store[:100]}..."
            )
            save_error_to_redis(task_id, reason_to_store, start_time)

            self.update_state(
                meta={
                    "source": error_info.get("source", ""),
                    "index_name": error_info.get("index_name", ""),
                    "task_name": error_info.get("task_name", ""),
                    "original_filename": error_info.get(
                        "original_filename", ""
                    ),
                    "custom_error": error_info.get("message", str(e)),
                    "stage": "text_extraction_failed",
                }
            )
            raise Exception(json.dumps(error_info, ensure_ascii=False))
        except Exception as ex:
            logger.error(f"Error serializing process exception: {str(ex)}")
            # Try to save error even if serialization fails
            try:
                error_message = str(e)
                friendly_reason = None
                parsed_error = None

                try:
                    parsed_error = json.loads(error_message)
                    if isinstance(parsed_error, dict):
                        error_message = parsed_error.get(
                            "message", error_message
                        )
                        friendly_reason = parsed_error.get("friendly_reason")
                        logger.debug(
                            "Fallback serialization: parsed JSON error for task "
                            f"{task_id}, friendly_reason={friendly_reason}"
                        )
                except (json.JSONDecodeError, TypeError):
                    logger.debug(
                        "Fallback serialization: exception is not JSON format "
                        f"for task {task_id}, using raw message"
                    )

                if not friendly_reason:
                    friendly_reason = enrich_error_reason(error_message)

                reason_to_store = friendly_reason or error_message
                if len(reason_to_store) > 200:
                    reason_to_store = reason_to_store[:200] + "..."

                save_error_to_redis(task_id, reason_to_store, start_time)
            except Exception:
                pass
            self.update_state(
                meta={
                    "custom_error": str(e),
                    "stage": "text_extraction_failed",
                }
            )
            raise


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.forward', queue='forward_q')
def forward(
        self,
        processed_data: Dict,
        index_name: str,
        source: str,
        source_type: str = 'minio',
        original_filename: Optional[str] = None,
        authorization: Optional[str] = None
) -> Dict:
    """
    Vectorize and store processed chunks in Elasticsearch

    Args:
        processed_data: Dict containing chunks and metadata
        index_name: Name of the index to store documents
        source: Original source path (for metadata)
        source_type: The type of the source("local", "minio")
        original_filename: The original name of the file
        authorization: Authorization header for API calls

    Returns:
        Dict containing storage results and metadata
    """
    start_time = time.time()
    task_id = self.request.id
    original_source = source
    original_index_name = index_name
    filename = original_filename

    try:
        # Before doing any heavy work, check whether this task has been
        # explicitly cancelled (for example, because the user deleted the
        # document from the knowledge base configuration page).
        try:
            redis_service = get_redis_service()
            if redis_service.is_task_cancelled(task_id):
                logger.info(
                    f"[{self.request.id}] FORWARD TASK: Detected cancellation flag for task {task_id}; "
                    f"skipping chunk forwarding for source '{source}' in index '{index_name}'."
                )
                # Treat this as a graceful early exit. We still return a
                # structured payload so callers can consider the task done.
                return {
                    'task_id': task_id,
                    'source': source,
                    'index_name': index_name,
                    'original_filename': original_filename,
                    'chunks_stored': 0,
                    'storage_time': 0,
                    'es_result': {
                        "success": False,
                        "message": "Indexing cancelled because document was deleted.",
                        "total_indexed": 0,
                        "total_submitted": 0,
                    },
                }
        except Exception as cancel_check_exc:
            logger.warning(
                f"[{self.request.id}] FORWARD TASK: Failed to check cancellation flag for task {task_id}: "
                f"{cancel_check_exc}"
            )

        chunks = processed_data.get('chunks')
        # If chunks are not in payload, try loading from Redis via the redis_key
        if (not chunks) and processed_data.get('redis_key'):
            redis_key = processed_data.get('redis_key')
            if not REDIS_BACKEND_URL:
                raise Exception(json.dumps({
                    "message": "REDIS_BACKEND_URL not configured to retrieve chunks",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": filename
                }, ensure_ascii=False))
            try:
                import redis
                client = redis.Redis.from_url(
                    REDIS_BACKEND_URL, decode_responses=True)
                cached = client.get(redis_key)
                if cached:
                    try:
                        logger.debug(
                            f"[{self.request.id}] FORWARD TASK: Retrieved Redis key '{redis_key}', payload_length={len(cached)}")
                        chunks = json.loads(cached)
                    except json.JSONDecodeError as jde:
                        # Log raw prefix to help diagnose incorrect writes
                        raw_preview = cached[:120] if isinstance(
                            cached, str) else str(type(cached))
                        logger.error(
                            f"[{self.request.id}] FORWARD TASK: JSON decode error for key '{redis_key}': {str(jde)}; raw_prefix={raw_preview!r}")
                        raise
                else:
                    # No busy-wait: release the worker slot and retry later
                    retry_num = getattr(self.request, 'retries', 0)
                    logger.info(
                        f"[{self.request.id}] FORWARD TASK: Chunks not yet available for key {redis_key}. Retry {retry_num + 1}/{FORWARD_REDIS_RETRY_MAX} in {FORWARD_REDIS_RETRY_DELAY_S}s")
                    raise self.retry(
                        countdown=FORWARD_REDIS_RETRY_DELAY_S,
                        max_retries=FORWARD_REDIS_RETRY_MAX,
                        exc=Exception(json.dumps({
                            "message": "Chunks not ready in Redis; will retry",
                            "index_name": original_index_name,
                            "task_name": "forward",
                            "source": original_source,
                            "original_filename": filename
                        }, ensure_ascii=False))
                    )
            except Retry:
                raise
            except Exception as exc:
                raise Exception(json.dumps({
                    "message": f"Failed to retrieve chunks from Redis: {str(exc)}",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": filename
                }, ensure_ascii=False))
        if processed_data.get('source'):
            original_source = processed_data.get('source')
        if processed_data.get('index_name'):
            original_index_name = processed_data.get('index_name')
        if processed_data.get('original_filename'):
            filename = processed_data.get('original_filename')
        logger.info(
            f"[{self.request.id}] FORWARD TASK: Received data for source '{original_source}' with {len(chunks) if chunks else 'None'} chunks")

        # Calculate total chunks for progress tracking
        total_chunks = len(chunks) if chunks else 0

        if chunks is None:
            raise Exception(json.dumps({
                "message": "No chunks received for forwarding",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": original_filename
            }, ensure_ascii=False))
        if len(chunks) == 0:
            logger.warning(
                f"[{self.request.id}] FORWARD TASK: Empty chunks list received for source {original_source}")
        formatted_chunks = []
        for i, chunk in enumerate(chunks):
            # Extract text and metadata
            content = chunk.get("content", "")
            metadata = chunk.get("metadata", {})

            # Validate chunk content
            if not content or len(content.strip()) == 0:
                logger.warning(
                    f"[{self.request.id}] FORWARD TASK: Chunk {i+1} has empty text content, skipping")
                continue

            file_size = get_file_size(source_type, original_source) if isinstance(
                original_source, str) else 0

            # Format as expected by the Elasticsearch API
            formatted_chunk = {
                "metadata": metadata,
                "filename": filename or (os.path.basename(original_source) if original_source and isinstance(original_source, str) else ""),
                "path_or_url": original_source,
                "content": content,
                "process_source": "Unstructured",
                "source_type": source_type,
                "file_size": file_size,
                "create_time": metadata.get("creation_date"),
                "date": metadata.get("date"),
            }
            formatted_chunks.append(formatted_chunk)

        if len(formatted_chunks) == 0:
            friendly_reason = build_friendly_reason_from_key("no_valid_chunks")
            raise Exception(json.dumps({
                "message": "No valid chunks to forward after formatting",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": original_filename,
                "friendly_reason": friendly_reason
            }, ensure_ascii=False))

        async def index_documents():
            elasticsearch_url = ELASTICSEARCH_SERVICE
            if not elasticsearch_url:
                raise Exception(json.dumps({
                    "message": "ELASTICSEARCH_SERVICE env is not set",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": original_filename
                }, ensure_ascii=False))
            route_url = f"/indices/{original_index_name}/documents"
            full_url = elasticsearch_url + route_url
            headers = {"Content-Type": "application/json"}
            if authorization:
                headers["Authorization"] = authorization
            # Add task_id header for progress tracking
            headers["X-Task-Id"] = task_id

            try:
                connector = aiohttp.TCPConnector(verify_ssl=False)
                # Increased timeout for large documents and slow ES bulk operations
                # Use generous total timeout to avoid marking long-running but successful
                # indexing as failed.
                timeout = aiohttp.ClientTimeout(total=600)

                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.post(
                        full_url,
                        headers=headers,
                        json=formatted_chunks,
                        raise_for_status=True
                    ) as response:
                        result = await response.json()
                        return result

            except aiohttp.ClientResponseError as e:
                # 400: embedding model reports chunk count exceeds concurrency
                if e.status == 400:
                    friendly_reason = build_friendly_reason_from_key(
                        "embedding_chunks_exceed_limit"
                    )
                    raise Exception(json.dumps({
                        "message": f"ElasticSearch service returned 400 Bad Request: {str(e)}",
                        "index_name": original_index_name,
                        "task_name": "forward",
                        "source": original_source,
                        "original_filename": original_filename,
                        "friendly_reason": friendly_reason
                    }, ensure_ascii=False))

                # Timeout from Elasticsearch refresh / bulk operations: stop retrying and treat as es_bulk_failed
                timeout_markers = [
                    "Connection timeout caused by",
                    "Read timed out",
                    "ReadTimeoutError"
                ]
                if any(marker in str(e) for marker in timeout_markers):
                    friendly_reason = build_friendly_reason_from_key(
                        "es_bulk_failed"
                    )
                    raise Exception(json.dumps({
                        "message": f"ElasticSearch operation timed out: {str(e)}",
                        "index_name": original_index_name,
                        "task_name": "forward",
                        "source": original_source,
                        "original_filename": original_filename,
                        "friendly_reason": friendly_reason
                    }, ensure_ascii=False))

                # 503: vector service busy: bubble up immediately, let caller decide
                if e.status == 503:
                    friendly_reason = build_friendly_reason_from_key(
                        "vector_service_busy"
                    )
                    raise Exception(json.dumps({
                        "message": f"ElasticSearch service unavailable: {str(e)}",
                        "index_name": original_index_name,
                        "task_name": "forward",
                        "source": original_source,
                        "original_filename": original_filename,
                        "friendly_reason": friendly_reason
                    }, ensure_ascii=False))

                # Other client response errors: bubble up
                raise Exception(json.dumps({
                    "message": f"ElasticSearch service unavailable: {str(e)}",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": original_filename
                }, ensure_ascii=False))
            except aiohttp.ClientConnectorError as e:
                logger.error(
                    f"[{self.request.id}] FORWARD TASK: Connection error to {full_url}: {str(e)}")
                raise Exception(json.dumps({
                    "message": f"Failed to connect to API: {str(e)}",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": original_filename
                }, ensure_ascii=False))
            except asyncio.TimeoutError as e:
                logger.warning(
                    f"[{self.request.id}] FORWARD TASK: Timeout when indexing documents: {str(e)}.")
                raise Exception(json.dumps({
                    "message": f"Timeout when indexing documents: {str(e)}",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": original_filename
                }, ensure_ascii=False))
            except Exception as e:
                logger.error(
                    f"[{self.request.id}] FORWARD TASK: Unexpected error when indexing documents: {str(e)}.")
                raise Exception(json.dumps({
                    "message": f"Unexpected error when indexing documents: {str(e)}",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": original_filename
                }, ensure_ascii=False))

        logger.info(
            f"[{self.request.id}] FORWARD TASK: Starting ES indexing for {len(formatted_chunks)} chunks to index '{original_index_name}'...")

        # Update task state with total chunks before starting vectorization
        self.update_state(
            state=states.STARTED,
            meta={
                'source': original_source,
                'index_name': original_index_name,
                'original_filename': filename,
                'task_name': 'forward',
                'start_time': start_time,
                'stage': 'vectorizing_and_storing',
                'total_chunks': total_chunks,
                'processed_chunks': 0  # Will be updated during vectorization via Redis
            }
        )

        es_result = run_async(index_documents())
        logger.debug(
            f"[{self.request.id}] FORWARD TASK: API response from main_server for source '{original_source}': {es_result}")

        if isinstance(es_result, dict) and es_result.get("success"):
            total_indexed = es_result.get("total_indexed", 0)
            total_submitted = es_result.get(
                "total_submitted", len(formatted_chunks))
            logger.debug(f"[{self.request.id}] FORWARD TASK: main_server reported {total_indexed}/{total_submitted} documents indexed successfully for '{original_source}'. Message: {es_result.get('message')}")

            if total_indexed < total_submitted:
                logger.info("Value when raise Exception:")
                logger.info(f"original_source: {original_source}")
                logger.info(f"original_index_name: {original_index_name}")
                logger.info("task_name: forward")
                logger.info(f"source: {original_source}")
                friendly_reason = build_friendly_reason_from_key(
                    "es_bulk_failed")
                raise Exception(json.dumps({
                    "message": f"Failure reported by main_server. Expected {total_submitted} chunks, indexed {total_indexed} chunks.",
                    "index_name": original_index_name,
                    "task_name": "forward",
                    "source": original_source,
                    "original_filename": original_filename,
                    "friendly_reason": friendly_reason
                }, ensure_ascii=False))
        elif isinstance(es_result, dict) and not es_result.get("success"):
            error_message = es_result.get(
                "message", "Unknown error from main_server")
            raise Exception(json.dumps({
                "message": f"main_server API error: {error_message}",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": original_filename
            }, ensure_ascii=False))
        else:
            raise Exception(json.dumps({
                "message": f"Unexpected API response format from main_server: {es_result}",
                "index_name": original_index_name,
                "task_name": "forward",
                "source": original_source,
                "original_filename": original_filename
            }, ensure_ascii=False))
        end_time = time.time()

        # Get final indexed count from result
        final_processed = 0
        if isinstance(es_result, dict) and es_result.get("success"):
            final_processed = es_result.get("total_indexed", len(chunks))

        logger.info(
            f"[{self.request.id}] FORWARD TASK: Updating task state to SUCCESS after ES indexing completion")
        self.update_state(
            state=states.SUCCESS,
            meta={
                'chunks_stored': len(chunks),
                'storage_time': end_time - start_time,
                'source': original_source,
                'index_name': original_index_name,
                'original_filename': original_filename,
                'task_name': 'forward',
                'es_result': es_result,
                'stage': 'completed',
                'total_chunks': total_chunks,
                'processed_chunks': final_processed
            }
        )

        logger.info(
            f"[{self.request.id}] FORWARD TASK: Successfully stored {len(chunks)} chunks to index {original_index_name} in {end_time - start_time:.2f}s")
        return {
            'task_id': task_id,
            'source': original_source,
            'index_name': original_index_name,
            'original_filename': original_filename,
            'chunks_stored': len(chunks),
            'storage_time': end_time - start_time,
            'es_result': es_result
        }
    except Exception as e:
        # If it's an Exception, all go here (including our custom JSON message)
        task_id = self.request.id
        try:
            error_info = json.loads(str(e))
            error_message = error_info.get('message', str(e))
            logger.error(
                f"Error forwarding chunks for index '{error_info.get('index_name', '')}': {error_message}")

            friendly_reason = error_info.get(
                'friendly_reason') or enrich_error_reason(error_message)
            reason_to_store = friendly_reason or error_message
            if len(reason_to_store) > 200:
                reason_to_store = reason_to_store[:200] + "..."

            # Save error info to Redis BEFORE re-raising
            logger.info(
                f"Attempting to save error info for task {task_id} with reason: {reason_to_store[:100]}...")
            save_error_to_redis(task_id, reason_to_store, start_time)

            self.update_state(
                meta={
                    'source': error_info.get('source', ''),
                    'index_name': error_info.get('index_name', ''),
                    'task_name': error_info.get('task_name', ''),
                    'original_filename': error_info.get('original_filename', ''),
                    'custom_error': error_message,
                    'stage': 'forward_task_failed'
                }
            )
        except Exception:
            logger.error(f"Error forwarding chunks: {str(e)}")
            # Try to save error even if parsing fails
            try:
                error_message = str(e)
                friendly_reason = enrich_error_reason(error_message)
                reason_to_store = friendly_reason or error_message
                if len(reason_to_store) > 200:
                    reason_to_store = reason_to_store[:200] + "..."
                save_error_to_redis(task_id, reason_to_store, start_time)
            except Exception:
                pass
            self.update_state(
                meta={
                    'custom_error': str(e),
                    'stage': 'forward_task_failed'
                }
            )
        raise


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.process_and_forward')
def process_and_forward(
        self,
        source: str,
        source_type: str,
        chunking_strategy: str,
        index_name: Optional[str] = None,
        original_filename: Optional[str] = None,
        authorization: Optional[str] = None,
        embedding_model_id: Optional[int] = None,
        tenant_id: Optional[str] = None
) -> str:
    """
    Combined task that chains processing and forwarding

    This task delegates to a chain of process -> forward

    Args:
        source: Source file path, URL, or text content
        source_type: source of the file("local", "minio")
        chunking_strategy: Strategy for chunking the document
        index_name: Name of the index to store documents
        original_filename: The original name of the file
        authorization: Authorization header for API calls
        embedding_model_id: Embedding model ID for chunk size configuration
        tenant_id: Tenant ID for retrieving model configuration

    Returns:
        Task ID of the chain
    """
    logger.info(
        f"Starting processing chain for {source}, original_filename={original_filename}, strategy={chunking_strategy}, index={index_name}, model_id={embedding_model_id}")

    # Create a task chain
    task_chain = chain(
        process.s(
            source=source,
            source_type=source_type,
            chunking_strategy=chunking_strategy,
            index_name=index_name,
            original_filename=original_filename,
            embedding_model_id=embedding_model_id,
            tenant_id=tenant_id
        ).set(queue='process_q'),
        forward.s(
            index_name=index_name,
            source=source,
            source_type=source_type,
            original_filename=original_filename,
            authorization=authorization
        ).set(queue='forward_q')
    )

    # Execute the chain
    result = task_chain.apply_async()
    if result is None or not hasattr(result, 'id') or result.id is None:
        logger.error(
            "Celery chain apply_async() did not return a valid result or result.id")
        return ""
    logger.info(f"Created task chain ID: {result.id}")

    return result.id


@app.task(bind=True, base=LoggingTask, name='data_process.tasks.process_sync')
def process_sync(
        self,
        source: str,
        source_type: str,
        chunking_strategy: str = "basic",
        timeout: int = 30,
        **params
) -> Dict:
    """
    Synchronous process task that returns text directly (for real-time API)

    Args:
        source: Source file path, URL, or text content
        source_type: source of the file("local", "minio")
        chunking_strategy: Strategy for chunking the document
        timeout: Timeout for the operation
        **params: Additional parameters

    Returns:
        Dict containing the extracted text and metadata
    """
    start_time = time.time()
    task_id = self.request.id

    # Check if we're in a valid Celery context before updating state
    is_celery_context = hasattr(
        self, 'request') and self.request.id is not None

    # Update task state to PROCESSING only if in Celery context
    if is_celery_context:
        self.update_state(
            state=states.STARTED,
            meta={
                'source': source,
                'source_type': source_type,
                'task_name': 'process_sync',
                'start_time': start_time,
                'sync_mode': True
            }
        )

    logger.info(
        f"Synchronous processing file: {source} with strategy: {chunking_strategy}")

    # Get the data processor instance
    actor = get_ray_actor()

    try:
        # Process the file based on the source type
        if source_type == "local":
            # The unified actor call, mapping 'file' source_type to 'local' destination
            chunks_ref = actor.process_file.remote(
                source,
                chunking_strategy,
                destination=source_type,
                task_id=task_id,
                **params
            )

            chunks = ray.get(chunks_ref)
        else:
            raise NotImplementedError(
                f"Source type '{source_type}' not yet implemented")

        end_time = time.time()
        elapsed_time = end_time - start_time

        # Extract text from chunks
        text_content = "\n\n".join(
            [chunk.get("content", "") for chunk in chunks])

        # Update task state to COMPLETE only if in Celery context
        if is_celery_context:
            self.update_state(
                state=states.SUCCESS,
                meta={
                    'chunks_count': len(chunks),
                    'processing_time': elapsed_time,
                    'source': source,
                    'task_name': 'process_sync',
                    'text_length': len(text_content),
                    'sync_mode': True
                }
            )

        logger.info(
            f"Synchronously processed {len(chunks)} chunks from {source} in {elapsed_time:.2f}s")

        return {
            'task_id': task_id,
            'source': source,
            'text': text_content,
            'chunks': chunks,
            'chunks_count': len(chunks),
            'processing_time': elapsed_time,
            'text_length': len(text_content)
        }

    except Exception as e:
        logger.error(f"Error synchronously processing file {source}: {str(e)}")

        # Update task state to FAILURE with custom metadata only if in Celery context
        if is_celery_context:
            self.update_state(
                meta={
                    'source': source,
                    'task_name': 'process_sync',
                    'custom_error': str(e),
                    'sync_mode': True,
                    'stage': 'sync_processing_failed'
                }
            )

        # Re-raise to let Celery handle exception serialization
        raise
