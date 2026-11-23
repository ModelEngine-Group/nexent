# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CHAT-TRAJECTORY-SAVED-IMPORT-D3-001: native files survive independent application lifetimes."""

import hashlib

import pytest
from contracts.constants import environment
from saved_trajectory_imports import call, saved_http, upload_saved
from trajectory_exchange import BODY, exported, http_app, seed

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-SAVED-IMPORT-D3-001"),
    pytest.mark.stage("D3"),
]


def test_saved_import_reopens_after_service_rebuild(tmp_path, monkeypatch):
    root = tmp_path / "data"
    source = seed(root)
    paths = [path for path in root.rglob("*") if path.is_file()]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    with http_app(monkeypatch, source) as http:
        raw = exported(http).content
    with saved_http(monkeypatch, root, real_startup=True) as http:
        result = upload_saved(http, raw)
        assert result.status_code == 200, result.text
        item = result.json()["data"]["item"]
        archive = root / ".imports/local/admin" / item["import_id"] / "archive.zip"
        assert archive.read_bytes() == raw
    monkeypatch.setattr(environment, "TRAJECTORY_READ_ENABLED", False)
    with saved_http(monkeypatch, root, real_startup=True) as http:
        assert call(http, "GET").json()["data"]["items"] == [item]
        trajectory = call(http, "GET", "/" + item["import_id"]).json()["data"][
            "trajectory"
        ]
        assert len(trajectory["pages"]) == 3
        assert trajectory["pages"][2]["snapshot"]["nodes"][2]["output"]["text"] == BODY
        assert trajectory["pages"][2]["snapshot"]["nodes"][0]["agent_version_no"] == 2
        assert trajectory["pages"][2]["run"]["root_agent_version_no"] is None
        assert len(list(source.store.identities())) == 1
        assert call(http, "DELETE", "/" + item["import_id"]).status_code == 200
        assert not archive.parent.exists()
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    } == before
    assert [path.name for path in (root / ".imports/local/admin").iterdir()] == [
        ".lock"
    ]
