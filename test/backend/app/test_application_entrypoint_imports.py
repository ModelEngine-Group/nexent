import os
from pathlib import Path
import subprocess
import sys

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"


@pytest.mark.parametrize("module_name", ["apps.runtime_app", "apps.config_app"])
def test_application_entrypoint_imports_without_module_stubs(
    module_name: str, tmp_path: Path
) -> None:
    """Import each production application entrypoint in an isolated interpreter."""
    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    command = (
        "import importlib; "
        f"module = importlib.import_module({module_name!r}); "
        "assert module.app is not None"
    )

    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )

    assert result.returncode == 0, result.stderr
