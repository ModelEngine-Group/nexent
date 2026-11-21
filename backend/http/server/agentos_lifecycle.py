# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Cancel request-owned AgentOS work when its HTTP caller disconnects."""

import asyncio

from fastapi import Request
from starlette.responses import JSONResponse


async def run_until_disconnect(request: Request, run):
    async def wait_for_disconnect():
        while (await request.receive())["type"] != "http.disconnect":
            pass

    execution = asyncio.create_task(run)
    disconnected = asyncio.create_task(wait_for_disconnect())
    try:
        completed, _ = await asyncio.wait((execution, disconnected), return_when=asyncio.FIRST_COMPLETED)
        if execution in completed:
            return execution.result()
        return JSONResponse({"code": "AGENTOS_CLIENT_DISCONNECTED"}, status_code=499)
    finally:
        disconnected.cancel()
        if not execution.done():
            execution.cancel()
        await asyncio.gather(disconnected, execution, return_exceptions=True)
