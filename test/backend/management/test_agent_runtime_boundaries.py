# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Responsibility regressions for UT-BE-ARB-001/002/003."""

import ast
import importlib.util
import os
from pathlib import Path
import tokenize
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]


def load_file(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project_python_sources(root):
    """Prune dependency/runtime artifacts before visiting project Python sources."""
    for folder in ("backend", "test/backend", "test-e2e/cases", "test-e2e/infra/automation"):
        for directory, directories, filenames in os.walk(root / folder):
            directories[:] = [
                name for name in directories
                if not name.startswith(".") and name not in {"__pycache__", "node_modules"}
                and not (Path(directory) / name / "pyvenv.cfg").is_file()
            ]
            for filename in filenames:
                if filename.endswith(".py"):
                    yield Path(directory) / filename


def _legacy_agent_imports(root):
    violations = []
    for path in _project_python_sources(root):
        with tokenize.open(path) as stream:
            tree = ast.parse(stream.read(), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if module in {"agents", "backend.agents"} or module.startswith(
                    ("agents.", "backend.agents.")
                ):
                    violations.append((path.relative_to(root).as_posix(), node.lineno, module))
    return violations


def test_ut_be_arb_001_product_callers_use_canonical_owners():
    assert not (ROOT / "backend/agents").exists()
    assert not _legacy_agent_imports(ROOT)


def test_source_scan_ignores_dependencies_but_detects_owned_legacy_imports(tmp_path):
    for folder in [".venv/site-packages", "node_modules/package", "__pycache__", ".pytest-tmp", "vendor-env/site-packages"]:
        path = tmp_path / "backend" / folder / "non_utf8.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xa4\n")
    (tmp_path / "backend/vendor-env/pyvenv.cfg").write_text("", encoding="utf-8")
    owned = tmp_path / "backend/owned.py"
    owned.write_text("# Owned source\nfrom agents import legacy\n", encoding="utf-8")
    assert _legacy_agent_imports(tmp_path) == [("backend/owned.py", 2, "agents")]


def test_ut_be_arb_002_factory_preserves_prepared_values(monkeypatch):
    factory = load_file("backend/runtime/adapters/nexent/factory.py", "arb_factory")
    constructor = Mock(side_effect=lambda **values: SimpleNamespace(**values))
    monkeypatch.setattr(factory, "AgentRunInfo", constructor)
    query = "hello"
    observer = object()
    stop = object()
    model_configs = []
    result = factory.build_run_info(
        query=query,
        model_config_list=model_configs,
        observer=observer,
        agent_config=object(),
        stop_event=stop,
        history=[],
        user_context={"tenant_id": "t"},
    )
    assert result.query == query
    assert result.observer is observer
    assert result.stop_event is stop
    assert result.model_config_list is model_configs
    assert result.user_context == {"tenant_id": "t"}
    constructor.assert_called_once()


def test_ut_be_arb_002_runtime_modules_have_no_business_or_environment_reads():
    paths = [
        ROOT / "backend/runtime/adapters/nexent/factory.py",
        ROOT / "backend/runtime/executions.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("management.", "agents.", "consts.")
                ), (path, node.module)
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"getenv", "environ"}, path


def test_ut_be_arb_003_registry_keeps_owner_and_cancels_local_resources():
    module = load_file("backend/runtime/executions.py", "arb_executions")
    registry = module.LocalExecutionRegistry()
    registry.agent_runs.clear()
    registry._reservations.clear()
    registry._agent_capacity_counts.clear()
    registry._agent_capacity_tokens.clear()
    worker = SimpleNamespace(
        stop_event=Mock(),
        cancellation_scope=Mock(),
        thread_manager=Mock(),
        thread_execution_id="exec-1",
    )
    replacement = SimpleNamespace()
    token = registry.reserve_agent_run(7, "u")
    registry.register_agent_run(7, worker, "u", reservation_token=token)
    assert not registry.unregister_agent_run(7, "u", agent_run_info=replacement)
    assert registry.get_agent_run_info(7, "u") is worker
    assert registry.stop_agent_run(7, "u")
    worker.stop_event.set.assert_called_once()
    worker.cancellation_scope.cancel.assert_called_once()
    worker.thread_manager.cancel.assert_called_once()
    assert registry.unregister_agent_run(7, "u", agent_run_info=worker)
    assert registry.get_active_run_count() == 0


def test_factory_owns_local_observer_and_stop_event(monkeypatch):
    factory = load_file(
        "backend/runtime/adapters/nexent/factory.py", "arb_factory_defaults"
    )
    observer = Mock()
    stop = Mock()
    make_observer = Mock(return_value=observer)
    monkeypatch.setattr(factory, "MessageObserver", make_observer)
    monkeypatch.setattr(factory.threading, "Event", Mock(return_value=stop))
    monkeypatch.setattr(
        factory, "AgentRunInfo", lambda **values: SimpleNamespace(**values)
    )
    result = factory.build_run_info(
        language="en", query="hello", model_config_list=[], agent_config=object()
    )
    assert result.observer is observer
    assert result.stop_event is stop
    make_observer.assert_called_once_with(lang="en")
    assert not hasattr(result, "language")


def test_assistant_projection_is_a_separate_responsibility():
    path = ROOT / "backend/management/services/agent/persistence.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {n.name for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
    assert "finalize_assistant_projection" in functions
    execution = (ROOT / "backend/management/services/agent/execution.py").read_text(
        encoding="utf-8"
    )
    execution_tree = ast.parse(execution)
    assignments = [node for node in ast.walk(execution_tree) if isinstance(node, ast.Assign)]
    assert any(
        isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "finalize_assistant_projection"
        and any(
            isinstance(target, ast.Name) and target.id == "projection"
            for target in node.targets
        )
        for node in assignments
    )
    awaits = [node.value for node in ast.walk(execution_tree) if isinstance(node, ast.Await)]
    assert any(isinstance(node, ast.Name) and node.id == "projection" for node in awaits)
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "settle_background_projection"
        and any(isinstance(arg, ast.Name) and arg.id == "projection" for arg in node.args)
        for node in awaits
    )
