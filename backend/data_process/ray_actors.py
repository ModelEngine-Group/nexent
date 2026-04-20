import logging
import json
import time
from typing import Any, Dict, List, Optional

import ray

from consts.const import RAY_ACTOR_NUM_CPUS, REDIS_BACKEND_URL, DEFAULT_EXPECTED_CHUNK_SIZE, DEFAULT_MAXIMUM_CHUNK_SIZE
from database.attachment_db import get_file_stream
from database.model_management_db import get_model_by_model_id
from nexent.data_process import DataProcessCore

logger = logging.getLogger("data_process.ray_actors")
# This now controls the number of CPUs requested by each DataProcessorRayActor instance.
# It allows a single file processing task to potentially use more than one core if the
# underlying processing library (e.g., unstructured) can leverage it.


@ray.remote(num_cpus=RAY_ACTOR_NUM_CPUS)
class DataProcessorRayActor:
    """
    Ray actor for handling data processing tasks.
    Encapsulates the DataProcessCore to be used in a Ray cluster.
    """

    def __init__(self):
        logger.info(
            f"Ray actor initialized using {RAY_ACTOR_NUM_CPUS} CPU cores...")
        self._processor = DataProcessCore()

    def ping(self) -> bool:
        """Lightweight health check used by prewarm logic."""
        return True

    def _prepare_process_params(
        self,
        task_id: Optional[str],
        model_id: Optional[int],
        tenant_id: Optional[str],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Normalize task/model-related processing params.
        """
        process_params = dict(params)
        if task_id:
            process_params["task_id"] = task_id

        if not (model_id and tenant_id):
            return process_params

        try:
            model_record = get_model_by_model_id(
                model_id=model_id, tenant_id=tenant_id)
            if not model_record:
                logger.warning(
                    f"[RayActor] Embedding model with ID {model_id} not found for tenant '{tenant_id}', using default chunk sizes")
                return process_params

            expected_chunk_size = model_record.get(
                "expected_chunk_size", DEFAULT_EXPECTED_CHUNK_SIZE)
            maximum_chunk_size = model_record.get(
                "maximum_chunk_size", DEFAULT_MAXIMUM_CHUNK_SIZE)
            model_name = model_record.get("display_name")

            process_params["max_characters"] = maximum_chunk_size
            process_params["new_after_n_chars"] = expected_chunk_size

            logger.info(
                f"[RayActor] Using chunk sizes from embedding model '{model_name}' (ID: {model_id}): "
                f"max_characters={maximum_chunk_size}, new_after_n_chars={expected_chunk_size}")
        except Exception as e:
            logger.warning(
                f"[RayActor] Failed to retrieve chunk sizes from embedding model ID {model_id}: {e}. Using default chunk sizes")
        return process_params

    def _run_file_process(
        self,
        file_data: bytes,
        filename: str,
        chunking_strategy: str,
        process_params: Dict[str, Any],
        log_subject: str,
    ) -> List[Dict[str, Any]]:
        chunks = self._processor.file_process(
            file_data=file_data,
            filename=filename,
            chunking_strategy=chunking_strategy,
            **process_params
        )

        if chunks is None:
            logger.warning(
                f"[RayActor] file_process returned None for {log_subject}='{filename}'")
            return []
        if not isinstance(chunks, list):
            logger.error(
                f"[RayActor] file_process returned non-list type {type(chunks)} for {log_subject}='{filename}'")
            return []
        if len(chunks) == 0:
            logger.warning(
                f"[RayActor] file_process returned empty list for {log_subject}='{filename}'")
            return []

        logger.info(
            f"[RayActor] Processing done: produced {len(chunks)} chunks for {log_subject}='{filename}'")
        return chunks

    def process_file(
        self,
        source: str,
        chunking_strategy: str,
        destination: str,
        task_id: Optional[str] = None,
        model_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        **params
    ) -> List[Dict[str, Any]]:
        """
        Process a file, auto-detecting its type using DataProcessCore.file_process.

        Args:
            source (str): The file path or URL.
            chunking_strategy (str): The strategy for chunking the file.
            destination (str): The source type of the file, e.g., 'local', 'minio'.
            task_id (str, optional): The task ID for processing. Defaults to None.
            model_id (int, optional): The embedding model ID for retrieving chunk size parameters. Defaults to None.
            tenant_id (str, optional): The tenant ID for retrieving model configuration. Defaults to None.
            **params: Additional parameters for the processing task.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries representing the processed chunks.
        """
        logger.info(
            f"[RayActor] Processing start: source='{source}', destination='{destination}', strategy='{chunking_strategy}', task_id='{task_id}', model_id='{model_id}'")
        process_params = self._prepare_process_params(
            task_id=task_id,
            model_id=model_id,
            tenant_id=tenant_id,
            params=params,
        )

        try:
            fetch_start = time.perf_counter()
            file_stream = get_file_stream(source)
            if file_stream is None:
                raise FileNotFoundError(
                    f"Unable to fetch file from URL: {source}")
            file_data = file_stream.read()
            fetch_elapsed = time.perf_counter() - fetch_start
            logger.info(
                f"[RayActor] Fetch file bytes done: destination='{destination}', source='{source}', "
                f"bytes={len(file_data)}, elapsed={fetch_elapsed:.3f}s")
        except Exception as e:
            logger.error(f"Failed to fetch file from {source}: {e}")
            raise

        return self._run_file_process(
            file_data=file_data,
            filename=source,
            chunking_strategy=chunking_strategy,
            process_params=process_params,
            log_subject="source",
        )

    def process_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        chunking_strategy: str,
        task_id: Optional[str] = None,
        model_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        **params
    ) -> List[Dict[str, Any]]:
        """
        Process in-memory file bytes, auto-detecting its type using DataProcessCore.file_process.
        """
        logger.info(
            f"[RayActor] Processing bytes: filename='{filename}', strategy='{chunking_strategy}', task_id='{task_id}', model_id='{model_id}'"
        )
        process_params = self._prepare_process_params(
            task_id=task_id,
            model_id=model_id,
            tenant_id=tenant_id,
            params=params,
        )

        return self._run_file_process(
            file_data=file_bytes,
            filename=filename,
            chunking_strategy=chunking_strategy,
            process_params=process_params,
            log_subject="filename",
        )

    def split_file(
        self,
        source: str,
        destination: str,
        task_id: Optional[str] = None,
        max_size: int = 5 * 1024 * 1024,
        file_data: Optional[bytes] = None,
        **params
    ) -> List[bytes]:
        """
        Split file into parts using DataProcessCore.file_split and return raw bytes list.
        """
        logger.info(
            f"[RayActor] Splitting file: source='{source}', destination='{destination}', task_id='{task_id}', max_size={max_size}"
        )

        if file_data is None:
            try:
                fetch_start = time.perf_counter()
                file_stream = get_file_stream(source)
                if file_stream is None:
                    raise FileNotFoundError(
                        f"Unable to fetch file from URL: {source}")
                file_data = file_stream.read()
                fetch_elapsed = time.perf_counter() - fetch_start
                logger.info(
                    f"[RayActor] Fetch file bytes for split done: destination='{destination}', source='{source}', "
                    f"bytes={len(file_data)}, elapsed={fetch_elapsed:.3f}s")
            except Exception as e:
                logger.error(f"Failed to fetch file from {source}: {e}")
                raise

        split_start = time.perf_counter()
        parts = self._processor.file_split(
            file_data=file_data,
            filename=source,
            max_size=max_size,
            **params
        )
        split_elapsed = time.perf_counter() - split_start

        if not parts:
            logger.info(
                f"[RayActor] Split done: destination='{destination}', source='{source}', "
                f"parts=0, elapsed={split_elapsed:.3f}s")
            return []

        bytes_parts: List[bytes] = []
        for part in parts:
            try:
                bytes_parts.append(part.getvalue())
            except Exception:
                continue

        logger.info(
            f"[RayActor] Split done: destination='{destination}', source='{source}', "
            f"parts={len(bytes_parts)}, elapsed={split_elapsed:.3f}s")
        return bytes_parts

    def store_chunks_in_redis(self, redis_key: str, chunks: List[Dict[str, Any]]) -> bool:
        """
        Store processed chunks into Redis under a given key.

        This is used to decouple Celery task execution from Ray processing, allowing
        Celery to submit work and return immediately while Ray persists results for
        a subsequent step to retrieve.
        """
        if not REDIS_BACKEND_URL:
            logger.error(
                "REDIS_BACKEND_URL is not configured; cannot store chunks.")
            return False
        try:
            import redis
            client = redis.Redis.from_url(
                REDIS_BACKEND_URL, decode_responses=True)
            # Use a compact JSON for storage
            if chunks is None:
                logger.error(
                    f"[RayActor] store_chunks_in_redis received None chunks for key '{redis_key}'")
                serialized = json.dumps([])
            else:
                try:
                    serialized = json.dumps(chunks, ensure_ascii=False)
                except Exception as ser_exc:
                    logger.error(
                        f"[RayActor] JSON serialization failed for key '{redis_key}': {ser_exc}")
                    # Fallback to empty list to avoid poisoning Redis with invalid data
                    serialized = json.dumps([])
            client.set(redis_key, serialized)
            # Optionally set an expiration to avoid leaks (e.g., 2 hours)
            client.expire(redis_key, 2 * 60 * 60)
            try:
                count_logged = len(chunks) if isinstance(chunks, list) else 0
            except Exception:
                count_logged = 0
            logger.info(
                f"[RayActor] Stored {count_logged} chunks in Redis at key '{redis_key}', value_len={len(serialized)}")
            return True
        except Exception as exc:
            logger.error(
                f"Failed to store chunks in Redis at key {redis_key}: {exc}")
            return False
