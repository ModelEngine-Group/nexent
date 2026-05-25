# -*- coding: utf-8 -*-
"""Robust path resolution for benchmark scripts.

Finds the project root by searching upward for a .git entry (directory
or file), then derives SDK_DIR and BACKEND_PATH from it. This makes
path setup resilient to file relocation within the project tree and to
git worktrees (which store a .git file rather than directory at root).
"""
import os
import sys


def _find_project_root(start: str = None) -> str:
    """Walk upward from *start* until a .git entry is found.

    Accepts ``.git`` as either a directory (normal checkout) or a file
    (git worktree, where ``.git`` is a pointer file to the gitdir).
    """
    current = os.path.abspath(start or os.path.dirname(__file__))
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(
                f"Could not find project root (.git) starting from {start or __file__}"
            )
        current = parent


def setup_paths() -> dict:
    """Resolve and inject project paths into sys.path.

    Returns a dict with resolved paths:
        project_root, sdk_dir, backend_dir

    Adds the following to sys.path (idempotent):
        - sdk_dir        (for ``from nexent import ...``)
        - project_root   (for ``from backend.utils import ...``)
        - backend_dir    (for ``from utils.prompt_template_utils import ...``)
    """
    project_root = _find_project_root()
    sdk_dir = os.path.join(project_root, "sdk")
    backend_dir = os.path.join(project_root, "backend")

    for p in (sdk_dir, project_root, backend_dir):
        if p not in sys.path:
            sys.path.insert(0, p)

    return {
        "project_root": project_root,
        "sdk_dir": sdk_dir,
        "backend_dir": backend_dir,
    }


# Convenience: resolve on import so callers can do `from paths import PROJECT_ROOT`
_resolved = setup_paths()
PROJECT_ROOT = _resolved["project_root"]
SDK_DIR = _resolved["sdk_dir"]
BACKEND_DIR = _resolved["backend_dir"]