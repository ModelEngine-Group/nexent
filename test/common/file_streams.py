# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral async stream doubles for the HTTP owner's current interface."""

import asyncio
from unittest.mock import AsyncMock, MagicMock


def object_stream(content=b'content'):
    stream = MagicMock()
    async def chunks():
        yield content
    stream.__aiter__.side_effect = chunks
    stream.aclose = AsyncMock()
    return stream


async def consume_response(response):
    blocks = []
    async def send(message):
        if message['type'] == 'http.response.body':
            blocks.append(message.get('body', b''))
    async def receive():
        await asyncio.Event().wait()
    await response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send)
    return b''.join(blocks)
