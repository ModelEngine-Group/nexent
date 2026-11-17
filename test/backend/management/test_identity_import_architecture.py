# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Identity persistence must not depend on application services or lazy imports."""

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3] / "backend"


@pytest.mark.parametrize("name", ["account", "membership", "roles", "user_tenant"])
def test_identity_persistence_has_only_module_level_lower_layer_imports(name):
    tree = ast.parse((BACKEND / "management/db/identity" / f"{name}.py").read_text(encoding="utf-8"))
    top_level_imports = {id(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert id(node) in top_level_imports, (name, node.lineno, "Function-local import")
            modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names]
            assert not any(module.startswith(("management.services", "services.")) for module in modules), (
                name,
                node.lineno,
                "Persistence depends on a service",
            )
