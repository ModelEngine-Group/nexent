# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Configuration works in repository tools and backend service entry points."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("directory,module", [(ROOT, "backend.contracts.constants.environment"), (ROOT / "backend", "contracts.constants.environment")])
def test_configuration_import_without_inherited_python_paths(directory, module):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["RUNTIME_AGENT_THREAD_MAX_WORKERS"] = "13"
    probe = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **kw: None; "
        f"from {module} import RUNTIME_AGENT_THREAD_MAX_WORKERS; "
        "print(RUNTIME_AGENT_THREAD_MAX_WORKERS)"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=directory, env=environment,
        capture_output=True, text=True, check=False, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "13"


@pytest.mark.parametrize("variable,filename", [
    ("MODEL_CATALOG_JSON_PATH", "model_catalog.json"),
    ("MODELS_DEV_CATALOG_JSON_PATH", "models_dev_catalog.json"),
    ("MODEL_REASONING_WIRE_PROFILES_PATH", "model_reasoning_wire_profiles.json"),
])
def test_environment_catalog_defaults_need_no_legacy_const_directory(tmp_path, variable, filename):
    backend = tmp_path / "backend"
    constants = backend / "contracts/constants"
    constants.mkdir(parents=True)
    for package in (backend / "contracts", constants):
        (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(ROOT / "backend/contracts/configuration.py", backend / "contracts/configuration.py")
    shutil.copy2(ROOT / "backend/contracts/constants/environment.py", constants / "environment.py")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(backend)
    environment.pop(variable, None)
    program = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **kw: None; "
        f"from contracts.constants.environment import {variable}; print({variable})"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == backend / "configs" / filename
    assert not (backend / "consts").exists()
