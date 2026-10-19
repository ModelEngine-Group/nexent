"""Local deterministic OpenAI-compatible model and native MCP fixture."""

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager

import uvicorn

# Windows virtual environments may not execute pywin32's post-install path hook.
if sys.platform == "win32":
    from pathlib import Path
    for folder in ("pywin32_system32", "win32", "win32/lib"):
        sys.path.append(str(Path(uvicorn.__file__).resolve().parents[1] / folder))

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route

state = {"requests": [], "script_calls": 0, "model_calls": 0, "mcp_calls": 0, "saw_skill": False, "tools": [], "messages": []}
mcp = FastMCP("jiuwen-local-fixture")


@mcp.tool
async def multiply(a: int, b: int, user_id: str | None = None) -> int:
    state["mcp_calls"] += 1
    state["user_id"] = user_id
    if a == 999:
        await asyncio.Event().wait()
    return a * b


@mcp.tool
def forbidden_tool() -> str:
    raise AssertionError("An unauthorized MCP tool must never execute")


async def completions(request: Request):
    body = await request.json()
    state["model_calls"] += 1
    state["requests"].append(body)
    messages = body["messages"]
    state["messages"] = messages
    if "FAIL_MODEL_400" in json.dumps(messages) or "FAIL_MODEL_503" in json.dumps(messages):
        status_code = 400 if "FAIL_MODEL_400" in json.dumps(messages) else 503
        return JSONResponse({"error": {"message": "Fixture provider failure", "type": "server_error"}},
                            status_code=status_code)
    if "block_model" in json.dumps(messages):
        await asyncio.Event().wait()
    state["tools"] = [tool["function"]["name"] for tool in body.get("tools", [])]
    state["saw_skill"] |= "Fixture skill guide" in json.dumps(messages)
    results = {message.get("name") or message.get("tool_call_id", "").removeprefix("fixture_"):
               message.get("content") for message in messages if message["role"] == "tool"}
    if "TRANSIENT_RETRY_MARKER" in json.dumps(messages) and "add" in results and not state.get("retry_injected"):
        state["retry_injected"] = True
        return JSONResponse({"error": {"message": "Temporary fixture failure", "type": "server_error"}}, status_code=503)
    chain = [
        ("add", {"a": 2, "b": 3}),
        ("multiply", {"a": 5, "b": 99}),
        ("read_skill_md", {"skill_name": "fixture_skill"}),
        ("run_skill_script", {"skill_name": "fixture_skill", "script_path": "scripts/hello.py"}),
    ]
    text_mode = not body.get("tools")
    if "BLOCK_MCP_MARKER" in json.dumps(messages):
        chain = [("multiply", {"a": 999, "b": 4})]
    if "PARALLEL_MARKER" in json.dumps(messages):
        chain = [("parallel_executor", {"tasks": [{"tool_name": "add", "arguments": {"a": 2, "b": 3}},
                   {"tool_name": "multiply", "arguments": {"a": 5, "b": 99}}]})]
    if text_mode:
        completed = sum("historical_tool_result" in str(message.get("content", "")) for message in messages)
        remaining = chain[completed:]
    else:
        remaining = [(name, args) for name, args in chain if name not in results]
    if "CURRENT_TASK_ONLY_MARKER" in json.dumps(messages[-1]):
        assert "Earlier conversation messages, attachments and results are historical reference" in json.dumps(messages)
        delta, reason = {"role": "assistant", "content": "CURRENT_RESPONSE_MARKER"}, "stop"
    elif remaining:
        name, args = remaining[0]
        delta = {"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": f"fixture_{name}",
                 "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
        reason = "tool_calls"
        if text_mode:
            args_text = ", ".join(f"{key}={value!r}" for key, value in args.items())
            delta = {"role": "assistant", "content": f"<code>\nprint({name}({args_text}))\n</code>"}
            reason = "stop"
    else:
        serialized = json.dumps(messages)
        if "PARALLEL_MARKER" not in serialized and "BLOCK_MCP_MARKER" not in serialized:
            assert "SKILL_GUIDE_MARKER" in serialized and "SCRIPT_RESULT_MARKER" in serialized
        assert "20" in serialized and "5" in serialized
        delta, reason = {"role": "assistant", "content": "native_result_20"}, "stop"
    chunk = {"id": "fixture-completion", "object": "chat.completion.chunk", "created": int(time.time()),
             "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
             "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}
    if body.get("stream"):
        return StreamingResponse(iter([f"data: {json.dumps(chunk)}\n\n", "data: [DONE]\n\n"]),
                                 media_type="text/event-stream")
    chunk["choices"][0]["message"] = chunk["choices"][0].pop("delta")
    for tool in chunk["choices"][0]["message"].get("tool_calls", []):
        tool.pop("index", None)
    chunk["object"] = "chat.completion"
    return JSONResponse(chunk)


async def status(request):
    return JSONResponse(state)


mcp_app = mcp.http_app(path="/mcp")


@asynccontextmanager
async def lifespan(app):
    async with mcp_app.lifespan(app):
        yield


app = Starlette(routes=[Route("/v1/chat/completions", completions, methods=["POST"]),
                        Route("/state", status), Mount("/", app=mcp_app)], lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning", timeout_graceful_shutdown=1)
