# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Canonical sandbox submodules keep isolation without a flat compatibility facade."""
import ast
import importlib
import pickle
import subprocess
import sys
from pathlib import Path

import pytest
from nexent.core.agents.sandbox import config, execution, tls


@pytest.mark.parametrize("name", ["SandboxLevel", "SandboxScope", "ShellPolicy", "SandboxConfig"])
def test_configuration_types_have_a_single_canonical_definition(name):
    symbol = getattr(config, name)
    assert getattr(execution, name) is symbol
    assert symbol.__module__ == config.__name__
    assert pickle.loads(pickle.dumps(symbol)) is symbol


def test_sandbox_is_a_package_without_flat_api_or_patch_forwarding():
    package = importlib.import_module("nexent.core.agents.sandbox")
    assert package.__spec__.submodule_search_locations is not None
    assert Path(config.__file__).parent == Path(execution.__file__).parent
    assert Path(package.__file__).name == "__init__.py"
    assert not Path(package.__file__).parent.with_suffix(".py").exists()
    assert "__getattr__" not in vars(package)
    assert "SandboxConfig" not in vars(package)
    assert "build_python_executor" not in vars(package)


def test_configuration_import_does_not_load_execution_or_tls():
    sdk = Path(__file__).resolve().parents[4] / "sdk"
    code = f'''
import sys,importlib.abc
sys.path.insert(0,{str(sdk)!r})
class ConfigOnly(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname in {{'nexent.core.agents.sandbox.execution','nexent.core.agents.sandbox.tls'}}:
            raise AssertionError(fullname)
sys.meta_path.insert(0,ConfigOnly())
from nexent.core.agents.sandbox.config import SandboxConfig
assert SandboxConfig().level.value == 'local'
print('CONFIG_ONLY_PASS')
'''
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert "CONFIG_ONLY_PASS" in result.stdout


def test_tls_bootstrap_is_packaged_and_used_by_the_real_gateway_command():
    source = Path(tls.__file__).with_name("tls_bootstrap.py").read_text(encoding="utf-8")
    assert tls.TLS_BOOTSTRAP == source
    command = execution._kernel_gateway_command("test-host")
    assert command[:5] == ["python", "-c", source, "test-host", tls.TLS_DIRECTORY]
    compile(command[2], "tls_bootstrap.py", "exec")
    assert "nexent.core" not in source


def test_sandbox_only_uses_explicit_library_compatibility():
    folder = Path(execution.__file__).parent
    for name in ("config.py", "execution.py", "tls.py", "tls_bootstrap.py"):
        for node in ast.walk(ast.parse(folder.joinpath(name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert "smolagents" not in (node.module or ""), name
                assert "cores." not in (node.module or ""), name
                assert "orchestration" not in (node.module or ""), name
    options = config.SandboxConfig.from_dict({"level": "docker", "failure_policy": "error"})
    assert options.level is config.SandboxLevel.DOCKER
    assert options.failure_policy == "error"
    with pytest.raises(ValueError, match="workspace mode"):
        config.SandboxConfig(workspace_mode="unknown")
