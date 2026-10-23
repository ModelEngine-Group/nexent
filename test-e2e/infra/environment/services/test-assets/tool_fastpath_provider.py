"""Nonce-scoped OpenAI responses for real deployed fast-path acceptance."""

import json
import re
import time
from dataclasses import dataclass

from cmsr_provider import controlled
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse


router = APIRouter()


@dataclass
class Scenario:
    responses: list[str]
    calls: int = 0


scenarios: dict[str, Scenario] = {}


def lookup(nonce):
    if not re.fullmatch(r"[a-f0-9]{32}", nonce) or nonce not in scenarios:
        raise HTTPException(404, "Unknown TFP scenario")
    return scenarios[nonce]


@router.post("/tfp/{nonce}/reset")
async def reset(nonce: str, request: Request):
    controlled(request)
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise HTTPException(400, "Invalid nonce")
    responses = (await request.json()).get("responses")
    if (
        not isinstance(responses, list)
        or not 1 <= len(responses) <= 6
        or any(not isinstance(text, str) or not text or len(text) > 8192 for text in responses)
    ):
        raise HTTPException(400, "Invalid scripted responses")
    scenarios[nonce] = Scenario(responses)
    return {"ready": True}


@router.get("/tfp/{nonce}/state")
async def state(nonce: str, request: Request):
    controlled(request)
    item = lookup(nonce)
    return {"calls": item.calls, "expected_calls": len(item.responses)}


@router.delete("/tfp/{nonce}")
async def delete(nonce: str, request: Request):
    controlled(request)
    lookup(nonce)
    del scenarios[nonce]
    return {"deleted": True}


def completion(nonce, content):
    return {
        "id": "chatcmpl-tfp-" + nonce,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "tfp-controlled",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


@router.post("/tfp/{nonce}/v1/chat/completions")
async def completions(nonce: str, request: Request):
    item = lookup(nonce)
    body = await request.json()
    # A fixture-specific system constraint identifies the actual Agent loop.
    # Title generation can use the same model and token budget as that loop.
    system = [message.get("content") for message in body.get("messages", []) if message.get("role") == "system"]
    auxiliary = not body.get("stream") or "TFP_AGENT_SCENARIO_" + nonce not in json.dumps(system)
    if auxiliary and not body.get("stream"):
        return completion(nonce, "TFP verification")
    if not auxiliary and item.calls >= len(item.responses):
        raise HTTPException(409, "Unexpected extra Agent turn")
    content = "TFP verification" if auxiliary else item.responses[item.calls]
    if "{{TFP_ARTIFACT_URL}}" in content:
        # Generate the final link only from the actual tool observation in the
        # provider request. No fabricated path can stand in for a real upload.
        observed = json.dumps(body.get("messages", []))
        matches = set(
            re.findall(
                r"s3://[a-zA-Z0-9_.-]+/workspace/[^\s/\"\\]+/[a-f0-9]{32}/outputs/tfp-" + nonce + r"\.txt", observed
            )
        )
        if len(matches) != 1:
            raise HTTPException(409, "Actual report upload observation is missing or ambiguous")
        content = content.replace("{{TFP_ARTIFACT_URL}}", matches.pop())
    if not auxiliary:
        item.calls += 1

    async def chunks():
        for offset in range(0, len(content), 16):
            yield (
                "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-tfp-" + nonce,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "tfp-controlled",
                        "choices": [
                            {"index": 0, "delta": {"content": content[offset : offset + 16]}, "finish_reason": None}
                        ],
                    }
                )
                + "\n\n"
            )
        yield (
            "data: "
            + json.dumps(
                {
                    "id": "chatcmpl-tfp-" + nonce,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "tfp-controlled",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(chunks(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})
