# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Coverage for the AIDP folder/file service layer."""

from __future__ import annotations

import copy
import importlib

import pytest

PAYLOAD = {
    "folders": [{"folder_name": "归档", "folder_id": 2}, "bad"],
    "files": {
        "value": [
            {
                "file_uuid": "u1",
                "file_name": "a.txt",
                "file_status": 1,
                "created_at": "2026-01-01",
            },
            "bad",
        ],
        "page": "2",
        "page_size": "5",
        "total": "1",
    },
    "folder_path": "/x",
    "folder_id": "7",
}


@pytest.fixture
def folder(monkeypatch):
    module = importlib.import_module(
        "ext_components.aidp.services.aidp_folder_service"
    )
    calls: list[tuple] = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return copy.deepcopy(PAYLOAD)

    monkeypatch.setattr(module, "_resolve_aidp_folder_id", lambda *a, **kw: 1)
    monkeypatch.setattr(module, "_get_aidp_folder_level", lambda *a, **kw: copy.deepcopy(PAYLOAD))
    monkeypatch.setattr(module, "_request_aidp_json", request)
    monkeypatch.setattr(module, "_get_folders_path", lambda kds: f"/kb/{kds}/Folders")
    monkeypatch.setattr(
        module, "_get_knowledge_files_path", lambda kds: f"/kb/{kds}/Files"
    )
    monkeypatch.setattr(module, "_join_folder_path", lambda p, n: f"{p.rstrip('/')}/{n}")
    return module, calls


def test_folder_tree_normalizes_mixed_payload(folder):
    module, _ = folder
    result = module.get_aidp_folder_tree_impl("s", "k", "kb", "/", page=2, page_size=5)
    assert result["folders"] == [{"folder_name": "归档", "folder_id": 2}]
    assert result["files"]["value"][0]["file_uuid"] == "u1"
    assert result["files"]["page"] == 2
    assert result["files"]["page_size"] == 5
    assert result["files"]["total"] == 1
    assert result["folder_id"] == 7


def test_folder_and_file_writes(folder):
    module, calls = folder
    module.create_aidp_folder_impl("s", "k", "kb", "/", "n")
    module.rename_aidp_folder_impl("s", "k", "kb", "/", "old", "new")
    module.delete_aidp_folder_impl("s", "k", "kb", "/old")
    module.move_aidp_folder_impl("s", "k", "kb", "/", "n", "/target", True)
    module.move_aidp_files_impl("s", "k", "kb", ["u1"], "/target")
    module.rename_aidp_file_impl("s", "k", "kb", "u1", "b.txt")
    assert len(calls) == 6
    assert calls[5][1]["json_body"]["new_file_name"] == "b.txt"
