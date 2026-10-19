# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Regression guards for canonical ownership and relocation-sensitive resources."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"


def test_flat_service_exclusions_match_deferred_scope():
    assert {p.name for p in (BACKEND / "services").rglob("*.py")} == {
        "__init__.py", "nl2skill_service.py", "skill_repository_service.py",
        "nl2agent_service.py", "northbound_service.py", "workspace_cleanup_service.py",
    }
    assert not list((BACKEND / "utils").glob("*.py"))
    assert not (BACKEND / "gateway").exists()
    assert not list((BACKEND / "runtime").rglob("*.py"))


def test_production_imports_use_canonical_owners():
    unexpected = []
    for path in BACKEND.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                name = name.removeprefix("backend.")
                if name.startswith("utils.") or (
                    name.startswith("services.")
                    and name not in {
                        "services.nl2skill_service", "services.skill_repository_service",
                        "services.nl2agent_service", "services.northbound_service",
                        "services.workspace_cleanup_service",
                    }
                ):
                    unexpected.append((path.relative_to(ROOT).as_posix(), name))
    assert unexpected == []


def test_relocated_implementations_stay_below_1500_lines():
    oversized = {}
    for directory in ("management", "infrastructure", "runtime", "contracts"):
        for path in (BACKEND / directory).rglob("*.py"):
            count = len(path.read_text(encoding="utf-8").splitlines())
            if count > 1500:
                oversized[path.relative_to(ROOT).as_posix()] = count
    assert oversized == {}


def test_plugin_root_still_resolves_to_backend_resources():
    path = BACKEND / "management/services/memory/providers/plugins.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name)
                              and target.id == "BUILTIN_MEMORY_PROVIDER_PLUGINS_DIR"
                              for target in node.targets))
    value = eval(compile(ast.Expression(assignment.value), str(path), "eval"),
                 {"Path": Path, "__file__": str(path)})
    assert value == BACKEND / "memory_provider_plugins"
    assert value.is_dir()


def test_langchain_root_still_resolves_to_backend_tools():
    path = BACKEND / "management/services/tool/langchain.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "LANGCHAIN_TOOLS_DIR"
                              for target in node.targets))
    import os

    value = eval(compile(ast.Expression(assignment.value), str(path), "eval"),
                 {"Path": Path, "os": os, "str": str, "__file__": str(path)})
    assert Path(value) == BACKEND / "tool_collection/langchain"


def test_partitioned_modules_have_no_initialization_import_cycles():
    modules = {}
    for package in ("evaluation", "repository/agent", "mcp", "tool"):
        for path in (BACKEND / "management/services" / package).rglob("*.py"):
            name = path.relative_to(BACKEND).with_suffix("").as_posix().replace("/", ".")
            modules[name] = ast.parse(path.read_text(encoding="utf-8"))
    graph = {name: set() for name in modules}
    for name, tree in modules.items():
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                targets = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                continue
            graph[name].update(target for target in targets if target in modules)

    visited = set()

    def visit(name, active):
        assert name not in active, f"Module initialization cycle through {name}"
        if name in visited:
            return
        for dependency in graph[name]:
            visit(dependency, active | {name})
        visited.add(name)

    for name in graph:
        visit(name, set())
