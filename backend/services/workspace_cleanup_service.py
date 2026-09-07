import logging
import re
import shutil
from pathlib import Path

from consts.const import AGENT_WORKSPACE_ROOT


logger = logging.getLogger("workspace_cleanup_service")

_RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def cleanup_orphaned_agent_workspaces(workspace_root: str = AGENT_WORKSPACE_ROOT) -> int:
    """Remove run-scoped workspaces left behind by a previous Runtime process."""
    root = Path(workspace_root)
    if not root.exists() or not root.is_dir() or root.is_symlink():
        return 0

    removed_count = 0
    for user_dir in root.iterdir():
        if not user_dir.is_dir() or user_dir.is_symlink():
            continue
        for run_dir in user_dir.iterdir():
            if (
                not run_dir.is_dir()
                or run_dir.is_symlink()
                or not _RUN_ID_PATTERN.fullmatch(run_dir.name)
            ):
                continue
            try:
                shutil.rmtree(run_dir)
                removed_count += 1
            except Exception as exc:
                logger.error("Failed to clean orphaned run workspace %s: %s", run_dir, exc)
        try:
            user_dir.rmdir()
        except OSError:
            pass

    if removed_count:
        logger.info(
            "Cleaned %d orphaned agent workspace(s) under %s",
            removed_count,
            root,
        )
    return removed_count
