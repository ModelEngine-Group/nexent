"""Controlled OpenAI-compatible fault provider (mounted at /fault/v1).

Minimal by design: built strictly from what the suite cases consume, so the
suite can retire test-assets without losing fault-injection coverage for
model flows. Model records are configured with
``base_url = http://<host>:30090/fault/v1`` (OpenAI-compatible gateways are
root-mounted by convention).

Implemented behaviours (each backed by a suite case):
  - POST /fault/v1/chat/completions
      * payload containing "force-regenerate-name-failure" -> 503
        (D3 regenerate-name case: the product retries 5x, then falls back
        to the ``_1`` suffix naming);
      * payload containing "provider 429" -> the first TWO calls per marker
        return 429, then the provider recovers (D5 REL-02 provider-failure
        case: agent run must surface the rate limit and still converge);
      * otherwise -> 200 with the fixed recovery content, either as a plain
        completion or as SSE chunks when ``stream: true``.

Deliberately NOT implemented (no suite case needs them — extend only when a
case does): GET /fault/v1/models (LLM model creation performs no connectivity
probe, model_management_service only verifies embedding models), the
"failure probe" / "forced fault" markers, and usage statistics.

Attempt counters are in-memory only (fresh per process/batch), matching the
original test-assets semantics. The unified control plane additionally
supports scheduled failures scoped to this route set
(``POST /_mock/fail-next {"service": "fault"}``) and ``POST /_reset`` clears
the attempt counters.
"""
import json
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, StreamingResponse

_RECOVERY_CONTENT = "CONTROLLED_PROVIDER_RECOVERED_AFTER_RATE_LIMIT"


class FaultAttemptState:
    """Per-marker attempt counters (in-memory, fresh per process)."""

    def __init__(self) -> None:
        self.attempts: Dict[str, int] = {}

    def record(self, marker: str) -> int:
        attempt = self.attempts.get(marker, 0) + 1
        self.attempts[marker] = attempt
        return attempt

    def reset(self) -> None:
        self.attempts.clear()


def create_router(state: Optional[FaultAttemptState] = None) -> APIRouter:
    fault_state = state if state is not None else FaultAttemptState()
    router = APIRouter(prefix="/fault")

    @router.post("/v1/chat/completions")
    def chat_completions(payload: Dict[str, Any] = Body(...)):
        # Marker detection stringifies the whole payload, so markers hidden
        # anywhere in the request (e.g. inside the task description that the
        # product forwards as the user prompt) trigger the fault.
        text = str(payload).lower()
        if "force-regenerate-name-failure" in text:
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "controlled name-regeneration provider failure"}},
            )
        if "provider 429" in text:
            marker = str((payload.get("messages") or [{}])[-1].get("content") or text)
            attempt = fault_state.record(marker)
            if attempt <= 2:
                return JSONResponse(
                    status_code=429,
                    content={"error": {"message": "controlled upstream rate limit"}},
                )

        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        if payload.get("stream"):
            def stream():
                chunks = [
                    {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "controlled-fault-model",
                        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                    },
                    {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "controlled-fault-model",
                        "choices": [{"index": 0, "delta": {"content": _RECOVERY_CONTENT}, "finish_reason": None}],
                    },
                    {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "controlled-fault-model",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    },
                ]
                for chunk in chunks:
                    yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(stream(), media_type="text/event-stream")

        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "controlled-fault-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": _RECOVERY_CONTENT},
                    "finish_reason": "stop",
                }
            ],
        }

    return router
