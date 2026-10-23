"""Architecture gate for process-owned thread creation and blocking offloads."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCAN_ROOTS = (REPO_ROOT / "backend", REPO_ROOT / "sdk" / "nexent")

# Data Process owns an independent lifecycle and is deferred to its own SPEC.
DEFERRED_PREFIXES = (
    "backend/data_process/",
    "backend/data_process_service.py",
    "backend/services/data_process_service.py",
    "backend/services/auto_summary_scheduler.py",
)

# The shared upload recovery helper is also used by Data Process. Its migration
# stays with the deferred Data Process integration so this SPEC does not change
# that process's behavior.
ALLOWED_CALLS = {
    ("backend/services/startup_recovery_service.py", "asyncio.to_thread"),
    ("backend/ext_components/aidp/apps/aidp_mgmt_app.py", "asyncio.to_thread"),
    (
        "sdk/nexent/core/concurrency/bounded_executor.py",
        "ThreadPoolExecutor",
    ),
    ("sdk/nexent/core/concurrency/manager.py", "threading.Thread"),
}

WATCHED_CALLS = {
    "Thread",
    "threading.Thread",
    "ThreadPoolExecutor",
    "concurrent.futures.ThreadPoolExecutor",
    "asyncio.to_thread",
    "run_in_executor",
}


def _call_name(node: ast.Call) -> str:
    parts: list[str] = []
    value = node.func
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def test_all_non_data_process_threads_are_managed():
    violations: list[str] = []
    for root in SCAN_ROOTS:
        for source_path in root.rglob("*.py"):
            relative = source_path.relative_to(REPO_ROOT).as_posix()
            if any(
                part.startswith(".") or part == "__pycache__"
                for part in source_path.relative_to(root).parts
            ):
                continue
            if relative.startswith(DEFERRED_PREFIXES):
                continue
            tree = ast.parse(
                source_path.read_text(encoding="utf-8-sig"), filename=relative
            )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call_name = _call_name(node)
                if call_name not in WATCHED_CALLS:
                    continue
                if (relative, call_name) in ALLOWED_CALLS:
                    continue
                violations.append(f"{relative}:{node.lineno} {call_name}")

    assert not violations, "Unmanaged thread creation or offload:\n" + "\n".join(
        violations
    )
