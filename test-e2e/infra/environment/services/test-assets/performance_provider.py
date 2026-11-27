# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bounded OpenAI-compatible stream used by the Daily conversation load case."""

import asyncio
import json
import re
import time
from collections import Counter
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()
active = Counter()


@router.get("/performance/{run}/v1/models")
async def models(run: str):
    return {"object": "list", "data": [{"id": "daily-fixed-stream", "object": "model"}]}


@router.get("/performance/{run}/active")
async def activity(run: str):
    return {"model_streams": active[run]}


@router.post("/performance/{run}/v1/chat/completions")
async def complete(run: str, request: Request):
    payload = await request.json()
    prompt = str(payload.get("messages", [])[-1:])
    marker = re.findall(r"D5PERF_[a-f0-9]{12}", prompt)
    answer = marker[-1] if marker else "Daily fixture ready"
    base = {"id": "chatcmpl-" + uuid4().hex, "model": "daily-fixed-stream", "created": int(time.time())}
    if not payload.get("stream"):
        return {**base, "object": "chat.completion", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
        ], "usage": {"prompt_tokens": 8, "completion_tokens": 8, "total_tokens": 16}}

    async def stream():
        active[run] += 1
        try:
            for index, delta in enumerate(({"role": "assistant"}, {"content": answer}, {"content": " completed"}, {})):
                if index:
                    await asyncio.sleep(4 if index == 1 and "D5PERF_HOLD" in prompt else 0.25)
                chunk = {**base, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": delta, "finish_reason": "stop" if index == 3 else None}
                ]}
                yield "data: " + json.dumps(chunk) + "\n\n"
            yield "data: [DONE]\n\n"
        finally:
            active[run] -= 1
            if not active[run]:
                del active[run]

    return StreamingResponse(stream(), media_type="text/event-stream")
