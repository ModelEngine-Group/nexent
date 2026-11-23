"""Regression coverage for architecture scans beside local Python environments."""

import pytest

from test.common.source_files import iter_project_python_files


@pytest.mark.parametrize("environment", [".venv", "venv", "custom-python"])
def test_scan_excludes_virtualenv_non_utf8_dependency(environment, tmp_path):
    root = tmp_path / "backend"
    source = root / "services" / "prompt.py"
    source.parent.mkdir(parents=True)
    source.write_text("# project source\n", encoding="utf-8")
    venv_root = root / environment
    dependency = venv_root / "lib/python3.11/site-packages/sample.py"
    dependency.parent.mkdir(parents=True)
    (venv_root / "pyvenv.cfg").write_text("home = python\n", encoding="utf-8")
    dependency.write_bytes("# -*- coding: big5 -*-\n# 中文\n".encode("big5"))

    assert list(iter_project_python_files(root)) == [source]
    assert list(iter_project_python_files(venv_root)) == []


@pytest.mark.parametrize("directory", ["node_modules", "__pycache__", ".git"])
def test_scan_excludes_dependency_and_cache_directories(directory, tmp_path):
    ignored = tmp_path / directory / "sample.py"
    ignored.parent.mkdir()
    ignored.write_bytes(b"\xff")
    source = tmp_path / "app.py"
    source.write_text("# project source\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("notes", encoding="utf-8")

    assert list(iter_project_python_files(tmp_path)) == [source]


def test_scan_keeps_business_source_in_package_directories(tmp_path):
    source = tmp_path / "services/custom/prompt.py"
    source.parent.mkdir(parents=True)
    source.write_text("nexent.core.prompts.auxiliary\n", encoding="utf-8")

    assert list(iter_project_python_files(tmp_path)) == [source]
    assert "nexent.core.prompts.auxiliary" in source.read_text(encoding="utf-8")
