# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CHAT-TRAJECTORY-ARCHIVE-D3-001: writer -> HTTP ZIP -> independent import service."""

import hashlib

import pytest
from contracts.constants import environment
from ops.services.trajectory import exchange
from trajectory_exchange import BODY, exported, http_app, imported, seed

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-ARCHIVE-D3-001"),
    pytest.mark.stage("D3"),
]


def test_native_archive_cross_service_roundtrip(tmp_path, monkeypatch):
    source = seed(tmp_path / "source")
    before = {
        str(file.relative_to(tmp_path)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in tmp_path.rglob("*")
        if file.is_file()
    }
    with http_app(monkeypatch, source) as http:
        raw = exported(http).content
    calls = source.catalog.calls
    files = []
    original = exchange.tempfile.TemporaryFile

    def temporary(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(exchange.tempfile, "TemporaryFile", temporary)
    monkeypatch.setattr(environment, "TRAJECTORY_READ_ENABLED", False)
    with http_app(monkeypatch) as target:
        for _ in range(2):
            response = imported(target, raw)
            assert response.status_code == 200, response.text
            result = response.json()["data"]
            assert [
                page["run"]["trajectory_id"] for page in result["pages"]
            ] == source.runs
            assert [page["run"]["round_no"] for page in result["pages"]] == [1, 2, 3]
            for index, page in enumerate(result["pages"]):
                nodes = {node["id"]: node for node in page["snapshot"]["nodes"]}
                assert nodes["node-3"]["output"]["text"].encode() == BODY.encode()
                assert nodes["node-3"]["parent_id"] == "node-1"
                assert nodes["node-1"]["agent_version_no"] == index
                assert nodes["node-1"]["agent_version_name"] == f"Version {index}"
                assert nodes["node-1"]["usage"]["total"] == 10
                assert nodes["node-2"]["reasoning"]["text"] == "reasoning 😀"
                assert nodes["node-2"]["raw"]["text"] == '{"original":null}'
                assert nodes["node-2"]["ttft_ms"] is None
                assert all(
                    node[slot]["content_id"] is None
                    for node in nodes.values()
                    for slot in ("input", "output", "reasoning", "raw")
                )
            assert all(file.closed for file in files)
        assert target.manager.snapshot().active_count == 0
    assert source.catalog.calls == calls
    after = {
        str(file.relative_to(tmp_path)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in tmp_path.rglob("*")
        if file.is_file()
    }
    assert after == before
