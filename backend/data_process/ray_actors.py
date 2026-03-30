from io import BytesIO
import logging
import json
from typing import Any, Dict, List, Optional

import ray

from consts.const import (
    RAY_ACTOR_NUM_CPUS,
    REDIS_BACKEND_URL,
    DEFAULT_EXPECTED_CHUNK_SIZE,
    DEFAULT_MAXIMUM_CHUNK_SIZE,
    TABLE_TRANSFORMER_MODEL_PATH,
    UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH,
)
from database.attachment_db import build_s3_url, get_file_stream, upload_fileobj
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

        if task_id:
            params['task_id'] = task_id

        self._apply_model_chunk_sizes(
            model_id=model_id, tenant_id=tenant_id, params=params)
        self._apply_model_paths(params)
        file_data = self._read_file_bytes(source)

        result = self._processor.file_process(
            file_data=file_data,
            filename=source,
            chunking_strategy=chunking_strategy,
            **params
        )
        chunks, images_info = self._normalize_processor_result(result)
        if images_info:
            self._append_image_chunks(
                source=source, chunks=chunks, images_info=images_info)

        chunks = self._validate_chunks(chunks, source)
        if not chunks:
            return []

        logger.info(
            f"[RayActor] Processing done: produced {len(chunks)} chunks for source='{source}'")
        return chunks

    def _apply_model_paths(self, params: Dict[str, Any]) -> None:
        params["table_transformer_model_path"] = TABLE_TRANSFORMER_MODEL_PATH
        params[
            "unstructured_default_model_initialize_params_json_path"
        ] = UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH

    def _apply_model_chunk_sizes(
        self,
        model_id: Optional[int],
        tenant_id: Optional[str],
        params: Dict[str, Any],
    ) -> None:
        if not (model_id and tenant_id):
            return

        try:
            model_record = get_model_by_model_id(
                model_id=model_id, tenant_id=tenant_id)
            if not model_record:
                logger.warning(
                    f"[RayActor] Embedding model with ID {model_id} not found for tenant '{tenant_id}', using default chunk sizes")
                return

            expected_chunk_size = model_record.get(
                'expected_chunk_size', DEFAULT_EXPECTED_CHUNK_SIZE)
            maximum_chunk_size = model_record.get(
                'maximum_chunk_size', DEFAULT_MAXIMUM_CHUNK_SIZE)
            model_name = model_record.get('display_name')
            model_type = model_record.get('model_type')

            params['max_characters'] = maximum_chunk_size
            params['new_after_n_chars'] = expected_chunk_size
            if model_type:
                params['model_type'] = model_type

            logger.info(
                f"[RayActor] Using chunk sizes from embedding model '{model_name}' (ID: {model_id}): "
                f"max_characters={maximum_chunk_size}, new_after_n_chars={expected_chunk_size}")
        except Exception as e:
            logger.warning(
                f"[RayActor] Failed to retrieve chunk sizes from embedding model ID {model_id}: {e}. Using default chunk sizes")

    def _read_file_bytes(self, source: str) -> bytes:
        try:
            file_stream = get_file_stream(source)
            if file_stream is None:
                raise FileNotFoundError(
                    f"Unable to fetch file from URL: {source}")
            return file_stream.read()
        except Exception as e:
            logger.error(f"Failed to fetch file from {source}: {e}")
            raise

    def _normalize_processor_result(
        self, result: Any
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if isinstance(result, tuple) and len(result) == 2:
            chunks, images_info = result
            return chunks or [], images_info or []
        return result or [], []

    def _append_image_chunks(
        self,
        source: str,
        chunks: List[Dict[str, Any]],
        images_info: List[Dict[str, Any]],
    ) -> None:
        folder = "images_in_attachments"
        for index, image_data in enumerate(images_info):
            if not isinstance(image_data, dict):
                logger.warning(
                    f"[RayActor] Skipping image entry at index {index}: unexpected type {type(image_data)}"
                )
                continue
            if "image_bytes" not in image_data:
                logger.warning(
                    f"[RayActor] Skipping image entry at index {index}: missing image_bytes"
                )
                continue

            img_obj = BytesIO(image_data["image_bytes"])
            result = upload_fileobj(
                file_obj=img_obj,
                file_name=f"{index}.{image_data['image_format']}",
                prefix=folder)
            image_url = build_s3_url(result.get("object_name", ""))

            image_data["source_file"] = source
            image_data["image_url"] = image_url

            chunks.append({
                "content": json.dumps({
                    "source_file": source,
                    "position": image_data["position"],
                    "image_url": image_url,
                }),
                "filename": source,
                "metadata": {
                    "chunk_index": len(chunks) + index,
                    "process_source": "UniversalImageExtractor",
                    "image_url": image_url,
                }
            })

    def _validate_chunks(
        self, chunks: Any, source: str
    ) -> List[Dict[str, Any]]:
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
