# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Image acquisition uses one exact read-only object capability."""

import base64
from io import BytesIO
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nexent.storage.errors import InvalidInput
from nexent.storage.models import ObjectRef, OperationContext, Revision

from infrastructure.file_processing import image_sources as module


def context():
    return OperationContext("image-ut", monotonic() + 5)


@pytest.mark.asyncio
async def test_inline_bytes_do_not_start_network(monkeypatch):
    session = Mock()
    monkeypatch.setattr(module.aiohttp, "ClientSession", session)
    assert await module.read_inline_or_web_image("data:image/png;base64," + base64.b64encode(b"bytes").decode(), context=context()) == b"bytes"
    session.assert_not_called()


@pytest.mark.parametrize("url", ["C:/secret.png", "/tmp/image.png", "file:///tmp/a", "s3://files/a", "https://images.example/a.svg"])
@pytest.mark.asyncio
async def test_invalid_network_scheme_is_rejected(url):
    with pytest.raises(InvalidInput):
        await module.read_inline_or_web_image(url, context=context())


@pytest.mark.asyncio
async def test_web_read_preserves_query_and_closes_contexts(monkeypatch):
    response = AsyncMock()
    response.status = 200
    response.read.return_value = b"image"
    response.__aenter__.return_value = response
    session = Mock()
    session.get.return_value = response
    owner = AsyncMock()
    owner.__aenter__.return_value = session
    factory = Mock(return_value=owner)
    monkeypatch.setattr(module.aiohttp, "ClientSession", factory)
    url = "https://images.example/a.png?x=1&y=2"
    assert await module.read_inline_or_web_image(url, context=context()) == b"image"
    session.get.assert_called_once_with(url, max_redirects=10)
    response.__aexit__.assert_awaited_once()
    owner.__aexit__.assert_awaited_once()
    assert 0 < factory.call_args.kwargs["timeout"].total <= 5
    assert factory.call_args.kwargs["trust_env"] is True


@pytest.mark.parametrize("failure", [False, True])
def test_object_is_pinned_exact_and_closed(monkeypatch, failure):
    monkeypatch.setattr(module.environment, "MINIO_DEFAULT_BUCKET", "files")
    store = Mock()
    pinned = ObjectRef("files", "attachments/u/a.png", Revision("v1"))
    store.stat.return_value = SimpleNamespace(ref=pinned, size=5)
    stream = BytesIO(b"image")
    store.open_read.return_value = stream
    if failure:
        store.open_read.side_effect = OSError("read failed")
    factory = Mock(return_value=store)
    monkeypatch.setattr(module, "bind_source_objects", factory)
    ctx = context()
    if failure:
        with pytest.raises(OSError, match="read failed"):
            module.read_object_image("s3://files/attachments/u/a.png", user_id="u", tenant_id="t", context=ctx)
    else:
        assert module.read_object_image("s3://files/attachments/u/a.png", user_id="u", tenant_id="t", context=ctx) == b"image"
        assert stream.closed
    factory.assert_called_once_with("t", "u", "attachments/u/a.png", "files", writable=False, role="management")
    store.open_read.assert_called_once_with(pinned, context=ctx)
    store.close.assert_called_once()


def test_foreign_bucket_never_binds(monkeypatch):
    monkeypatch.setattr(module.environment, "MINIO_DEFAULT_BUCKET", "files")
    factory = Mock()
    monkeypatch.setattr(module, "bind_source_objects", factory)
    with pytest.raises(InvalidInput):
        module.read_object_image("s3://other/attachments/u/a.png", user_id="u", tenant_id="t", context=context())
    factory.assert_not_called()
