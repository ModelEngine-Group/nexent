# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Coverage for the AIDP chunk service layer."""

from __future__ import annotations

import copy
import importlib
from unittest.mock import MagicMock

import httpx
import pytest


@pytest.fixture
def chunk(monkeypatch):
    module = importlib.import_module(
        "ext_components.aidp.services.aidp_chunk_service"
    )
    calls: list[tuple] = []
    payloads = {
        "value": [{"chunk_id": "11", "chunk_text": "a"}],
        "chunk_id": "11",
        "data": {"task_id": "t1"},
        "message": "queued",
    }

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return copy.deepcopy(payloads)

    monkeypatch.setattr(module, "_request_aidp_json", request)
    monkeypatch.setattr(module, "_get_chunks_path", lambda kds: f"/kb/{kds}/Chunks")
    monkeypatch.setattr(module, "_get_batch_metadata_path", lambda kds, **kw: f"/kb/{kds}/Batch")
    monkeypatch.setattr(module, "_get_tags_sync_path", lambda tenant=None: "/tags/sync")
    return module, calls


def test_chunk_crud_and_metadata(chunk):
    module, calls = chunk
    assert module.list_aidp_chunks_impl("s", "k", "kb", "u")["value"][0]["chunk_id"] == 11
    assert module.get_aidp_chunk_impl("s", "k", "kb", 1)["chunk_id"] == 11
    assert module.create_aidp_chunk_impl("s", "k", "kb", "u", "text")["chunk_id"] == 11
    assert module.update_aidp_chunk_impl("s", "k", "kb", 1, "text")["chunk_id"] == 11
    module.remove_aidp_chunks_impl("s", "k", "kb", [1, 2])
    module.update_chunk_metadata_impl(
        "s",
        "k",
        "kb",
        od_id=1,
        metadata_json={"f": "v"},
        tag=["t"],
        chunk_id_list=[1],
        file_uuid_list=["u"],
        async_mode=True,
    )
    assert module.sync_chunk_tags_impl("s", "k", [1]) == {
        "task_id": "t1",
        "message": "queued",
    }
    assert len(calls) == 7


def test_chunk_image_returns_bytes(chunk, monkeypatch):
    module, _ = chunk
    client = MagicMock()
    client.get.return_value = httpx.Response(
        200,
        content=b"png",
        request=httpx.Request("GET", "http://aidp.example/x"),
    )
    monkeypatch.setattr(module.aidp_client.http_client_manager, "get_sync_client", MagicMock(return_value=client))
    monkeypatch.setattr(module, "_validate_params", lambda *a: "http://aidp.example")
    monkeypatch.setattr(module, "_get_view_image_path", lambda *a, **kw: "/image")
    monkeypatch.setattr(module, "_aidp_headers", lambda *a, **kw: {})
    assert module.get_aidp_image_impl("s", "k", "kb", "file") == b"png"


def test_chunk_id_normalization(chunk):
    module, _ = chunk
    assert module._normalize_chunk_id(True) is True
    assert module._normalize_chunk_id("12") == 12
    assert module._normalize_chunk_id("x") == "x"


def test_chunk_image_error_path(chunk, monkeypatch):
    module, _ = chunk
    client = MagicMock()
    client.get.side_effect = httpx.ConnectError("down")
    monkeypatch.setattr(module.aidp_client.http_client_manager, "get_sync_client", MagicMock(return_value=client))
    monkeypatch.setattr(module, "_validate_params", lambda *a: "http://aidp.example")
    monkeypatch.setattr(module, "_get_view_image_path", lambda *a, **kw: "/image")
    monkeypatch.setattr(module, "_aidp_headers", lambda *a, **kw: {})
    with pytest.raises(module.AppException):
        module.get_aidp_image_impl("s", "k", "kb", "file")
