import logging
from typing import Any, Dict, List, Optional

import ray

from consts.const import RAY_ACTOR_NUM_CPUS
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
            f"[RayActor] Processing file: {source}, destination: {destination}")

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

        if not chunks:
            logger.warning(
                f"[RayActor] file_process returned no chunks for {source}")
            return []

        logger.debug(
            f"[RayActor] file_process returned {len(chunks)} chunks, returning as is.")
        return chunks
