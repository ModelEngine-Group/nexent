# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP and SSE transport with request-owned upstream response lifetime."""

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from gateway.routing import filtered_headers


async def forward_http(request, url, headers, client):
    try:
        outgoing = client.build_request(request.method, url, headers=headers, content=request.stream())
        upstream = await client.send(outgoing, stream=True)
    except httpx.TimeoutException:
        return JSONResponse({"detail": "Upstream timeout"}, status_code=504)
    except httpx.RequestError:
        return JSONResponse({"detail": "Upstream unavailable"}, status_code=502)

    async def stream():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    response = StreamingResponse(stream(), status_code=upstream.status_code,
                                 background=BackgroundTask(upstream.aclose))
    response.raw_headers = [(name.encode("latin-1"), value.encode("latin-1"))
                            for name, value in filtered_headers(upstream.headers.multi_items())]
    return response
