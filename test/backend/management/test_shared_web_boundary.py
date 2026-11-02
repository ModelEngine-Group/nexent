# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The shared Web layer must construct independently of business-service source."""

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3] / "backend"


@pytest.mark.parametrize("file", ["application.py", "health.py"])
def test_shared_web_has_no_business_service_imports(file):
    tree = ast.parse((BACKEND / "infrastructure/web" / file).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = ([node.module] if isinstance(node, ast.ImportFrom)
                 else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
        assert all(name and name.split(".")[0] not in {"management", "runtime"} for name in names)


@pytest.mark.parametrize("path", ["management/api/application.py", "management/api/northbound_application.py",
                                  "runtime/api/application.py"])
def test_backend_assemblies_use_the_canonical_shared_factory(path):
    tree = ast.parse((BACKEND / path).read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and any(alias.name == "create_app" for alias in node.names)]
    assert imports == ["infrastructure.web.application"]


def test_legacy_web_imports_reference_the_same_implementation():
    from infrastructure.web.application import create_app, register_exception_handlers
    from infrastructure.web.health import install_health_contract
    from management.utils import app_factory, health

    assert app_factory.create_app is create_app
    assert app_factory.register_exception_handlers is register_exception_handlers
    assert health.install_health_contract is install_health_contract
    assert create_app.__module__ == "infrastructure.web.application"


def test_source_only_shared_web_serves_without_business_services(tmp_path):
    for package in ("infrastructure", "contracts"):
        (tmp_path / package).mkdir()
        (tmp_path / package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copytree(BACKEND / "infrastructure/web", tmp_path / "infrastructure/web",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(BACKEND / "contracts/errors", tmp_path / "contracts/errors",
                    ignore=shutil.ignore_patterns("__pycache__"))
    code = '''import importlib.abc,json,sys
sys.path.insert(0,sys.argv[1])
class RejectBusiness(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'management','runtime','nexent'}:
            raise AssertionError('Unexpected business/SDK import '+fullname)
sys.meta_path.insert(0,RejectBusiness())
from infrastructure.web.application import create_app
from fastapi.testclient import TestClient
app=create_app(enable_monitoring=False)
with TestClient(app) as client:
    assert client.get('/health/live').json()=={'status':'alive'}
    assert client.get('/health/ready').json()=={'status':'ready'}
assert not {'management','runtime','nexent'} & sys.modules.keys()
print(json.dumps({'startup':True,'health':True,'business_sources':False}))
'''
    result = subprocess.run([sys.executable, "-I", "-c", code, str(tmp_path)], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"startup": True, "health": True, "business_sources": False}
