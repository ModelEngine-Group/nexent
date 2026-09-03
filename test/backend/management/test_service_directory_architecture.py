"""Architecture checks for the first Management service migration slice."""

import ast
import re
from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
MANAGEMENT_SERVICES = BACKEND_ROOT / "management" / "services"

MIGRATED_MODULES = {
    "agent/management.py",
    "agent/naming.py",
    "agent/read.py",
    "agent/run_context.py",
    "agent/run.py",
    "agent/service.py",
    "knowledge_base/common.py",
    "knowledge_base/deletion.py",
    "knowledge_base/listing.py",
    "knowledge_base/management.py",
    "knowledge_base/permission.py",
    "knowledge_base/service.py",
    "model/resolver.py",
    "skill/service.py",
    "skill/support.py",
}

LEGACY_MODULE_NAMES = {
    "agent_management_service",
    "agent_naming_service",
    "agent_read_service",
    "agent_run_context",
    "agent_runtime_service",
    "agent_service",
    "knowledge_base_common",
    "knowledge_base_deletion_service",
    "knowledge_base_list_service",
    "knowledge_base_management_service",
    "knowledge_base_permission_service",
    "model_resolver_service",
    "skill_service",
    "skill_support",
    "vectordatabase_service",
}


def _project_python_files(root):
    """Scan project sources without descending into local Python environments."""
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories
            if name not in {".venv", "venv", "__pycache__"}
            and not (Path(directory) / name / "pyvenv.cfg").is_file()
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(directory) / filename


def test_migrated_management_services_have_single_canonical_location():
    actual_modules = {
        path.relative_to(MANAGEMENT_SERVICES).as_posix()
        for path in MANAGEMENT_SERVICES.rglob("*.py")
        if path.name != "__init__.py"
    }

    assert actual_modules == MIGRATED_MODULES
    assert all(
        not (BACKEND_ROOT / "services" / f"{module_name}.py").exists()
        for module_name in LEGACY_MODULE_NAMES
    )


def test_migrated_management_services_stay_below_two_thousand_lines():
    oversized_modules = {
        path.relative_to(MANAGEMENT_SERVICES).as_posix(): len(path.read_text(encoding="utf-8").splitlines())
        for path in MANAGEMENT_SERVICES.rglob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 2000
    }

    assert oversized_modules == {}


def test_source_and_tests_do_not_reference_legacy_module_paths():
    module_pattern = "|".join(
        re.escape(module_name)
        for module_name in sorted(LEGACY_MODULE_NAMES, key=len, reverse=True)
    )
    legacy_reference = re.compile(
        rf"(?<!management\.)(?:backend\.)?services\.({module_pattern})(?![A-Za-z0-9_])"
    )
    unexpected_references = []

    for source_root in (BACKEND_ROOT, PROJECT_ROOT / "sdk", PROJECT_ROOT / "test"):
        for source_file in _project_python_files(source_root):
            if source_file == Path(__file__):
                continue
            if legacy_reference.search(source_file.read_text(encoding="utf-8")):
                unexpected_references.append(source_file.relative_to(PROJECT_ROOT).as_posix())

    assert unexpected_references == []


def test_management_services_do_not_import_runtime_implementation_modules():
    invalid_imports = []

    for source_file in MANAGEMENT_SERVICES.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported_modules = [node.module or ""]
            else:
                continue

            for imported_module in imported_modules:
                if imported_module.startswith("runtime.services"):
                    invalid_imports.append(f"{source_file.name}: {imported_module}")

    assert invalid_imports == []
