"""Select project sources for architecture checks without installed dependencies."""

import os
from collections.abc import Iterator
from pathlib import Path


def iter_project_python_files(root: Path) -> Iterator[Path]:
    """Prune virtual environments before traversing their third-party sources."""
    excluded = {".venv", "venv", "__pycache__", "node_modules", ".git"}
    if root.name in excluded or (root / "pyvenv.cfg").is_file():
        return
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories
            if name not in excluded
            and not (Path(directory) / name / "pyvenv.cfg").is_file()
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(directory) / filename
