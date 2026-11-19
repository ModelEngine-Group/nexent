# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bidirectional WebSocket transport and peer cleanup."""

import asyncio
from contextlib import suppress

from fastapi import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake


async def forward_websocket(websocket, url, headers):
    protocols = websocket.scope.get("subprotocols", [])
    accepted = False
    try:
        async with connect(url, additional_headers=headers, subprotocols=protocols or None,
                           open_timeout=10, max_size=16 * 1024 * 1024) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)
            accepted = True

            async def upload():
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        code = message.get("code", 1000)
                        await upstream.close(code=code if code not in {1005, 1006, 1015} else 1000)
                        return
                    await upstream.send(message.get("text") if message.get("text") is not None else message["bytes"])

            async def download():
                async for message in upstream:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(message)

            tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            code = upstream.close_code or 1000
            with suppress(RuntimeError):
                await websocket.close(code=code if code not in {1005, 1006, 1015} else 1011)
    except (OSError, TimeoutError, ConnectionClosed, InvalidHandshake, WebSocketDisconnect):
        with suppress(RuntimeError):
            await websocket.close(code=1011 if accepted else 1008)
