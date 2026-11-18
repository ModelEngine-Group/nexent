# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persistent import unit contracts with controlled format-parser boundaries."""

import io
from dataclasses import replace
from unittest.mock import Mock

import pytest
from ops.services.trajectory import saved_imports
from ops.services.trajectory.access import Actor
from ops.services.trajectory.exchange import ExchangeLimits
from ops.services.trajectory.primitives import QueryError

OWNER = Actor("admin", "local", "OPS")
DATA = {"row": {"conversation_id": "source", "root_agent_name": "中文😀"}, "pages": []}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(saved_imports, "import_archive", Mock(return_value=DATA))
    return saved_imports.SavedImports(tmp_path / "trajectory")


def save(store, actor=OWNER):
    return store.create(actor, io.BytesIO(b"original zip"), "轨迹.zip")


def test_duplicate_files_are_independent_and_survive_new_store(store):
    first, second = save(store), save(store)
    assert first["item"]["import_id"] != second["item"]["import_id"]
    items = store.list(OWNER, 1, 1)
    assert items["total"] == 2 and items["items"] == [second["item"]]
    other = saved_imports.SavedImports(store.root)
    assert other.read(OWNER, first["item"]["import_id"])["trajectory"] == DATA
    path = store.root / ".imports/local/admin" / first["item"]["import_id"]
    assert (path / "archive.zip").read_bytes() == b"original zip"
    assert (path / "record.json").is_file()


@pytest.mark.parametrize(
    "actor", [Actor("other", "local", "OPS"), Actor("admin", "other", "SU")]
)
def test_owner_is_local_identity_even_for_superadmin(store, actor):
    item = save(store)["item"]
    assert store.list(actor)["total"] == 0
    for action in (store.read, store.delete):
        if action == store.delete:
            assert action(actor, item["import_id"]) == {"deleted": True}
        else:
            with pytest.raises(QueryError) as error:
                action(actor, item["import_id"])
            assert error.value.status == 404
    assert store.read(OWNER, item["import_id"])["trajectory"] == DATA


def test_delete_is_idempotent_and_only_removes_one_archive(store):
    first, second = save(store)["item"], save(store)["item"]
    assert store.delete(OWNER, first["import_id"]) == {"deleted": True}
    assert store.delete(OWNER, first["import_id"]) == {"deleted": True}
    assert store.list(OWNER)["items"] == [second]
    assert not (store.root / ".imports/local/admin" / first["import_id"]).exists()


def test_bad_input_failure_and_cancel_do_not_publish(store, monkeypatch):
    parser = saved_imports.import_archive
    parser.side_effect = QueryError("invalid_archive", 422)
    with pytest.raises(QueryError):
        save(store)
    assert store.list(OWNER)["total"] == 0
    parser.side_effect = None
    with monkeypatch.context() as patch:
        patch.setattr(
            saved_imports, "write_all", Mock(side_effect=OSError("disk fault"))
        )
        with pytest.raises(QueryError) as error:
            save(store)
        assert error.value.status == 503
    assert store.list(OWNER)["total"] == 0
    assert save(store)["trajectory"] == DATA


def test_corruption_links_and_invalid_ids_fail_closed(store):
    item = save(store)["item"]
    path = store.root / ".imports/local/admin" / item["import_id"]
    (path / "archive.zip").write_bytes(b"damaged")
    with pytest.raises(QueryError) as error:
        store.read(OWNER, item["import_id"])
    assert error.value.status == 422
    for key in ("../admin", "not-a-uuid"):
        with pytest.raises(QueryError) as error:
            store.read(OWNER, key)
        assert error.value.status == 404
    (path / "archive.zip").unlink()
    target = store.root / "outside"
    target.write_bytes(b"private")
    (path / "archive.zip").symlink_to(target)
    with pytest.raises(QueryError):
        store.read(OWNER, item["import_id"])
    assert target.read_bytes() == b"private"


def test_pending_and_trash_reclaimed_and_boundaries(store):
    save(store)
    owner = store.root / ".imports/local/admin"
    for name in (
        ".pending-00000000-0000-0000-0000-000000000001",
        ".trash-00000000-0000-0000-0000-000000000002",
    ):
        (owner / name).mkdir()
        (owner / name / "archive.zip").write_bytes(b"partial")
    assert store.list(OWNER)["total"] == 1
    assert not list(owner.glob(".pending-*")) and not list(owner.glob(".trash-*"))
    for page, size in ((0, 20), (1, 101)):
        with pytest.raises(QueryError):
            store.list(OWNER, page, size)
    small = saved_imports.SavedImports(
        store.root, limits=replace(ExchangeLimits(), compressed_bytes=3)
    )
    with pytest.raises(QueryError) as error:
        save(small)
    assert error.value.status == 413
    with pytest.raises(QueryError) as error:
        save(store, Actor("user", "local", "USER"))
    assert error.value.status == 403


def test_concurrent_first_lock_creation_does_not_lose_the_new_record(
    store, monkeypatch
):
    import os

    original = saved_imports.Directory.open

    def macos_create_race(directory, name, flags):
        if name == ".lock" and flags & os.O_CREAT and not flags & os.O_EXCL:
            raise FileNotFoundError("controlled concurrent creation race")
        return original(directory, name, flags)

    monkeypatch.setattr(saved_imports.Directory, "open", macos_create_race)
    item = save(store)["item"]
    assert store.list(OWNER)["items"] == [item]
