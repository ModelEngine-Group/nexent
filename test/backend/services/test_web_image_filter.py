# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-WEB-IMAGE-01: local decisions and bounded external image reads."""

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image
from runtime.images import WebImageFilter

from infrastructure.web_images import load_web_image


@pytest.mark.parametrize("url", ["s3://bucket/key", "data:image/png;base64,abc", "/tmp/image.png", "https://test/image.svg"])
async def test_loader_rejects_non_web_inputs_without_requests(url):
    session = MagicMock()
    assert await load_web_image(session, url) is None
    session.get.assert_not_called()


@pytest.mark.parametrize("status,body,expected", [(404, b"", False), (200, b"invalid", False), (200, None, True)])
async def test_loader_owns_response_and_decodes_in_memory(status, body, expected):
    if body is None:
        buffer = BytesIO()
        with Image.new("RGBA", (200, 200)) as image:
            image.save(buffer, format="PNG")
        body = buffer.getvalue()
    response = MagicMock(status=status)
    response.read = AsyncMock(return_value=body)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get.return_value = response
    image = await load_web_image(session, "https://example.invalid/image.png")
    assert (image is not None) is expected
    session.get.assert_called_once_with("https://example.invalid/image.png", max_redirects=10)
    response.__aexit__.assert_awaited_once()
    if image is not None:
        try:
            assert image.size == (200, 200)
            image.getpixel((0, 0))
        finally:
            image.close()


@pytest.fixture
def external(mocker):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = mocker.patch("runtime.images.aiohttp.ClientSession", return_value=session)
    load = mocker.patch("runtime.images.load_web_image", new=AsyncMock())
    mocker.patch("runtime.images.get_current_thread_manager", return_value=object())
    return SimpleNamespace(session=session, factory=factory, load=load)


def test_filter_requires_managed_execution_before_network(mocker):
    mocker.patch("runtime.images.get_current_thread_manager", return_value=None)
    factory = mocker.patch("runtime.images.aiohttp.ClientSession")
    with pytest.raises(RuntimeError, match="managed"):
        WebImageFilter(enabled=False, model_path=None)(["https://image.invalid/a"], "query")
    factory.assert_not_called()


def test_filter_preserves_order_prompts_and_closes_images(external, mocker):
    first = Image.new("RGB", (200, 200))
    second = Image.new("RGB", (199, 200))
    external.load.side_effect = [first, second, None]
    service = WebImageFilter(enabled=True, model_path="/clip")
    classify = mocker.patch.object(service.scorer, "filter", side_effect=[
        {"is_important": True}, {"is_important": False},
    ])
    urls = ["https://image.invalid/1", "https://image.invalid/2", "https://image.invalid/3"]
    assert service(urls, "query") == urls[:1]
    assert classify.call_count == 2
    assert classify.call_args_list[0].kwargs == {
        "enabled": True, "positive_prompt": "query",
        "negative_prompt": "logo or banner or background or advertisement or icon or avatar",
    }
    assert external.load.await_count == 3
    external.session.__aexit__.assert_awaited_once()
    assert external.factory.call_args.kwargs["timeout"].total == 2
    for image in (first, second):
        with pytest.raises(ValueError, match="closed image"):
            image.getpixel((0, 0))


def test_single_image_error_is_not_retried(external):
    external.load.side_effect = OSError("unavailable")
    assert WebImageFilter(enabled=False, model_path=None)(["https://image.invalid/1"], "query") == []
    external.load.assert_awaited_once()
    external.session.__aexit__.assert_awaited_once()


def test_total_deadline_cancels_download_and_closes_session(external, mocker, caplog):
    cancelled = []

    async def stalled(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    external.load.side_effect = stalled
    service = WebImageFilter(enabled=False, model_path=None, image_seconds=0.01)
    classify = mocker.patch.object(service.scorer, "filter")
    assert service(["https://private.invalid/token=secret"], "private-query") == []
    assert cancelled == [True]
    classify.assert_not_called()
    external.load.assert_awaited_once()
    external.session.__aexit__.assert_awaited_once()
    assert "web_image_timeout" in caplog.text
    assert "private-query" not in caplog.text and "secret" not in caplog.text
    assert not any(row.levelname == "ERROR" for row in caplog.records)


def test_late_native_result_is_not_published(external, mocker):
    image = Image.new("RGB", (200, 200))
    external.load.return_value = image
    service = WebImageFilter(enabled=False, model_path=None)
    clock = mocker.patch("runtime.images.monotonic", side_effect=[0, 0, 3])
    classify = mocker.patch.object(service.scorer, "filter", return_value={"is_important": True})
    assert service(["https://image.invalid/1"], "query") == []
    assert clock.call_count == 3
    classify.assert_called_once()
    with pytest.raises(ValueError, match="closed image"):
        image.getpixel((0, 0))


def test_inflight_downloads_are_limited_to_ten(external):
    active = maximum = 0

    async def load(*args):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0)
            return Image.new("RGB", (200, 200))
        finally:
            active -= 1

    external.load.side_effect = load
    urls = [f"https://image.invalid/{number}" for number in range(25)]
    assert WebImageFilter(enabled=False, model_path=None)(urls, "query") == urls
    assert maximum == 10 and active == 0
    assert external.load.await_count == 25


def test_model_lock_wait_uses_remaining_deadline(external, mocker):
    image = Image.new("RGB", (200, 200))
    external.load.return_value = image
    service = WebImageFilter(enabled=False, model_path=None, image_seconds=0.01)
    classify = mocker.patch.object(service.scorer, "filter")
    service._model_lock.acquire()
    try:
        assert service(["https://image.invalid/1"], "query") == []
    finally:
        service._model_lock.release()
    classify.assert_not_called()
    with pytest.raises(ValueError, match="closed image"):
        image.getpixel((0, 0))
