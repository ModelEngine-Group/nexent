# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorize attachments and prepare history, prompts and Skill snapshots."""

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from contracts.constants.environment import AGENT_WORKSPACE_ROOT
from contracts.errors.exceptions import WorkbenchError
from management.services.agent.prompt import load_agent_prompt_bundle
from management.services.file.service import validate_urls_access
from nexent.core.agents.prompt import AgentPromptComposer
from infrastructure.agent_attachments import (
    _build_internal_s3_url,
    _collect_run_minio_files as _collect_run_minio_files,
    _convert_history_with_minio_files as _convert_history_with_minio_files,
    _format_minio_files_for_content as _format_minio_files_for_content,
    render_query_with_attachments,
)
from infrastructure.workspace_paths import create_run_workspace

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)


def _build_run_workspace(user_id: str, run_id: str) -> str:
    """Bridge the deployment root to the runtime workspace path owner."""
    return create_run_workspace(user_id, run_id, workspace_root=AGENT_WORKSPACE_ROOT)


def _materialize_runtime_skill_snapshot(
    snapshot: List[Dict[str, Any]],
    workspace_path: str,
    tenant_id: str,
) -> List[Dict[str, Any]]:
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


def _validate_run_minio_files(
    minio_files: Optional[List[Dict[str, Any]]],
    user_id: str,
    tenant_id: str,
) -> None:
    """Authorize every current-request MinIO object with the canonical backend policy."""
    urls = [
        url
        for item in (minio_files or [])
        if isinstance(item, dict) and (url := _build_internal_s3_url(item))
    ]
    validate_urls_access(urls, user_id, tenant_id)


async def join_minio_file_description_to_query(
    minio_files, query, history=None, max_files: int = 50, max_chars: int = 10000, language: str = "en",
):
    return render_query_with_attachments(minio_files, query, history, max_files, max_chars, language)


async def prepare_prompt_templates(
    is_manager: bool,
    language: str = "zh",
    agent_id: int = None,
):
    """
    Prepare prompt templates, support multiple languages

    Args:
        is_manager: Whether it is a manager mode
        language: Language code ('zh' or 'en')
        agent_id: Agent ID for fetching skill instances

    Returns:
        dict: Prompt template configuration
    """
    bundle = load_agent_prompt_bundle(is_manager=is_manager, language=language)
    return AgentPromptComposer(bundle).compatibility_templates()
