# -*- coding: utf-8 -*-
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Robust path resolution for benchmark scripts.

Finds the project root from Git metadata or a complete SDK/backend source
layout, then derives SDK_DIR and BACKEND_PATH from it. Exported source
trees do not need Git metadata just to import benchmark entrypoints.
"""
import os
import sys


def _find_project_root(start: str = None) -> str:
    """Walk upward from *start* until a checkout or complete source root is found.

    Accepts ``.git`` as either a directory (normal checkout) or a file
    (git worktree, where ``.git`` is a pointer file to the gitdir). Without
    metadata, all three source markers must be present.
    """
    current = os.path.abspath(start or os.path.dirname(__file__))
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        if all(os.path.isfile(os.path.join(current, marker)) for marker in (
            "sdk/nexent/__init__.py", "backend/pyproject.toml", "VERSION",
        )):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(
                f"Could not find project root (.git or complete source layout) starting from {start or __file__}"
            )
        current = parent


def setup_paths() -> dict:
    """Resolve and inject project paths into sys.path.

    Returns a dict with resolved paths:
        project_root, sdk_dir, backend_dir

    Adds the following to sys.path (idempotent):
        - sdk_dir        (for ``from nexent import ...``)
        - project_root   (for ``from backend.utils import ...``)
        - backend_dir    (for ``from management.services.agent.prompt import ...``)
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
