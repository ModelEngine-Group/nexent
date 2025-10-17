import logging
import json
from typing import Any, Dict, List, Optional

import ray

from consts.const import RAY_ACTOR_NUM_CPUS, REDIS_BACKEND_URL
from database.attachment_db import get_file_stream
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

    def process_file(
        self,
        source: str,
        chunking_strategy: str,
        destination: str,
        task_id: Optional[str] = None,
        **params
    ) -> List[Dict[str, Any]]:
        """
        Process a file, auto-detecting its type using DataProcessCore.file_process.

        Args:
            source (str): The file path or URL.
            chunking_strategy (str): The strategy for chunking the file.
            destination (str): The source type of the file, e.g., 'local', 'minio'.
            task_id (str, optional): The task ID for processing. Defaults to None.
            **params: Additional parameters for the processing task.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries representing the processed chunks.
        """
        logger.info(
            f"[RayActor] Processing start: source='{source}', destination='{destination}', strategy='{chunking_strategy}', task_id='{task_id}'")

        if task_id:
            params['task_id'] = task_id

        try:
            file_stream = get_file_stream(source)
            if file_stream is None:
                raise FileNotFoundError(
                    f"Unable to fetch file from URL: {source}")
            file_data = file_stream.read()
        except Exception as e:
            logger.error(f"Failed to fetch file from {source}: {e}")
            raise

        chunks = self._processor.file_process(
            file_data=file_data,
            filename=source,
            chunking_strategy=chunking_strategy,
            **params
        )

        if chunks is None:
            logger.warning(
                f"[RayActor] file_process returned None for source='{source}'")
            return []
        if not isinstance(chunks, list):
            logger.error(
                f"[RayActor] file_process returned non-list type {type(chunks)} for source='{source}'")
            return []
        if len(chunks) == 0:
            logger.warning(
                f"[RayActor] file_process returned empty list for source='{source}'")
            return []

        logger.info(
            f"[RayActor] Processing done: produced {len(chunks)} chunks for source='{source}'")
        return chunks

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
