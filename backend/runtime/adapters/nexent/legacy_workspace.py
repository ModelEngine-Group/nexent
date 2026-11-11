# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Stage files owned by the compatibility execution workspace."""

import copy
from pathlib import Path
from typing import Any

from contracts.errors.exceptions import WorkbenchError


def materialize_legacy_skill_snapshot(
    snapshot: list[dict[str, Any]],
    workspace_path: str,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Materialize frozen Skill files below the run workspace without mutating input."""
    effective = copy.deepcopy(snapshot)
    snapshot_root = (Path(workspace_path).resolve() / ".skill_snapshot").resolve()
    tenant_root = (snapshot_root / tenant_id).resolve()
    if not tenant_root.is_relative_to(snapshot_root):
        raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
    for skill in effective:
        skill_name = str(skill.get("name") or "")
        if (
            not skill_name
            or Path(skill_name).name != skill_name
            or skill_name in {".", ".."}
        ):
            raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
        skill_root = (tenant_root / skill_name).resolve()
        if not skill_root.is_relative_to(tenant_root):
            raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
        files = skill.pop("files", [])
        for relative_path, content in files:
            destination = (skill_root / str(relative_path)).resolve()
            if not destination.is_relative_to(skill_root):
                raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bytes(content))
        if not (skill_root / "SKILL.md").is_file():
            raise WorkbenchError("RUNTIME_SKILL_DEPENDENCY_UNAVAILABLE")
        skill["_snapshot_root"] = str(snapshot_root)
    return effective
