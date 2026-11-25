# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Stream one provider connectivity probe within Runtime and own its cancellation."""

import asyncio
import logging
from uuid import uuid4

from nexent.core.model_service.profiles.probe_diagnostics import _probe_diagnostic

logger = logging.getLogger(__name__)

_MODEL_TYPES = {"llm", "chat", "embedding", "multi_embedding", "rerank", "vlm", "vlm2", "vlm3", "vlm4", "stt", "tts"}


def log_probe_failure(model_type: str, error: dict) -> None:
    logger.warning(
        "event=model_connectivity_failed request_id=%s model_type=%s category=%s http_status=%s",
        error["request_id"],
        model_type if model_type in _MODEL_TYPES else "unknown",
        error["category"],
        error.get("http_status"),
    )


async def probe_model_profile(profile, key, *, http_headers=None):
    """Probe through the production streamed sender without mutating configuration."""
    from nexent.core.model_service.contracts import ModelMessage, ModelRequest
    from nexent.core.model_service.registry import AuthenticationRegistry
    from nexent.core.model_service.service import ModelService, ModelServiceError
    from nexent.core.models.retry import DEFAULT_MODEL_RETRY

    auth = AuthenticationRegistry()
    service = ModelService(lambda captured: auth.sender_for(captured, lambda _tenant, _reference: key, http_headers=http_headers),
                           retry_policy=DEFAULT_MODEL_RETRY)
    request_id = uuid4().hex
    call = ModelRequest(request_id=request_id, outlet_id=profile.outlet_id,
        config_revision=profile.config_revision, stream=True, purpose="connection_validation",
        messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "Hello"}])])
    error = None
    ok = False
    try:
        async with service.astream(call, profile) as events:
            async for event in events:
                if event.type == "error":
                    error = _probe_diagnostic(event.error)
                elif event.type == "message_completed":
                    ok = bool(event.message.content_parts or event.message.tool_calls or event.message.refusal)
        if not ok and error is None:
            error = {"category": "MODEL_EMPTY_RESPONSE", "scope": "model"}
    except ModelServiceError as failure:
        ok = False
        error = _probe_diagnostic(failure.error)
    if ok:
        return {"ok": True, "error": None}
    error["request_id"] = request_id
    log_probe_failure("llm", error)
    return {"ok": False, "error": error}


async def probe_until_disconnect(profile, key, headers, is_disconnected):
    task = asyncio.create_task(probe_model_profile(profile, key, http_headers=headers),
                               name="runtime-model-outlet-connectivity")
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.05)
            if not task.done() and await is_disconnected():
                raise asyncio.CancelledError()
        return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
