# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Deadline-aware embedding for automatic memory operations."""

import asyncio
import logging
import math

import httpx
import requests

from infrastructure.memory_embedding_health import (
    admit_embedding, embedding_circuit_key, record_embedding_failure, record_embedding_success,
)
from infrastructure.memory_io import remaining_time
from nexent.core.gateway.modality.embedding.openai import InvalidEmbeddingResponse
from nexent.memory.embedding_model import EmbeddingModelInfo
from nexent.core.gateway.modality.embedding.embedding_adapter import EmbeddingRequest

logger = logging.getLogger(__name__)


async def compute_runtime_embedding(
    content: str, model_info: EmbeddingModelInfo, *, tenant_id: str, deadline: float, client,
) -> list[float] | None:
    """Make one bounded attempt and open the circuit only for upstream failures."""
    if remaining_time(deadline) <= 0:
        return None
    key = embedding_circuit_key(tenant_id, model_info)
    token = admit_embedding(key)
    if token is None:
        logger.info("event=memory_embedding_skipped reason=circuit_open tenant_id=%s", tenant_id)
        return None
    timeout = remaining_time(deadline) - 0.05
    if timeout <= 0:
        return None
    try:
        async with asyncio.timeout(timeout):
            if callable(getattr(client, "get_embeddings_with_deadline", None)):
                vectors = await client.get_embeddings_with_deadline(content, timeout=timeout)
            else:
                vectors = await client.invoke(EmbeddingRequest(
                    [content], timeout=timeout, retries=0, worker_lane="model-embedding",
                ))
        vector = vectors[0] if isinstance(vectors, list) and len(vectors) == 1 else None
        if not isinstance(vector, list) or len(vector) != model_info.dimension or not vector:
            raise InvalidEmbeddingResponse("Unexpected embedding dimension")
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
            raise InvalidEmbeddingResponse("Embedding vector contains invalid values")
    except Exception as exc:
        status = (exc.response.status_code if isinstance(exc, (httpx.HTTPStatusError, requests.HTTPError))
                  and exc.response is not None else 0)
        if (
            isinstance(exc, (TimeoutError, httpx.TransportError, requests.Timeout, requests.ConnectionError, InvalidEmbeddingResponse))
            or status in (408, 429)
            or status >= 500
        ):
            record_embedding_failure(key)
        logger.warning("event=memory_embedding_failed tenant_id=%s error_type=%s status=%s",
                       tenant_id, type(exc).__name__, status or None)
        return None
    record_embedding_success(key, token)
    return [float(value) for value in vector] if remaining_time(deadline) > 0 else None
