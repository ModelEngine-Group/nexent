# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Business ownership and import boundaries of shared backend contracts."""
import management.services.model.catalog as _relocated_management_services_model_catalog

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "backend/contracts"


def test_a2a_settings_keep_distinct_public_validation_rules():
    from contracts.a2a import GatewayA2AServerSettings, ManagementA2AServerSettings

    with pytest.raises(ValidationError):
        GatewayA2AServerSettings(is_enabled="true")
    assert GatewayA2AServerSettings(is_enabled=True).is_enabled is True
    assert ManagementA2AServerSettings(is_enabled="true").is_enabled is True


def test_constant_modules_import_without_loading_deployment_or_database_clients():
    program = """
import importlib
import sys
importlib.import_module('contracts.constants.constants')
assert 'contracts.constants.environment' not in sys.modules
assert 'management.db.client' not in sys.modules
assert 'nexent.core.models.capacity_resolver' not in sys.modules
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "backend"), str(ROOT / "sdk"))
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_typed_catalog_keeps_one_shared_sdk_profile_mapping():
    from contracts.constants import constants as model
    from nexent.core.models.capacity_resolver import CapabilityProfile

    catalog = _relocated_management_services_model_catalog.CATALOG
    assert catalog is _relocated_management_services_model_catalog.CATALOG
    assert catalog
    assert all(isinstance(profile, CapabilityProfile) for profile in catalog.values())


def test_contracts_use_business_files_and_two_shared_subdirectories():
    assert {
        p.name for p in CONTRACTS.iterdir() if p.is_dir() and p.name != "__pycache__"
    } == {
        "constants",
        "errors",
    }
    assert {p.stem for p in CONTRACTS.glob("*.py") if p.name != "__init__.py"} == {
        "a2a",
        "agent",
        "authentication",
        "automation",
        "configuration",
        "conversation",
        "evaluation",
        "file",
        "identity",
        "knowledge",
        "memory",
        "model",
        "skill",
        "tag",
        "tool",
        "voice",
    }


def test_constants_have_no_environment_or_implementation_dependencies():
    for path in (CONTRACTS / "constants").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith(
                    ("consts", "management", "infrastructure", "gateway")
                ), path
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"getenv", "load_dotenv"}:
                    assert path.name == "environment.py", path


def test_two_constant_files_use_one_assignment_per_physical_line():
    directory = CONTRACTS / "constants"
    assert {path.name for path in directory.glob("*.py")} == {
        "__init__.py", "constants.py", "environment.py"
    }
    for filename in ("constants.py", "environment.py"):
        path = directory / filename
        source = path.read_text(encoding="utf-8")
        statements = ast.parse(source).body
        assignment_lines = []
        for node in statements:
            assert isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)), (filename, node.lineno)
            assert node.lineno == node.end_lineno, (filename, node.lineno)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                assignment_lines.append(node.lineno)
        assert len(assignment_lines) == len(set(assignment_lines))
        lines = source.splitlines()
        for position, line in enumerate(lines):
            if line.strip():
                continue
            following = next((item for item in lines[position + 1:] if item.strip()), None)
            assert following is None or following.startswith("#"), (filename, position + 1)


def test_error_definitions_have_one_canonical_directory():
    assert {p.name for p in (CONTRACTS / "errors").glob("*.py")} == {
        "__init__.py",
        "codes.py",
        "messages.py",
        "exceptions.py",
    }
    assert not any(
        (CONTRACTS / name).exists()
        for name in (
            "error_code.py",
            "error_message.py",
            "exceptions.py",
        )
    )
