# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CHAT-TRAJECTORY-SAVED-IMPORT-D5-001: real storage faults and hostile file boundaries."""

import io
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from ops.services.trajectory import saved_imports
from ops.services.trajectory.access import Actor
from ops.services.trajectory.primitives import CURRENT_CANCEL, QueryError
from saved_trajectory_imports import call, saved_http, upload_saved
from trajectory_exchange import exported, http_app, rewrite, seed

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-SAVED-IMPORT-D5-001"),
    pytest.mark.stage("D5"),
]


def test_saved_import_faults_paths_and_recovery(tmp_path, monkeypatch):
    with http_app(monkeypatch, seed(tmp_path / "source")) as http:
        raw = exported(http).content
    root = tmp_path / "saved"
    with saved_http(monkeypatch, root) as http:
        bad = rewrite(raw, lambda entries: entries.update({"../escape": b"no"}))
        assert upload_saved(http, bad).status_code == 422
        with monkeypatch.context() as patch:
            patch.setattr(
                saved_imports,
                "write_all",
                Mock(side_effect=OSError("owned disk fault")),
            )
            assert upload_saved(http, raw).status_code == 503
        assert call(http, "GET").json()["data"]["total"] == 0
        original = saved_imports.write_all
        with monkeypatch.context() as patch:

            def cancel(fd, data):
                original(fd, data)
                CURRENT_CANCEL.get().set()

            patch.setattr(saved_imports, "write_all", cancel)
            assert upload_saved(http, raw).status_code == 503
        assert call(http, "GET").json()["data"]["total"] == 0
        record = upload_saved(http, raw).json()["data"]["item"]
        assert call(http, "GET", actor="peer").json()["data"]["total"] == 0
        for actor in ("peer", "other"):
            assert (
                call(http, "GET", "/" + record["import_id"], actor).status_code == 404
            )
            assert (
                call(http, "DELETE", "/" + record["import_id"], actor).status_code
                == 200
            )
        assert call(http, "GET", "/" + record["import_id"]).status_code == 200
        owner = root / ".imports/local/admin"
        pending = owner / ".pending-00000000-0000-0000-0000-000000000001"
        pending.mkdir()
        (pending / "archive.zip").write_bytes(b"crash")
        assert call(http, "GET").json()["data"]["total"] == 1
        assert not pending.exists()
        path = owner / record["import_id"]
        (path / "archive.zip").unlink()
        target = tmp_path / "outside"
        target.write_bytes(b"private")
        (path / "archive.zip").symlink_to(target)
        denied = call(http, "GET", "/" + record["import_id"])
        assert denied.status_code in (422, 503) and "private" not in denied.text
        assert call(http, "DELETE", "/" + record["import_id"]).status_code == 200
        assert target.read_bytes() == b"private"
        record = upload_saved(http, raw).json()["data"]["item"]
        with monkeypatch.context() as patch:
            patch.setattr(
                saved_imports.SavedImports,
                "_remove",
                Mock(side_effect=OSError("unlink failure")),
            )
            assert call(http, "DELETE", "/" + record["import_id"]).status_code == 503
        assert call(http, "GET").json()["data"]["total"] == 0
        assert not list(owner.glob(".trash-*"))
        assert upload_saved(http, raw).status_code == 200


def test_saved_import_concurrent_publication_and_delete(tmp_path, monkeypatch):
    with http_app(monkeypatch, seed(tmp_path / "source")) as http:
        raw = exported(http).content
    root = tmp_path / "saved"
    actor = Actor("admin", "local", "OPS")
    store = saved_imports.SavedImports(root)

    def create(_):
        for _ in range(50):
            try:
                return store.create(actor, io.BytesIO(raw), "same.zip")["item"]
            except QueryError as error:
                assert error.code == "import_store_busy"
        raise AssertionError("No progress under controlled concurrent load")

    with ThreadPoolExecutor(max_workers=2) as workers:
        items = list(workers.map(create, range(2)))
    assert len({item["import_id"] for item in items}) == 2
    assert store.list(actor)["total"] == 2
    assert store.read(actor, items[0]["import_id"])["trajectory"]["pages"]
    store.delete(actor, items[1]["import_id"])
    assert store.read(actor, items[0]["import_id"])["trajectory"]["pages"]
