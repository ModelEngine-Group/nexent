"""Merge accepted guidance into the existing ordered stream and message-unit persistence."""

import asyncio
import json
from contextlib import suppress

from nexent.core.concurrency import run_blocking


async def stream_with_guidance(source, port, *, poll_seconds=0.25):
    """Keep the original iterator alive while input arrives during a model/tool wait."""
    seen = set()
    iterator = aiter(source)
    pending = None
    next_poll = 0.0
    loop = asyncio.get_running_loop()
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(iterator))
            await asyncio.wait({pending}, timeout=max(0, next_poll - loop.time()))
            ended = pending.done() and isinstance(pending.exception(), StopAsyncIteration)
            if loop.time() >= next_poll or ended:
                for item in await run_blocking(
                    "hitl-port-visible_guidance", port.visible_guidance, lane="control-io", owner=__name__,
                ):
                    if item["request_id"] not in seen:
                        seen.add(item["request_id"])
                        yield json.dumps({"type": "user_steering", "content": json.dumps(item, ensure_ascii=False)},
                                         ensure_ascii=False)
                next_poll = loop.time() + poll_seconds
            if pending.done():
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    break
                pending = None
                yield chunk
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        await iterator.aclose()
