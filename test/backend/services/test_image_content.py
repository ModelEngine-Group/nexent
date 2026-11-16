# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Isolated Management image-content orchestration and deadline tests."""

import asyncio
import base64
from io import BytesIO
from threading import Event
from time import monotonic
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from management.services.file import image_content as module
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.storage.models import OperationContext
from PIL import Image


@pytest_asyncio.fixture
async def pool(monkeypatch):
    manager = ThreadManager(service_name="image-ut", lane_policies={
        "control-io": LanePolicy(name="control-io", max_workers=1, max_queue_size=1,
                                 queue_timeout_seconds=0, cancel_grace_seconds=1, shutdown_grace_seconds=2),
    })
    manager.start()
    monkeypatch.setattr(module, "get_current_thread_manager", lambda: manager)
    try:
        yield manager
    finally:
        result = await manager.shutdown(timeout=2)
        assert not result.stuck_execution_ids


@pytest.fixture
def png():
    with Image.new("RGB", (4, 4), "blue") as image, BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


@pytest.mark.asyncio
async def test_web_image_is_encoded_in_managed_lane(pool, monkeypatch, png):
    fetch = AsyncMock(return_value=png)
    monkeypatch.setattr(module, "read_inline_or_web_image", fetch)
    result = await module.fetch_image_content("https://images.example/i?a=1&b=2")
    assert result["content_type"] == "image/png"
    assert base64.b64decode(result["base64"]) == png
    fetch.assert_awaited_once()
    assert fetch.call_args.args == ("https://images.example/i?a=1&b=2",)
    assert fetch.call_args.kwargs["context"].deadline <= monotonic() + 5


@pytest.mark.asyncio
async def test_owned_s3_image_passes_identity(pool, monkeypatch, png):
    fetch = Mock(return_value=png)
    network = AsyncMock()
    monkeypatch.setattr(module, "read_object_image", fetch)
    monkeypatch.setattr(module, "read_inline_or_web_image", network)
    result = await module.fetch_image_content("s3://files/attachments/u/a.png", user_id="u", tenant_id="t")
    assert result["success"]
    assert fetch.call_args.kwargs["user_id"] == "u"
    assert fetch.call_args.kwargs["tenant_id"] == "t"
    network.assert_not_called()


@pytest.mark.parametrize("user_id,key", [(None, "attachments/u/a.png"), ("u", "attachments/other/a.png")])
@pytest.mark.asyncio
async def test_denied_object_never_enters_storage(pool, monkeypatch, user_id, key):
    fetch = Mock()
    monkeypatch.setattr(module, "read_object_image", fetch)
    with pytest.raises(PermissionError):
        await module.fetch_image_content("s3://files/" + key, user_id=user_id, tenant_id="t")
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_total_network_deadline_cancels_once(pool, monkeypatch):
    stopped = asyncio.Event()

    async def read(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    fetch = AsyncMock(side_effect=read)
    monkeypatch.setattr(module, "read_inline_or_web_image", fetch)
    monkeypatch.setattr(module, "OperationContext", lambda op, deadline: OperationContext(op, monotonic() + 0.03))
    with pytest.raises(TimeoutError):
        await module.fetch_image_content("https://images.example/slow?secret=fixture")
    assert stopped.is_set()
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_manager_is_required(monkeypatch):
    monkeypatch.setattr(module, "get_current_thread_manager", lambda: None)
    monkeypatch.setattr(module, "get_default_thread_manager", lambda: None)
    with pytest.raises(RuntimeError, match="service-owned"):
        await module.fetch_image_content("data:image/png;base64,AQ==")


@pytest.mark.asyncio
async def test_storage_deadline_cancels_owned_worker(pool, monkeypatch):
    exited = Event()

    def read(*args, context, **kwargs):
        try:
            assert context.cancelled.wait(1)
            context.remaining()
        finally:
            exited.set()

    fetch = Mock(side_effect=read)
    monkeypatch.setattr(module, "read_object_image", fetch)
    monkeypatch.setattr(module, "OperationContext", lambda op, deadline: OperationContext(op, monotonic() + 0.03))
    with pytest.raises(TimeoutError):
        await module.fetch_image_content("s3://files/attachments/u/a.png", user_id="u", tenant_id="t")
    for _ in range(20):
        if exited.is_set():
            break
        await asyncio.sleep(0.01)
    assert exited.is_set()
    fetch.assert_called_once()
