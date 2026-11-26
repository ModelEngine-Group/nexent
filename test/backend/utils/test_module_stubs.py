# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Module-stub isolation must never execute third-party lazy attribute hooks."""

import sys
from pathlib import Path
from types import ModuleType

import pytest

from test.common.module_stubs import capture_module_stubs


def lazy_parent(name):
    parent = ModuleType(name)
    calls = []
    def lazy_attribute(attribute):
        calls.append(attribute)
        raise RecursionError("Controlled lazy-module recursion")
    parent.__getattr__ = lazy_attribute
    return parent, calls


@pytest.mark.parametrize("exported", [False, True])
def test_capture_removes_new_children_without_lazy_imports(monkeypatch, exported):
    parent, calls = lazy_parent("_nexent_stub_lazy_capture")
    monkeypatch.setitem(sys.modules, parent.__name__, parent)
    original = sys.modules.copy()
    child = ModuleType(parent.__name__ + ".child")
    monkeypatch.setitem(sys.modules, child.__name__, child)
    if exported:
        parent.__dict__["child"] = child
    capture_module_stubs(original)
    assert child.__name__ not in sys.modules
    assert "child" not in parent.__dict__
    assert calls == []


def test_install_and_undo_missing_export_use_dictionary_state(monkeypatch):
    parent, calls = lazy_parent("_nexent_stub_lazy_install")
    monkeypatch.setitem(sys.modules, parent.__name__, parent)
    original = sys.modules.copy()
    child = ModuleType(parent.__name__ + ".child")
    monkeypatch.setitem(sys.modules, child.__name__, child)
    parent.__dict__["child"] = child
    install = capture_module_stubs(original)
    for _ in range(2):
        with monkeypatch.context() as scope:
            install(scope)
            assert sys.modules[child.__name__] is child
            assert parent.__dict__["child"] is child
        assert child.__name__ not in sys.modules
        assert "child" not in parent.__dict__
    assert calls == []


def test_replaced_child_restores_module_and_parent_identity(monkeypatch):
    parent, calls = lazy_parent("_nexent_stub_replaced")
    original_child = ModuleType(parent.__name__ + ".child")
    parent.__dict__["child"] = original_child
    monkeypatch.setitem(sys.modules, parent.__name__, parent)
    monkeypatch.setitem(sys.modules, original_child.__name__, original_child)
    original = sys.modules.copy()
    replacement = ModuleType(original_child.__name__)
    monkeypatch.setitem(sys.modules, replacement.__name__, replacement)
    parent.__dict__["child"] = replacement
    install = capture_module_stubs(original)
    assert sys.modules[replacement.__name__] is original_child
    assert parent.__dict__["child"] is original_child
    with monkeypatch.context() as scope:
        install(scope)
        assert sys.modules[replacement.__name__] is replacement
        assert parent.__dict__["child"] is replacement
    assert sys.modules[replacement.__name__] is original_child
    assert parent.__dict__["child"] is original_child
    assert calls == []


def test_capture_and_install_top_level_module_without_a_parent(monkeypatch):
    name = "_nexent_stub_top_level"
    original = sys.modules.copy()
    module = ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    install = capture_module_stubs(original)
    assert name not in sys.modules
    with monkeypatch.context() as scope:
        install(scope)
        assert sys.modules[name] is module
    assert name not in sys.modules


@pytest.mark.parametrize("location", ["temporary", "project_venv"])
def test_new_third_party_imports_stay_loaded(monkeypatch, tmp_path, location):
    original = sys.modules.copy()
    parent, calls = lazy_parent("_nexent_native_dependency")
    folder = tmp_path / "site-packages"
    if location == "project_venv":
        folder = Path(__file__).resolve().parents[3] / "backend/.venv/Lib/site-packages"
    parent.__file__ = str(folder / "dependency" / "__init__.py")
    child = ModuleType(parent.__name__ + ".native")
    child.__file__ = str(folder / "dependency" / "native.so")
    parent.__dict__["native"] = child
    monkeypatch.setitem(sys.modules, parent.__name__, parent)
    monkeypatch.setitem(sys.modules, child.__name__, child)
    install = capture_module_stubs(original)
    assert sys.modules[parent.__name__] is parent
    assert sys.modules[child.__name__] is child
    with monkeypatch.context() as scope:
        install(scope)
        assert parent.__dict__["native"] is child
    assert sys.modules[parent.__name__] is parent
    assert sys.modules[child.__name__] is child
    assert calls == []


def test_new_project_imports_are_scoped_to_the_fixture(monkeypatch):
    parent = ModuleType("_nexent_project_dependency")
    parent.__file__ = str(Path(__file__).resolve())
    original = sys.modules.copy()
    monkeypatch.setitem(sys.modules, parent.__name__, parent)
    install = capture_module_stubs(original)
    assert parent.__name__ not in sys.modules
    with monkeypatch.context() as scope:
        install(scope)
        assert sys.modules[parent.__name__] is parent
    assert parent.__name__ not in sys.modules
