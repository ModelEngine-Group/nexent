# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unbound local uploads become owned immutable bytes before KB binding."""

import io
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from management.services.file import staged_local_source as module
from nexent.storage.errors import Conflict, OutcomeUnknown, ScopeDenied, Unavailable

from infrastructure.file_processing.local_source import open_staged_local_source
from test.backend.services.test_local_source_staging import (  # noqa: F401
    context,
    staging,
)


@pytest.fixture
def publication(staging, monkeypatch, tmp_path):  # noqa: F811
    journal, _, port, _, _ = staging

    @contextmanager
    def ports(tenant, user, *, context):
        assert (tenant, user) == ("t", "u")
        yield port

    monkeypatch.setattr(module, "local_source_staging_port", ports)
    return SimpleNamespace(
        journal=journal,
        actor=SimpleNamespace(tenant_id="t", user_id="u"),
        root=tmp_path,
    )


def test_stage_upload_pins_bytes_and_returns_registered_exclusive_path(publication):
    p = publication
    stream = io.BytesIO(b"owned source")
    stream.seek(3)
    first = module.stage_local_source(stream, "source.txt", p.actor, p.root, context())
    second = module.stage_local_source(stream, "source.txt", p.actor, p.root, context())
    assert first["state"] == "READY" and first["knowledge_id"] is None
    assert first["local_source_path"] != second["local_source_path"]
    assert Path(first["local_source_path"]).read_bytes() == b"owned source"
    assert stream.tell() == 3
    assert p.journal.find(first["local_source_path"], context=context()) == first
    with open_staged_local_source(first, p.root, context()) as source:
        assert source.read() == b"owned source"


def test_staged_source_changed_after_upload_is_rejected(publication):
    p = publication
    row = module.stage_local_source(
        io.BytesIO(b"owned"), "a.txt", p.actor, p.root, context()
    )
    Path(row["local_source_path"]).write_bytes(b"other")
    with pytest.raises(Conflict):
        open_staged_local_source(row, p.root, context())


def test_arbitrary_or_foreign_local_path_never_opened(publication):
    p = publication
    row = module.stage_local_source(
        io.BytesIO(b"owned"), "a.txt", p.actor, p.root, context()
    )
    row["local_source_path"] = str(p.root / "arbitrary.txt")
    with pytest.raises(ScopeDenied):
        open_staged_local_source(row, p.root, context())


def test_empty_filename_never_publishes_a_directory_as_a_source(publication):
    p = publication
    with pytest.raises(ScopeDenied):
        module.stage_local_source(io.BytesIO(b"owned"), "", p.actor, p.root, context())
    assert not list(p.root.iterdir())


def test_confirmed_publication_with_lost_close_stays_unknown(publication, monkeypatch):
    p = publication
    original = module.local_source_staging_port

    @contextmanager
    def lost_close(*args, **kwargs):
        with original(*args, **kwargs) as records:
            yield records
        raise Unavailable()

    monkeypatch.setattr(module, "local_source_staging_port", lost_close)
    with pytest.raises(OutcomeUnknown):
        module.stage_local_source(
            io.BytesIO(b"owned"), "a.txt", p.actor, p.root, context()
        )
    paths = list(p.root.glob("knowledge/*/a.txt"))
    assert len(paths) == 1
    assert p.journal.find(str(paths[0]), context=context())["state"] == "READY"
