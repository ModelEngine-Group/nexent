# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent image rules delegate object I/O to the attachment data layer."""

import io
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from management.services.agent.icon import (
    read_icon_image, upload_icon_image, validate_icon_image,
)


@pytest.fixture
def storage(mocker, monkeypatch):
    module = ModuleType("database.attachment_db")
    module.upload_file_bytes = MagicMock(return_value=(True, None))
    module.get_file_stream = MagicMock()
    monkeypatch.setitem(sys.modules, "database.attachment_db", module)
    return module


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
    assert upload_icon_image(content, "icons/agent-1") == "image/jpeg"
    storage.upload_file_bytes.assert_called_once_with(content, "icons/agent-1")


def test_upload_maps_storage_failure(storage):
    storage.upload_file_bytes.return_value = (False, "offline")
    with pytest.raises(ValueError, match="Failed to upload icon: offline"):
        upload_icon_image(b"GIF89aimage", "icons/agent-1")


def test_upload_rejects_invalid_image_before_storage(storage):
    with pytest.raises(ValueError, match="PNG, JPEG, GIF, or WebP"):
        upload_icon_image(b"invalid", "icons/agent-1")
    storage.upload_file_bytes.assert_not_called()


def test_read_returns_validated_content(storage):
    content = b"RIFF\x00\x00\x00\x00WEBPimage"
    storage.get_file_stream.return_value = io.BytesIO(content)
    assert read_icon_image("icons/agent-1") == (content, "image/webp")
    storage.get_file_stream.assert_called_once_with("icons/agent-1")


def test_read_maps_missing_object(storage):
    storage.get_file_stream.return_value = None
    with pytest.raises(FileNotFoundError, match="Icon not found"):
        read_icon_image("icons/missing")


def test_read_maps_invalid_stored_content(storage):
    storage.get_file_stream.return_value = io.BytesIO(b"invalid")
    with pytest.raises(FileNotFoundError, match="Icon is invalid") as error:
        read_icon_image("icons/agent-1")
    assert isinstance(error.value.__cause__, ValueError)
