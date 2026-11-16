# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB image capability keeps actor scope and managed source ownership."""

import asyncio
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from PIL import Image
from runtime import knowledge_images as module
from runtime.images import WebImageFilter


@pytest_asyncio.fixture
async def pool():
    manager = ThreadManager(service_name="kb-image-ut", lane_policies={
        name: LanePolicy(name=name, max_workers=2, max_queue_size=2, queue_timeout_seconds=0,
                         cancel_grace_seconds=1, shutdown_grace_seconds=2)
        for name in ("model-tool-io", "control-io")
    })
    manager.start()
    try:
        yield manager
    finally:
        result = await manager.shutdown(timeout=2)
        assert not result.stuck_execution_ids


@pytest.fixture
def png():
    with BytesIO() as output, Image.new("RGBA", (200, 200)) as image:
        image.save(output, format="PNG")
        return output.getvalue()


def capability(seconds=2):
    return module.KnowledgeImageFilter(SimpleNamespace(user_id="u", tenant_id="t"),
                                       selector=WebImageFilter(enabled=False, model_path=None, image_seconds=seconds))


async def invoke(pool, service, urls, **kwargs):
    return await pool.run("model-tool-io", ManagedTaskSpec(task_name="kb-image-ut", owner="test"),
                          service, urls, "query", **kwargs)


@pytest.mark.asyncio
async def test_object_uses_runtime_actor_and_exact_read(pool, monkeypatch, png):
    read = Mock(return_value=png)
    monkeypatch.setattr(module, "read_object_image", read)
    url = "s3://files/attachments/u/a.png"
    assert await invoke(pool, capability(), [url]) == [url]
    assert read.call_args.kwargs["user_id"] == "u"
    assert read.call_args.kwargs["tenant_id"] == "t"
    assert read.call_args.kwargs["role"] == "runtime"
    assert read.call_args.kwargs["context"].cancelled is not None
    read.assert_called_once()


@pytest.mark.asyncio
async def test_foreign_object_denied_before_storage(pool, monkeypatch):
    read = Mock()
    monkeypatch.setattr(module, "read_object_image", read)
    assert await invoke(pool, capability(), ["s3://files/attachments/other/a.png"]) == []
    read.assert_not_called()


@pytest.mark.asyncio
async def test_inline_image_never_enters_object_store(pool, monkeypatch, png):
    import base64

    read = Mock()
    monkeypatch.setattr(module, "read_object_image", read)
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    assert await invoke(pool, capability(), [url]) == [url]
    read.assert_not_called()


@pytest.mark.asyncio
async def test_web_source_is_closed_after_decision(pool, monkeypatch):
    image = Image.new("RGB", (200, 200))
    read = AsyncMock(return_value=image)
    monkeypatch.setattr(module, "load_web_image", read)
    assert await invoke(pool, capability(), ["https://example.test/a.png"]) == ["https://example.test/a.png"]
    read.assert_awaited_once()
    with pytest.raises(ValueError, match="closed image"):
        image.getpixel((0, 0))


@pytest.mark.asyncio
async def test_run_cancellation_stops_object_worker(pool, monkeypatch):
    entered, exited = Event(), Event()

    def read(*args, context, **kwargs):
        entered.set()
        try:
            assert context.cancelled.wait(1)
            context.remaining()
        finally:
            exited.set()

    reader = Mock(side_effect=read)
    monkeypatch.setattr(module, "read_object_image", reader)
    scope = RunCancellationScope()
    task = asyncio.create_task(invoke(pool, capability(), ["s3://files/attachments/u/a.png"], cancellation_scope=scope))
    for _ in range(100):
        if entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert entered.is_set()
    scope.cancel()
    with pytest.raises(RunTerminated):
        await task
    for _ in range(100):
        if exited.is_set():
            break
        await asyncio.sleep(0.01)
    assert exited.is_set()
    reader.assert_called_once()
    assert not scope._closers
