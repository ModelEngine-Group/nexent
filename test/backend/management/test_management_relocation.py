# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Regression guards for canonical ownership and relocation-sensitive resources."""

import ast
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
FLAT_SERVICE_MODULES = {
    "nl2agent_configuration",
    "nl2agent_prompt_service",
    "nl2agent_resource_flow",
    "nl2agent_retrieval_progress",
    "nl2agent_semantic_retrieval",
    "nl2agent_state_service",
}


def test_flat_service_exclusions_match_remaining_scope():
    services_dir = BACKEND / "services"
    assert {p.relative_to(services_dir).as_posix() for p in services_dir.rglob("*.py")} == {
        "__init__.py",
        *(f"{module}.py" for module in FLAT_SERVICE_MODULES),
    }
    assert not list((BACKEND / "utils").glob("*.py"))
    assert (BACKEND / "runtime/api/application.py").is_file()
    assert (BACKEND / "gateway/application.py").is_file()
    assert not (BACKEND / "gateway/api").exists()
    assert (BACKEND / "management/api/northbound.py").is_file()
    assert (BACKEND / "runtime/api/__init__.py").is_file()


def test_production_imports_use_canonical_owners():
    unexpected = []
    allowed_imports = {f"services.{module}" for module in FLAT_SERVICE_MODULES}
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "backend"], cwd=ROOT, text=True,
    ).splitlines()
    for relative in paths:
        path = ROOT / relative
        if path.suffix != ".py" or not path.is_file():
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
                if name.startswith(("utils.", "services.")) and name not in allowed_imports:
                    unexpected.append((path.relative_to(ROOT).as_posix(), name))
    assert unexpected == []


def test_relocated_service_implementations_stay_below_1500_lines():
    """Keep the original service/helper migration budget on its owned files."""
    paths = []
    for directory in ("management/services", "management/utils", "infrastructure"):
        paths.extend((BACKEND / directory).rglob("*.py"))
    # These shared contracts belonged to the service migration. Later API/DB
    # relocations have separate ownership checks in test_api_db_directory_architecture.
    paths.extend(BACKEND / "contracts" / name for name in (
        "__init__.py", "a2a.py", "agent.py", "automation.py", "file.py",
        "knowledge.py", "model.py", "constants/constants.py", "tag.py",
    ))
    oversized = {}
    for path in paths:
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
