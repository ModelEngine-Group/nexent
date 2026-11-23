# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Assemble the local Python import closure for a backend service image."""

import ast
import sys
from collections import deque
from importlib.util import resolve_name
from pathlib import Path
from shutil import copyfile


SERVICE_MODULES = {
    "mcp-service": ("backend.http.mcp_service",),
    "ops": ("backend.http.ops_service", "ops.scripts.backfill_trajectory_summaries"),
}


def module_file(source: Path, name: str) -> Path | None:
    parts = name.split(".")
    if not all(part.isidentifier() for part in parts):
        return None
    parent = source if parts[0] in {"backend", "infrastructure"} else source / "backend"
    path = parent.joinpath(*parts)
    return next((file for file in (path / "__init__.py", path.with_suffix(".py")) if file.is_file()), None)


def imported_modules(file: Path, module: str):
    package = module if file.name == "__init__.py" else module.rpartition(".")[0]
    for node in ast.walk(ast.parse(file.read_text(encoding="utf-8-sig"), filename=str(file))):
        if isinstance(node, ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            owner = node.module or ""
            if node.level:
                owner = resolve_name("." * node.level + owner, package)
            yield owner
            yield from (f"{owner}.{item.name}" for item in node.names if item.name != "*")
        elif isinstance(node, ast.Call) and node.args:
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", None)
            first = node.args[0]
            if name in {"import_module", "__import__"} and isinstance(first, ast.Constant) and isinstance(first.value, str):
                if not first.value.startswith("."):
                    yield first.value


def collect_sources(source: Path, modules: tuple[str, ...]) -> set[Path]:
    for module in modules:
        if module_file(source, module) is None:
            raise FileNotFoundError(module)
    pending = deque(modules)
    visited = set()
    files = set()
    while pending:
        parts = pending.popleft().split(".")
        for count in range(1, len(parts) + 1):
            module = ".".join(parts[:count])
            if module in visited:
                continue
            visited.add(module)
            file = module_file(source, module)
            if file is not None:
                files.add(file.relative_to(source))
                pending.extend(imported_modules(file, module))
    return files


def main():
    source, target = map(Path, sys.argv[1:3])
    for relative in sorted(collect_sources(source, SERVICE_MODULES[sys.argv[3]])):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source / relative, destination)


if __name__ == "__main__":
    main()
