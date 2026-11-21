# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authorize attachments and prepare history, prompts and Skill snapshots."""

import logging
from typing import Any, Dict, List, Optional

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

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)


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
