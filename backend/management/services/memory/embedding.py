# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Vectorize Memory text through the signed Runtime model interface."""

import logging

from nexent.memory.embedding_model import EmbeddingModelInfo

logger = logging.getLogger(__name__)


async def embed_memory_text(
    text: str, model: EmbeddingModelInfo, user_id: str, tenant_id: str,
) -> list[float] | None:
    if type(model.model_id) is not int or model.model_id <= 0:
        return None

    from management.clients.model import embed_query

    try:
        vector = await embed_query(
            model_id=model.model_id, revision=model.revision, query=text, user_id=user_id, tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning(
            "Unable to vectorize memory text tenant=%s model_id=%s error_type=%s",
            tenant_id, model.model_id, type(exc).__name__,
        )
        return None
    if len(vector) != model.dimension:
        logger.warning("Memory vector dimension mismatch tenant=%s model_id=%s", tenant_id, model.model_id)
        return None
    return vector
