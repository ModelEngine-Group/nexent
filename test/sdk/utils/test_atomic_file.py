import os
import stat

import pytest

from nexent.utils.atomic_file import _fsync_directory, atomic_write_bytes, atomic_write_text


def test_atomic_write_text_replaces_content_without_leaving_temp_files(tmp_path):
    target = tmp_path / "config" / "config.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)

    atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert list(target.parent.iterdir()) == [target]


def test_atomic_write_bytes_creates_parent_directory(tmp_path):
    target = tmp_path / "nested" / "artifact.bin"

    atomic_write_bytes(target, b"payload")

    assert target.read_bytes() == b"payload"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_atomic_write_cleans_temporary_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "SKILL.md"

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(target, "content")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_directory_sync_is_best_effort(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unsupported")))

    _fsync_directory(tmp_path)


def test_directory_sync_closes_descriptor_when_fsync_fails(tmp_path, monkeypatch):
    close_calls = []
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: 123)
    monkeypatch.setattr(os, "fsync", lambda _descriptor: (_ for _ in ()).throw(OSError("unsupported")))
    monkeypatch.setattr(os, "close", close_calls.append)

    _fsync_directory(tmp_path)

    assert close_calls == [123]
