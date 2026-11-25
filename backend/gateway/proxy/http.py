# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""HTTP and SSE transport with request-owned upstream response lifetime."""

import asyncio

import httpx
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.requests import ClientDisconnect

from gateway.routing import filtered_headers


async def _send_cancellable(request, url, headers, client):
    """Release a probe even when the upstream has yet to send its headers."""
    body_forwarded = asyncio.Event()

    async def body():
        async for chunk in request.stream():
            yield chunk
        body_forwarded.set()

    async def wait_for_disconnect():
        # The upload owns ASGI receive until the request body has been read.
        await body_forwarded.wait()
        while (await request.receive())["type"] != "http.disconnect":
            pass

    outgoing = client.build_request(request.method, url, headers=headers, content=body())
    send = asyncio.create_task(client.send(outgoing, stream=True))
    disconnect = asyncio.create_task(wait_for_disconnect())
    upstream = None
    try:
        finished, _ = await asyncio.wait({send, disconnect}, return_when=asyncio.FIRST_COMPLETED)
        if disconnect not in finished:
            upstream = send.result()
        return upstream
    finally:
        disconnect.cancel()
        if not send.done():
            send.cancel()
        result, _ = await asyncio.gather(send, disconnect, return_exceptions=True)
        if upstream is None and isinstance(result, httpx.Response):
            await result.aclose()


async def forward_http(request, url, headers, client, *, cancel_before_headers=False):
    try:
        if cancel_before_headers:
            upstream = await _send_cancellable(request, url, headers, client)
        else:
            outgoing = client.build_request(request.method, url, headers=headers, content=request.stream())
            upstream = await client.send(outgoing, stream=True)
    except ClientDisconnect:
        return Response(status_code=499)
    except httpx.TimeoutException:
        return JSONResponse({"detail": "Upstream timeout"}, status_code=504)
    except httpx.RequestError:
        return JSONResponse({"detail": "Upstream unavailable"}, status_code=502)

    if upstream is None:
        return Response(status_code=499)

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
