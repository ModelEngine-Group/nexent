# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Ownership and import regressions for the API/persistence directory migration."""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test.common.source_files import iter_project_python_files


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"


@pytest.mark.parametrize("legacy", ["apps", "database"])
def test_obsolete_implementation_packages_are_empty(legacy):
    assert not list((BACKEND / legacy).glob("*.py"))


@pytest.mark.parametrize("service", ["management", "gateway", "runtime", "data_process"])
def test_business_api_modules_are_importable_packages(service):
    api = BACKEND / service / "api"
    assert (api / "__init__.py").is_file()
    routes = [path for path in api.rglob("*.py") if path.name != "__init__.py"]
    assert routes
    for path in routes:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        tree = ast.parse(source)
        assert not any(isinstance(node, ast.ClassDef) for node in tree.body), path


def test_contracts_do_not_depend_on_backend_implementations():
    forbidden = ("services", "database", "management", "runtime", "gateway", "contracts.constants.environment", "sqlalchemy")
    for path in (BACKEND / "contracts").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            assert not any(module == prefix or module.startswith(prefix + ".") for module in modules for prefix in forbidden), path


@pytest.mark.parametrize("source_root", ["backend", "sdk", "test"])
def test_project_imports_do_not_reference_removed_packages(source_root):
    for path in iter_project_python_files(ROOT / source_root):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                modules = [node.module or ""]
            elif isinstance(node, ast.Call) and node.args:
                function = node.func
                name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
                argument = node.args[0]
                if name in {"import_module", "__import__"} and isinstance(argument, ast.Constant):
                    if isinstance(argument.value, str):
                        modules = [argument.value]
            assert not any(
                module.removeprefix("backend.").split(".")[0] in {"apps", "database"}
                for module in modules
            ), path


def test_shared_helpers_do_not_import_database_clients():
    for filename in ("orm.py", "audit_fields.py", "skill_params.py", "file_http.py", "a2a.py"):
        path = BACKEND / "management/utils" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("management.db", "database")), path


def test_model_registry_retains_shared_metadata_without_opening_clients():
    program = """
import json
import sys
from management.db import models
from management.db.base import SimpleTableBase, TableBase
classes = {value for value in vars(models).values()
           if isinstance(value, type) and hasattr(value, '__tablename__')}
assert len(classes) == 74
assert len(TableBase.metadata.tables) == 69
assert len(SimpleTableBase.metadata.tables) == 5
assert models.OuterApiTool is models.OuterApiService
assert models.AgentEvaluation.__module__ == 'management.db.evaluation.models'
assert models.ModelMonitoringRecord.__module__ == 'management.db.monitoring.models'
assert all(value.metadata is TableBase.metadata or value.metadata is SimpleTableBase.metadata
           for value in classes)
assert 'management.db.client' not in sys.modules
print(json.dumps({'tables': len(classes), 'client_loaded': False}))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(BACKEND)
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"tables": 74, "client_loaded": False}
