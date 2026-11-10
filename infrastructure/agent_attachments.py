# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Attachment formatting and read scope shared by Agent preparation and Runtime."""

import logging
from typing import Any, Dict, List, Optional

from contracts.constants.environment import MINIO_DEFAULT_BUCKET
from infrastructure.object_storage.read_access import require_s3_read_access
from nexent.core.agents.agent_model import AgentHistory
from nexent.core.agents.prompt.user_context import render_user_context

logger = logging.getLogger(__name__)


def _build_internal_s3_url(file: dict) -> str:
    """Build a valid S3 URL for internal tools from uploaded file metadata."""
    if not isinstance(file, dict):
        return ""

    object_name = str(file.get("object_name") or "").strip().lstrip("/")
    if object_name:
        bucket = MINIO_DEFAULT_BUCKET or "nexent"
        return f"s3://{bucket}/{object_name}"

    url = str(file.get("url") or "").strip()
    if not url or url.startswith("blob:") or url.startswith("s3:/blob:"):
        return ""

    if url.startswith("s3://"):
        return url

    if url.startswith("s3:/"):
        return "s3://" + url.replace("s3:/", "", 1).lstrip("/")

    return "s3:/" + url


def _collect_run_minio_files(
    minio_files: Optional[List[Dict[str, Any]]],
    history: Optional[List[Any]],
    max_files: int = 50,
) -> List[Dict[str, Any]]:
    """Collect current and historical attachments for one authorized Agent run."""
    seen_urls: set[str] = set()
    collected: List[Dict[str, Any]] = []
    sources = [minio_files]
    for message in history or []:
        attachments = (
            message.get("minio_files")
            if isinstance(message, dict)
            else getattr(message, "minio_files", None)
        )
        sources.append(attachments)

    for attachments in sources:
        if not isinstance(attachments, list):
            continue
        for file in attachments:
            if not isinstance(file, dict) or not file.get("name"):
                continue
            s3_url = _build_internal_s3_url(file)
            if not s3_url or s3_url in seen_urls:
                continue
            seen_urls.add(s3_url)
            collected.append(file)
            if len(collected) == max_files:
                return collected
    return collected


def render_query_with_attachments(
    minio_files,
    query,
    history=None,
    max_files: int = 50,
    max_chars: int = 10000,
    language: str = "en",
):
    """
    Join MinIO file descriptions to the user query.

    This function formats uploaded file information into a structured description
    that includes both S3 URL (for internal tools) and presigned_url (for external MCP tools).
    It processes files from both the current message and historical messages.

    De-duplication is performed using the file URL as the unique key. A maximum
    file count and total character limit are enforced to prevent prompt bloat.

    Args:
        minio_files: List of file info dicts from current message upload
        query: Original user query
        history: Optional list of historical message dicts, each may contain minio_files
        max_files: Maximum number of files to include (default 50)
        max_chars: Maximum total characters for file descriptions (default 10000)

    Returns:
        Modified query with file descriptions appended
    """
    final_query = query
    all_files = _collect_run_minio_files(minio_files, history, max_files=max_files)

    if all_files:
        file_descriptions: list[str] = []
        # Calculate fixed overhead that is added only once
        prefix = render_user_context(language, "file_intro")
        suffix = render_user_context(language, "file_query", {"query": query})
        fixed_overhead = len(prefix) + len(suffix)

        for i, file in enumerate(all_files):
            s3_url = _build_internal_s3_url(file)
            presigned_url = file.get("presigned_url", "")

            # Build description with both URLs
            desc = render_user_context(
                language,
                "file_with_presigned_url"
                if presigned_url
                else "file_without_presigned_url",
                {
                    "name": file["name"],
                    "s3_url": s3_url,
                    "presigned_url": presigned_url,
                },
            )

            # Calculate total length if we include this description
            # Each description after the first adds 2 chars for \n\n separator
            separator_chars = 2 if i > 0 else 0
            total_len = (
                sum(len(d) for d in file_descriptions)
                + len(desc)
                + separator_chars
                + fixed_overhead
            )

            # Check if adding this description would exceed the character limit
            if total_len > max_chars:
                logger.info(
                    f"File descriptions truncated at {len(file_descriptions)} files "
                    f"to stay within {max_chars} character limit"
                )
                break

            file_descriptions.append(desc)

        if file_descriptions:
            final_query = prefix + "\n\n".join(file_descriptions) + suffix

    return final_query


def _format_minio_files_for_content(
    minio_files: Optional[List[dict]], max_files: int = 20, language: str = "en"
) -> str:
    """Format minio_files into a string for embedding in history content.

    Args:
        minio_files: List of file info dicts
        max_files: Maximum number of files to include per message

    Returns:
        Formatted string describing the files, or empty string if no files
    """
    if not minio_files or not isinstance(minio_files, list):
        return ""

    file_lines = []
    for i, file in enumerate(minio_files):
        if i >= max_files:
            file_lines.append(
                render_user_context(
                    language,
                    "history_file_overflow",
                    {"count": len(minio_files) - max_files},
                )
            )
            break
        if (
            isinstance(file, dict)
            and file.get("name")
            and (file.get("url") or file.get("object_name"))
        ):
            s3_url = _build_internal_s3_url(file)
            if not s3_url:
                continue
            presigned_url = file.get("presigned_url", "")
            file_lines.append(
                render_user_context(
                    language,
                    "history_file_with_presigned_url"
                    if presigned_url
                    else "history_file_without_presigned_url",
                    {
                        "name": file["name"],
                        "s3_url": s3_url,
                        "presigned_url": presigned_url,
                    },
                )
            )

    if not file_lines:
        return ""

    return render_user_context(language, "history_file_intro") + "\n".join(file_lines)


def _convert_history_with_minio_files(
    history: List, language: str = "en"
) -> Optional[List[AgentHistory]]:
    """Convert HistoryItem list to AgentHistory list, embedding minio_files into content.

    Args:
        history: List of HistoryItem from API

    Returns:
        List of AgentHistory with file info embedded in content, or None if history is None
    """
    if history is None:
        return None

    result = []
    for item in history:
        content = item.content
        if item.minio_files:
            file_info = _format_minio_files_for_content(
                item.minio_files, language=language
            )
            if file_info:
                content = content + file_info if content else file_info
        result.append(AgentHistory(role=item.role, content=content))
    return result


def validate_attachment_references(urls: list[str], user_id: str, tenant_id: str) -> None:
    """Restrict prepared attachments to the configured attachment bucket and caller's read scope."""
    from nexent.multi_modal.utils import parse_s3_url

    require_s3_read_access(urls, user_id, tenant_id)
    if any(parse_s3_url(url)[0] != (MINIO_DEFAULT_BUCKET or "nexent") for url in urls):
        raise PermissionError("Attachment bucket is outside the run's read scope")
