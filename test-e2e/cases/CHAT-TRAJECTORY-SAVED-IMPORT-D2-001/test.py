# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CHAT-TRAJECTORY-SAVED-IMPORT-D2-001: persistent HTTP and ownership contracts."""

import pytest
from saved_trajectory_imports import call, saved_http, upload_saved
from trajectory_exchange import BODY, exported, http_app, imported, seed

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-SAVED-IMPORT-D2-001"),
    pytest.mark.stage("D2"),
]


def test_saved_import_protocol_and_isolation(tmp_path, monkeypatch):
    with http_app(monkeypatch, seed(tmp_path / "source")) as http:
        raw = exported(http).content
    root = tmp_path / "saved"
    with saved_http(monkeypatch, root) as http:
        responses = [upload_saved(http, raw) for _ in range(2)]
        assert all(response.status_code == 200 for response in responses)
        first, second = [response.json()["data"]["item"] for response in responses]
        assert first["import_id"] != second["import_id"]
        assert all(
            response.headers["cache-control"] == "private,no-store"
            for response in responses
        )
        listing = call(http, "GET", params={"page_size": 1}).json()["data"]
        assert listing["total"] == 2 and listing["items"] == [second]
        second_page = call(http, "GET", params={"page_size": 1, "page": 2}).json()[
            "data"
        ]
        assert second_page["items"] == [first]
        detail = call(http, "GET", "/" + first["import_id"])
        assert detail.headers["cache-control"] == "private,no-store"
        data = detail.json()["data"]["trajectory"]
        assert data["pages"][2]["snapshot"]["nodes"][2]["output"]["text"] == BODY
        assert data["row"]["user_id"] == "owner"
        for actor, status in [(None, 401), ("user", 403)]:
            assert upload_saved(http, raw, actor).status_code == status
            for method, path in [
                ("GET", ""),
                ("GET", "/" + first["import_id"]),
                ("DELETE", "/" + first["import_id"]),
            ]:
                assert call(http, method, path, actor).status_code == status
        for actor in ("peer", "other"):
            assert call(http, "GET", actor=actor).json()["data"]["items"] == []
            denied = call(http, "GET", "/" + first["import_id"], actor)
            assert denied.status_code == 404 and "Archive" not in denied.text
            assert (
                call(http, "DELETE", "/" + first["import_id"], actor).status_code == 200
            )
        assert call(http, "GET", "/" + first["import_id"]).status_code == 200
        for path in ("?page=0", "?page_size=101"):
            assert call(http, "GET", path).status_code == 422
        assert call(http, "GET", "/invalid").status_code == 404
        assert upload_saved(http, b"bad ZIP").status_code == 422
        assert imported(http, raw).status_code == 200
        assert call(http, "GET").json()["data"]["total"] == 2
        for _ in range(2):
            assert call(http, "DELETE", "/" + first["import_id"]).json()["data"] == {
                "deleted": True
            }
        assert call(http, "GET", "/" + first["import_id"]).status_code == 404
        assert call(http, "GET").json()["data"]["items"] == [second]
