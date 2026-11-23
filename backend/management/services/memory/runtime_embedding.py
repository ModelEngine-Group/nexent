# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bound automatic Memory embedding through the signed Runtime interface."""

import asyncio
import logging

from contracts.agentos import EmbeddingInvocation
from infrastructure.memory_io import remaining_time
from management.clients.model import _model_client
from nexent.memory.embedding_model import EmbeddingModelInfo

logger = logging.getLogger(__name__)


async def compute_runtime_embedding(
    content: str, model_info: EmbeddingModelInfo, *, tenant_id: str, user_id: str, deadline: float,
) -> list[float] | None:
    timeout = remaining_time(deadline) - 0.05
    if timeout <= 0 or model_info.model_id is None:
        return None
    try:
        async with asyncio.timeout(timeout):
            result = await _model_client().invoke_model(EmbeddingInvocation(
                model_id=model_info.model_id, expected_revision=model_info.revision,
                input=[content], memory_timeout_seconds=timeout,
            ), user_id, tenant_id)
        output = result.output
        if isinstance(output, list) and len(output) == 1 and remaining_time(deadline) > 0:
            return output[0]
    except Exception as exc:
        logger.warning("event=memory_embedding_failed tenant_id=%s error_type=%s", tenant_id, type(exc).__name__)
    return None
