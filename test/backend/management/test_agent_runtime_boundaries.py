# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Responsibility regressions for UT-BE-ARB-001/002/003."""

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
import tokenize
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]


def test_retired_in_process_execution_chain_is_removed():
    retired = [
        "backend/runtime/agentos/legacy_admission.py",
        "backend/runtime/agentos/legacy_tracking.py",
        "backend/runtime/agentos/legacy_producer.py",
        "backend/runtime/agentos/admission.py",
        "backend/management/services/agent/run.py",
        "backend/management/services/agent/subscription.py",
        "backend/management/services/agent/execution.py",
        "backend/management/services/agent/lifecycle.py",
        "backend/runtime/adapters/nexent/legacy_workspace.py",
    ]
    assert not [name for name in retired if (ROOT / name).exists()]


def test_preparation_and_factory_have_no_in_process_materializer():
    preparation = (ROOT / "backend/management/services/agent/preparation/run.py").read_text(encoding="utf-8")
    factory = (ROOT / "backend/runtime/adapters/nexent/factory.py").read_text(encoding="utf-8")
    assert "legacy_materializer" not in preparation
    assert "LegacyRunFactory" not in factory
    assert "materialize_legacy_run" not in factory


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


def test_management_app_serves_liveness_without_runtime_source():
    script = """
import asyncio
import importlib.abc
import sys
from unittest.mock import patch

import httpx

class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"runtime", "backend.runtime"} or fullname.startswith(("runtime.", "backend.runtime.")):
            raise AssertionError(f"Management imported peer source: {fullname}")

sys.meta_path.insert(0, BlockRuntime())
with patch("nexent.core.nlp.stopwords.load_stopwords"):
    from management.api.application import app
    from management.services.agent import runtime_client, prepared_turn

assert not hasattr(runtime_client, "agent_run_manager")
assert not hasattr(prepared_turn, "_agent_stream_producer_tasks")

assert "post" in app.openapi()["paths"]["/agent/run"]

async def verify():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management") as client:
        result = await client.get("/health/live")
        assert result.status_code == 200 and result.json() == {"status": "alive"}

asyncio.run(verify())
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / path) for path in ("", "backend", "sdk"))}
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_source_scan_ignores_dependencies_but_detects_owned_legacy_imports(tmp_path):
    for folder in [".venv/site-packages", "node_modules/package", "__pycache__", ".pytest-tmp", "vendor-env/site-packages"]:
        path = tmp_path / "backend" / folder / "non_utf8.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xa4\n")
    (tmp_path / "backend/vendor-env/pyvenv.cfg").write_text("", encoding="utf-8")
    owned = tmp_path / "backend/owned.py"
    owned.write_text("# Owned source\nfrom agents import legacy\n", encoding="utf-8")
    assert _legacy_agent_imports(tmp_path) == [("backend/owned.py", 2, "agents")]


def test_management_compiler_and_legacy_streams_do_not_import_runtime_factory_or_sdk_alias():
    for name in ("preparation/run.py", "prepared_projection.py", "runtime_client.py", "prepared_turn.py"):
        path = ROOT / "backend" / "management" / "services" / "agent" / name
        tree = ast.parse(path.read_bytes(), filename=str(path))
        forbidden = "runtime" if name.startswith("preparation/") else "runtime.adapters"
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom):
                modules = [f"{node.module or ''}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            assert all(
                name != forbidden and not name.startswith(f"{forbidden}.")
                for name in (module.removeprefix("backend.") for module in modules)
            ), (path, node.lineno)


def test_management_run_and_subscription_do_not_import_runtime_thread_manager():
    for name in ("runtime_client.py", "prepared_turn.py"):
        path = ROOT / "backend" / "management" / "services" / "agent" / name
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules = [f"{node.module or ''}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            assert not any(
                module.removeprefix("backend.").split(".")[:2] == ["runtime", "thread_management"]
                for module in modules
            ), (path, node.lineno)


def test_management_sources_do_not_import_runtime():
    for path in (ROOT / "backend/management").rglob("*.py"):
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules = [f"{node.module or ''}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            assert all(module.removeprefix("backend.").split(".")[0] != "runtime" for module in modules), (path, node.lineno)


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
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "canonicalize_assistant_units" in functions
    execution = (ROOT / "backend/management/services/agent/prepared_projection.py").read_text(
        encoding="utf-8"
    )
    assert "canonicalize_assistant_units(" in execution
    assert "persist_prepared_assistant_projection" in execution


def test_raw_preparation_does_not_load_legacy_subscription():
    script = """
import importlib.abc
import sys
from unittest.mock import patch

class BlockLegacyExecution(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"management.services.agent." + name for name in ("subscription", "run", "execution", "lifecycle")} | {"backend.management.services.agent." + name for name in ("subscription", "run", "execution", "lifecycle")}:
            raise AssertionError(f"Preparation imported retired execution facade: {fullname}")
        if fullname in {"runtime", "backend.runtime"} or fullname.startswith(("runtime.", "backend.runtime.")):
            raise AssertionError(f"Preparation imported Runtime source: {fullname}")

sys.meta_path.insert(0, BlockLegacyExecution())
with patch("nexent.core.nlp.stopwords.load_stopwords"):
    from management.services.agent.preparation.evaluation_snapshot import prepare_debug_snapshot
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / path) for path in ("", "backend", "sdk"))}
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_runtime_sources_do_not_import_management():
    for path in (ROOT / "backend/runtime").rglob("*.py"):
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            assert all(module.removeprefix("backend.").split(".")[0] != "management" for module in modules), (path, node.lineno)


def test_runtime_app_serves_liveness_without_management_source():
    script = """
import asyncio, importlib.abc, sys
from unittest.mock import patch
import httpx
class BlockManagement(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"management", "backend.management"} or fullname.startswith(("management.", "backend.management.")):
            raise AssertionError(f"Runtime imported peer source: {fullname}")
sys.meta_path.insert(0, BlockManagement())
with patch("nexent.core.nlp.stopwords.load_stopwords"):
    from runtime.api.application import app
assert not any("/compat/" in getattr(route, "path", "") for route in app.routes)
assert not {"/agent/run", "/agent/stop/{run_id}"} & {getattr(route, "path", "") for route in app.routes}
async def verify():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://runtime") as client:
        result=await client.get("/health/live")
        assert result.status_code==200 and result.json()=={"status":"alive"}
asyncio.run(verify())
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / path) for path in ("", "backend", "sdk"))}
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
