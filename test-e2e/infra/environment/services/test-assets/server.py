"""Controlled HTTP assets and failure providers for the isolated daily suite."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
import uvicorn
from cmsr_provider import router as cmsr_router
from runtime_fault_provider import router as runtime_fault_router
from prompt_fault_provider import router as prompt_fault_router


app = FastAPI(title="nexent-controlled-test-assets")
app.include_router(cmsr_router)
app.include_router(runtime_fault_router)
app.include_router(prompt_fault_router)
TEST_ROOT = Path(
    os.environ.get("NEXENT_TEST_HOME", str(Path(__file__).resolve().parents[2]))
).resolve()
WIRE_LOG = Path(os.environ["NEXENT_TEST_API_WIRE_LOG"]) if os.environ.get("NEXENT_TEST_API_WIRE_LOG") else None
FAULT_ATTEMPTS: dict[str, int] = {}


def record_wire(tool: str, payload: dict) -> None:
    if WIRE_LOG is None:
        return
    WIRE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with WIRE_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"tool": tool, **payload}, ensure_ascii=False) + "\n")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/test-api/code", operation_id="get_api_test_code")
async def test_api_code() -> dict:
    result = {"code": "API-NX-92831"}
    record_wire("get_api_test_code", {"result": result})
    return result


@app.get("/assets/image.jpg")
async def image() -> FileResponse:
    return FileResponse(TEST_ROOT / "assets" / "images" / "肝脏图片.jpg", media_type="image/jpeg")


@app.get("/assets/video.mp4")
async def video() -> FileResponse:
    return FileResponse(TEST_ROOT / "assets" / "video" / "20260829_110109.mp4", media_type="video/mp4")


@app.get("/assets/large.md")
async def large_markdown() -> PlainTextResponse:
    nodes = "\n".join(f"  N{i}[Node {i}] --> N{i + 1}[Node {i + 1}]" for i in range(120))
    paragraphs = "\n\n".join(
        f"## Section {i}\nControlled markdown performance marker {i}. " + "content " * 80
        for i in range(40)
    )
    return PlainTextResponse(f"# Controlled large Markdown\n\n```mermaid\ngraph TD\n{nodes}\n```\n\n{paragraphs}")


@app.get("/api/data-management/datasets/{dataset_id}/files/{file_id}/download")
async def datamate_download(dataset_id: str, file_id: str) -> PlainTextResponse:
    return PlainTextResponse(f"CONTROLLED_DATAMATE_ASSET:{dataset_id}:{file_id}\n")


@app.post("/idata/apiaccess/modelmate/north/machine/v1/knowledgeSpaces/query")
async def idata_knowledge_spaces() -> dict:
    return {"code": "1", "msg": "success", "data": [], "msgParams": None}


@app.get("/dify/v1/datasets")
async def dify_datasets() -> dict:
    return {"data": [], "has_more": False, "limit": 20, "page": 1, "total": 0}


@app.get("/ragflow/api/v1/datasets")
@app.get("/api/v1/datasets")
async def ragflow_datasets() -> dict:
    return {"code": 0, "data": [], "message": "success"}


@app.get("/fault/v1/models")
async def fault_models() -> dict:
    return {"object": "list", "data": [{"id": "controlled-fault-model", "object": "model"}]}


@app.post("/fault/v1/chat/completions")
async def fault_chat(request: Request):
    payload = await request.json()
    text = str(payload).lower()
    if "force-regenerate-name-failure" in text:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "controlled name-regeneration provider failure"}},
        )
    if any(marker in text for marker in ("provider 429", "failure probe", "forced fault")):
        marker = str((payload.get("messages") or [{}])[-1].get("content") or text)
        attempt = FAULT_ATTEMPTS.get(marker, 0) + 1
        FAULT_ATTEMPTS[marker] = attempt
        if attempt <= 2:
            return JSONResponse(status_code=429, content={"error": {"message": "controlled upstream rate limit"}})
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    content = "CONTROLLED_PROVIDER_RECOVERED_AFTER_RATE_LIMIT"
    if payload.get("stream"):
        async def stream():
            chunks = [
                {"id": completion_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": "controlled-fault-model", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"id": completion_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": "controlled-fault-model", "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]},
                {"id": completion_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": "controlled-fault-model", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
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
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protocol_fallback(path: str) -> JSONResponse:
    # External knowledge adapters use different discovery paths and response
    # envelopes.  A deterministic empty result validates the adapter transport
    # without requiring a real third-party account or turning a missing route
    # into a product-side 5xx.
    return JSONResponse(
        status_code=200,
        content={
            "code": 0,
            "data": [],
            "datasets": [],
            "items": [],
            "message": "success",
            "path": path,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=19192)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
