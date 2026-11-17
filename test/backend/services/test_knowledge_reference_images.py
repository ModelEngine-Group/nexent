# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Knowledge images use typed content grants; URL input is no longer supported."""

import asyncio
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from contracts.agentos_knowledge import (
    KnowledgeContentGrant,
    KnowledgeContentRequest,
    ObjectReference,
)
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated
from nexent.storage.errors import ScopeDenied
from PIL import Image
from runtime import knowledge_images as module
from runtime.images import WebImageFilter


@pytest_asyncio.fixture
async def pool():
    manager = ThreadManager(
        service_name="kb-image-ut",
        lane_policies={
            name: LanePolicy(
                name=name,
                max_workers=2,
                max_queue_size=2,
                queue_timeout_seconds=0,
                cancel_grace_seconds=1,
                shutdown_grace_seconds=2,
            )
            for name in ("model-tool-io", "control-io")
        },
    )
    manager.start()
    try:
        yield manager
    finally:
        result = await manager.shutdown(timeout=2)
        assert not result.stuck_execution_ids


@pytest.fixture
def reference():
    return KnowledgeContentRequest(
        knowledge_id=1,
        file_id="a" * 32,
        file_version=2,
        image_ref=ObjectReference(
            space="files",
            key=f"images/{'b' * 64}/{'c' * 64}.png",
            version="v1",
            sha256="c" * 64,
        ),
    )


@pytest.fixture
def png():
    with BytesIO() as output, Image.new("RGBA", (200, 200)) as image:
        image.save(output, format="PNG")
        return output.getvalue()


def capability(mocker, read, seconds=2):
    mocker.patch.object(
        module, "KnowledgeContentReader", return_value=SimpleNamespace(read=read)
    )
    return module.KnowledgeImageFilter(
        SimpleNamespace(user_id="u", tenant_id="t"),
        object(),
        selector=WebImageFilter(enabled=False, model_path=None, image_seconds=seconds),
    )


async def invoke(pool, service, references, **kwargs):
    return await pool.run(
        "model-tool-io",
        ManagedTaskSpec(task_name="kb-image-ut", owner="test"),
        service,
        references,
        "query",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_typed_object_read_is_bounded_and_decoded_image_is_closed(
    pool, mocker, png, reference
):
    read = AsyncMock(return_value=(png, "source.pdf"))
    image = Image.new("RGB", (200, 200))
    mocker.patch.object(module, "decode_image_bytes", return_value=image)
    assert await invoke(pool, capability(mocker, read), [reference]) == [reference]
    assert read.await_count == 1 and read.await_args.args == (reference,)
    assert 0 < read.await_args.kwargs["context"].remaining() <= 2
    with pytest.raises(ValueError, match="closed image"):
        image.getpixel((0, 0))


@pytest.mark.parametrize(
    "value",
    ["s3://files/image", "https://example.test/image", "data:image/png;base64,AAAA"],
)
@pytest.mark.asyncio
async def test_legacy_url_is_rejected_before_read(pool, mocker, value):
    read = AsyncMock()
    with pytest.raises(ValueError):
        await invoke(pool, capability(mocker, read), [value])
    read.assert_not_called()


@pytest.mark.asyncio
async def test_unauthorized_or_timed_out_image_is_never_reintroduced(
    pool, mocker, reference
):
    for error in (ScopeDenied(), TimeoutError()):
        read = AsyncMock(side_effect=error)
        assert await invoke(pool, capability(mocker, read), [reference]) == []
        assert read.await_count == 1


@pytest.mark.asyncio
async def test_existing_all_empty_importance_behavior_uses_only_verified_images(
    pool, mocker, png, reference
):
    read = AsyncMock(return_value=(png, "source"))
    service = capability(mocker, read)
    service.selector.scorer.filter = Mock(return_value={"is_important": False})
    assert await invoke(pool, service, [reference]) == [reference]
    assert read.await_count == 1


@pytest.mark.asyncio
async def test_cancellation_closes_active_content_read_without_retry(
    pool, mocker, reference
):
    entered, exited = Event(), Event()
    from runtime.knowledge_base import content

    grant = KnowledgeContentGrant(
        **reference.model_dump(), object_ref=reference.image_ref, filename="source"
    )
    client = SimpleNamespace(authorize_knowledge_content=AsyncMock(return_value=grant))

    def blocked(*args, context, **kwargs):
        entered.set()
        try:
            assert context.cancelled.wait(1)
            context.remaining()
        finally:
            exited.set()

    read = mocker.patch.object(content, "read_knowledge_content", side_effect=blocked)
    service = module.KnowledgeImageFilter(
        SimpleNamespace(user_id="u", tenant_id="t"),
        client,
        selector=WebImageFilter(enabled=False, model_path=None),
    )
    scope = RunCancellationScope()
    task = asyncio.create_task(
        invoke(pool, service, [reference], cancellation_scope=scope)
    )
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
    assert exited.is_set() and read.call_count == 1 and not scope._closers
