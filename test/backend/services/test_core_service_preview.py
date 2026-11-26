# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preview key contracts must stay independent of storage initialization."""

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.fixture
def preview(mocker):
    attachment = ModuleType("management.db.file.attachment")
    storage = Mock(side_effect=AssertionError("Unexpected storage operation"))
    for name in (
        "copy_file",
        "delete_file",
        "file_exists",
        "get_content_type",
        "get_file_range",
        "get_file_size_from_minio",
        "get_file_stream_raw",
    ):
        setattr(attachment, name, storage)
    mocker.patch.dict("sys.modules", {attachment.__name__: attachment})
    path = (
        Path(__file__).resolve().parents[3]
        / "backend/management/services/file/preview.py"
    )
    spec = importlib.util.spec_from_file_location("slimming_keys", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    storage.assert_not_called()


@pytest.mark.parametrize(
    "name", ["a.docx", "folder/中文.pptx", "without-extension", "a.b.c"]
)
def test_ac002_preview_key_matches_existing_contract(preview, name):
    stem = name.rsplit(".", 1)[0] if "." in name else name
    digest = hashlib.md5(name.encode()).hexdigest()[:8]
    assert (
        preview.build_preview_pdf_object_key(name)
        == f"preview/converted/{stem}_{digest}.pdf"
    )
    assert (
        preview.build_preview_pdf_object_key(name, temporary=True)
        == f"preview/converting/{stem}_{digest}.pdf.tmp"
    )
