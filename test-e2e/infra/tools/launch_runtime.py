"""Select a test-home Python before importing the dependency-heavy suite runner."""

from __future__ import annotations

import os
from pathlib import Path


def test_python(home: Path) -> Path:
    suffix = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return home / "runtime/test-venv" / suffix


def selected_python(argv: list[str], current: Path) -> Path | None:
    if not argv or argv[0] not in {"plan", "doctor", "run", "daily", "resume", "worker"}:
        return None
    home_value = None
    for index, value in enumerate(argv):
        if value == "--test-home" and index + 1 < len(argv):
            home_value = argv[index + 1]
            break
        if value.startswith("--test-home="):
            home_value = value.split("=", 1)[1]
            break
    if not home_value:
        return None
    home = Path(home_value).resolve()
    runtime = test_python(home)
    if not runtime.is_file():
        raise FileNotFoundError(f"Dedicated test Python is missing: {runtime}. Run bootstrap --execute first")
    # Comparing resolved files follows venv symlinks to the base interpreter.
    # Compare the invoked paths instead so a system Python cannot masquerade as the venv.
    same_path = os.path.normcase(os.path.abspath(runtime)) == os.path.normcase(os.path.abspath(current))
    return None if same_path else runtime
