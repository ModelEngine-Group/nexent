# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent image rules delegate exact object I/O to StorageInterface."""

import io
from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.services.agent import icon
from management.services.agent.icon import (
    read_icon_image,
    upload_icon_image,
    validate_icon_image,
)
from nexent.storage.errors import NotFound, ScopeDenied, Unavailable
from nexent.storage.models import ObjectRef, OperationContext


@pytest.fixture
def storage(mocker):
    store = Mock()
    mocker.patch.object(icon, "icon_write_port", return_value=io_context(store))
    mocker.patch.object(icon, "file_read_ports", return_value=io_context(store))
    return store


@contextmanager
def io_context(value):
    yield value


@pytest.mark.parametrize(("content", "error"), [
    (b"", "Icon file is empty"),
    (b"x" * (2 * 1024 * 1024 + 1), "2 MB"),
    (b"invalid", "PNG, JPEG, GIF, or WebP"),
    (b"RIFF\x00\x00\x00\x00WEB", "PNG, JPEG, GIF, or WebP"),
], ids=["empty", "oversized", "invalid", "incomplete-webp"])
def test_rejects_invalid_image(content, error):
    with pytest.raises(ValueError, match=error):
        validate_icon_image(content)


@pytest.mark.parametrize(("content", "mime"), [
    (b"\x89PNG\r\n\x1a\nrest", "image/png"),
    (b"\xff\xd8\xffrest", "image/jpeg"),
    (b"GIF87arest", "image/gif"),
    (b"GIF89arest", "image/gif"),
    (b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
])
def test_accepts_supported_signatures(content, mime):
    assert validate_icon_image(content) == mime


def test_accepts_exact_size_limit():
    content = b"GIF89a" + b"x" * (2 * 1024 * 1024 - 6)
    assert validate_icon_image(content) == "image/gif"


def test_upload_delegates_exact_bytes_and_key(storage):
    content = b"\xff\xd8\xffimage"
    key = "agent-icons/tenant/1/icon"

    def inspect(ref, body, *, content_type, size, context):
        assert ref == ObjectRef("files", key)
        assert body.read() == content
        assert content_type == "image/jpeg" and size == len(content)
        assert context.remaining() <= 5

    storage.put.side_effect = inspect
    assert upload_icon_image(content, key) == "image/jpeg"
    storage.put.assert_called_once()


def test_upload_maps_storage_failure(storage):
    storage.put.side_effect = Unavailable()
    with pytest.raises(ValueError, match="Failed to upload icon: Storage is unavailable"):
        upload_icon_image(b"GIF89aimage", "agent-icons/tenant/1/icon")
    storage.put.assert_called_once()


def test_upload_rejects_invalid_image_before_storage(storage):
    with pytest.raises(ValueError, match="PNG, JPEG, GIF, or WebP"):
        upload_icon_image(b"invalid", "agent-icons/tenant/1/icon")
    icon.icon_write_port.assert_not_called()


def test_read_returns_validated_content(storage):
    content = b"RIFF\x00\x00\x00\x00WEBPimage"
    stream = io.BytesIO(content)
    storage.open_read.return_value = stream
    assert read_icon_image("agent-icons/tenant/1/icon") == (content, "image/webp")
    assert storage.open_read.call_args.args == (ObjectRef("files", "agent-icons/tenant/1/icon"),)
    assert stream.closed


@pytest.mark.parametrize("error", [NotFound(), Unavailable()])
def test_read_maps_missing_or_unavailable_object(storage, error):
    storage.open_read.side_effect = error
    with pytest.raises(FileNotFoundError, match="Icon not found"):
        read_icon_image("agent-icons/tenant/missing/icon")
    storage.open_read.assert_called_once()


def test_read_maps_invalid_stored_content(storage):
    stream = io.BytesIO(b"invalid")
    storage.open_read.return_value = stream
    with pytest.raises(FileNotFoundError, match="Icon is invalid") as error:
        read_icon_image("agent-icons/tenant/1/icon")
    assert isinstance(error.value.__cause__, ValueError)
    assert stream.closed


def test_read_stops_after_size_limit_and_closes(storage):
    stream = io.BytesIO(b"GIF89a" + b"x" * (icon.ICON_MAX_BYTES + 10))
    reader = Mock(wraps=stream)
    @contextmanager
    def read_scope():
        try:
            yield reader
        finally:
            stream.close()
    storage.open_read.return_value = read_scope()
    with pytest.raises(FileNotFoundError, match="Icon is invalid"):
        read_icon_image("agent-icons/tenant/1/icon")
    assert sum(call.args[0] for call in reader.read.call_args_list) == icon.ICON_MAX_BYTES + 1
    assert stream.closed


def test_icon_write_grants_only_the_selected_key(mocker):
    from infrastructure import icon_objects

    client = mocker.patch.object(icon_objects, "_configured_client")
    mocker.patch.object(icon_objects, "_configured_environment", return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET="owned"))
    context = OperationContext("icon-scope", monotonic() + 5)
    with pytest.raises(ScopeDenied), icon_objects.icon_write_port("attachments/user/shared", context=context):
        pytest.fail("Non-icon path accepted")
    with (
        icon_objects.icon_write_port("agent-icons/tenant/1/icon", context=context) as store,
        pytest.raises(ScopeDenied),
    ):
        store.put(ObjectRef("files", "agent-icons/tenant/2/icon"), io.BytesIO(b"data"),
                  content_type="image/gif", size=4, context=context)
    client.assert_not_called()
