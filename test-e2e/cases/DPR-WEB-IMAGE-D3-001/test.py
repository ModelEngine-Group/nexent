# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Actual web HTTP, Runtime managed execution and all three SDK image events."""

import asyncio
import json
from collections import Counter
from io import BytesIO
from time import monotonic
from types import SimpleNamespace

import pytest
from aiohttp import web
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.utils.observer import MessageObserver
from PIL import Image
from runtime.images import WebImageFilter


@pytest.mark.stage("D3")
@pytest.mark.case_id("DPR-WEB-IMAGE-D3-001")
async def test_web_image_runtime(record_property):
    bodies = {}
    for name, size in (("large", 200), ("small", 199)):
        with BytesIO() as buffer, Image.new("RGB", (size, 200)) as image:
            image.save(buffer, format="PNG")
            bodies[name] = buffer.getvalue()
    requests, handlers = Counter(), set()

    async def image_route(request):
        task = asyncio.current_task()
        handlers.add(task)
        name = request.match_info["name"]
        requests[name] += 1
        try:
            if name == "slow":
                await asyncio.Event().wait()
            if name not in bodies:
                return web.Response(status=404)
            return web.Response(body=bodies[name], content_type="image/png")
        finally:
            handlers.discard(task)

    app = web.Application()
    app.router.add_get("/{name}", image_route)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    address = site._server.sockets[0].getsockname()
    base = f"http://127.0.0.1:{address[1]}"
    urls = [base + path for path in ("/large", "/small", "/missing", "/slow", "/large")]
    manager = ThreadManager(service_name="web-image-proof", lane_policies={
        "model-tool-io": LanePolicy(name="model-tool-io", max_workers=1, max_queue_size=0,
                                   queue_timeout_seconds=0, cancel_grace_seconds=1, shutdown_grace_seconds=3),
    })
    manager.start()
    observed = []
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    beating = asyncio.create_task(heartbeat())

    def exercise():
        port = WebImageFilter(enabled=False, model_path=None, image_seconds=0.2)
        for name, key in (("Exa", "exa"), ("Tavily", "tavily"), ("Linkup", "linkup")):
            observer = MessageObserver()
            config = ToolConfig(
                class_name=name + "SearchTool", name=key + "_search", source="local", description="Search",
                output_type="string", params={key + "_api_key": "synthetic-key", "image_filter": True},
                metadata={"image_filterer": port},
            )
            tool = NexentAgent.create_local_tool(SimpleNamespace(observer=observer), config)
            assert not hasattr(tool, "data_process_service")
            tool._filter_images(urls, "query")
            messages = [json.loads(value) for value in observer.get_cached_message()]
            assert len(messages) == 1 and messages[0]["type"] == "picture_web"
            content = messages[0]["content"]
            if isinstance(content, str):
                content = json.loads(content)
            assert content == {"images_url": [urls[0], urls[4]]}
            observed.append(name)

    started = monotonic()
    try:
        async with asyncio.timeout(8):
            await manager.run("model-tool-io", ManagedTaskSpec(task_name="web-images", owner="proof"), exercise)
        assert monotonic() - started < 5 and ticks > 3
        assert observed == ["Exa", "Tavily", "Linkup"]
        assert requests == {"large": 6, "small": 3, "missing": 3, "slow": 3}
    finally:
        beating.cancel()
        await asyncio.gather(beating, return_exceptions=True)
        for task in tuple(handlers):
            task.cancel()
        await asyncio.gather(*tuple(handlers), return_exceptions=True)
        await runner.cleanup()
        drained = await manager.shutdown(timeout=3)
        assert not drained.stuck_execution_ids
    assert not handlers and beating.done()
    with pytest.raises(OSError):
        _reader, writer = await asyncio.open_connection(*address[:2])
        writer.close()
        await writer.wait_closed()
    record_property("web_image_runtime", json.dumps({
        "tools": observed, "requests": dict(requests), "heartbeat": ticks, "owned_cleanup": True,
        "clip_enabled": False, "old_service_requests": 0,
    }))
