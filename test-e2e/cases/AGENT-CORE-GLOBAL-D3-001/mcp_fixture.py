# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Controlled remote creator tools served through the actual MCP transport."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn

if sys.platform == "win32":
    for folder in ("pywin32_system32", "win32", "win32/lib"):
        sys.path.append(str(Path(uvicorn.__file__).resolve().parents[1] / folder))

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route


state = {"cards": 0, "effects": 0}
mcp = FastMCP("creator-boundary-fixture")


@mcp.tool
def nl2a_wrapper(agent_id: int) -> str:
    state["cards"] += 1
    payload = {"subtype": "requirement_clarification", "agent_id": agent_id, "questions": [
        {"question_id": "scope", "question_type": "text", "title": "What output?", "required": True,
         "options": [], "allow_other": False, "other_input_expanded": False}]}
    return '<nl2a>\n' + json.dumps(payload) + '\n</nl2a>\nNL2A payload generated.'


@mcp.tool
def forbidden_effect() -> str:
    state["effects"] += 1
    return "must not execute after the card"


async def status(request):
    return JSONResponse(state)


mcp_app = mcp.http_app(path="/mcp")


@asynccontextmanager
async def lifespan(app):
    async with mcp_app.lifespan(app):
        yield


app = Starlette(routes=[Route("/state", status), Mount("/", app=mcp_app)], lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning", timeout_graceful_shutdown=1)
