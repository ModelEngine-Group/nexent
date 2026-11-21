# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP file summary proxy service (read one summary, retry generation).

Summaries belong to one ingested AIDP file and are addressed under
``/KnowledgeBase/Tenants/aidp/KnowledgeBases/{kds_id}/KnowledgeFiles``. The
read returns AIDP's ``result`` object as-is (an empty object means summaries
are off or not generated yet); retry forwards a non-empty file UUID list and
passes AIDP's per-file success/failure lists through unchanged.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from contracts.errors.exceptions import AppException
from ext_components.aidp.services.aidp_client import (
    _request_aidp_json,
    _resolve_tenant_id,
)


logger = logging.getLogger("aidp_summary_service")

# ==================== File summaries ====================


def _get_file_summary_path(kds_id: str, file_uuid: str, tenant_id: str | None = None) -> str:
    """Build the file-scoped summary read path."""
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/KnowledgeFiles/{file_uuid}/Summary"
    )


def _get_retry_summary_path(kds_id: str, tenant_id: str | None = None) -> str:
    """Build the knowledge-base scoped summary retry path."""
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/KnowledgeFiles/RetrySummary"
    )


def _normalize_summary_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the fields AIDP documents for one file summary.

    The contract spells the payload as ``result.summary_text``,
    ``result.summary_status`` and ``result.summary_model``; status is compared
    case-insensitively by the page, so it is lower-cased here. Unknown extra
    fields are preserved rather than dropped.
    """
    out = dict(raw)
    status = out.get("summary_status")
    if isinstance(status, str):
        out["summary_status"] = status.strip().lower()
    for key in ("summary_text", "summary_model"):
        value = out.get(key)
        if value is not None and not isinstance(value, str):
            out[key] = str(value)
    return out


def get_aidp_file_summary_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuid: str,
) -> Dict[str, Any]:
    """Read one file's summary.

    AIDP wraps the payload in ``result``; when a deployment answers the summary
    fields at the top level instead, those fields are lifted into the same
    ``result`` shape so the page has one contract to consume. An empty
    ``result`` is preserved: whether it means "not previewable" or "not
    generated yet" depends on the knowledge base configuration.
    """
    result = _request_aidp_json(
        server_url,
        api_key,
        "GET",
        _get_file_summary_path(kds_id, file_uuid),
        context="get-file-summary",
        retry=True,
    )
    if not isinstance(result, dict):
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "Unexpected AIDP file summary response format",
        )
    inner = result.get("result")
    if isinstance(inner, dict):
        return {"result": _normalize_summary_result(inner)}
    direct = {
        key: result[key]
        for key in ("summary_text", "summary_status", "summary_model")
        if key in result
    }
    if direct:
        return {"result": _normalize_summary_result(direct)}
    return {"result": _normalize_summary_result(result)}


def retry_aidp_file_summaries_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuids: List[str],
) -> Dict[str, Any]:
    """Ask AIDP to regenerate summaries for the requested files.

    The contract always takes a non-empty ``file_uuids`` array, including for a
    single file. Per-file success/failure lists are passed through unchanged so
    the caller never turns a partial success into a total success.
    """
    result = _request_aidp_json(
        server_url,
        api_key,
        "POST",
        _get_retry_summary_path(kds_id),
        context="retry-file-summaries",
        retry=True,
        json_body={"file_uuids": list(file_uuids)},
    )
    return result if isinstance(result, dict) else {}


# ==================== Knowledge-file history (all-status listing) ====================

# Channel entries are read through alias lists because AIDP deployments spell
# these fields differently. Only the forms actually observed are listed; adding
# a new spelling here is enough to support another deployment.
_CHANNEL_FS_ID_KEYS = (
    "fs_id",
    "fsId",
    "fsid",
    "file_system_id",
    "fileSystemId",
    "file_sys_id",
    "filesystem_id",
)
_CHANNEL_SRC_DIR_KEYS = (
    "src_dir",
    "srcDir",
    "source_dir",
    "sourceDir",
    "source_path",
    "sourcePath",
    "dir_path",
    "dirPath",
    "input_dir",
    "inputDir",
)
_CHANNEL_KB_ID_KEYS = (
    "kds_id",
    "kdsId",
    "knowledge_base_id",
    "knowledgeBaseId",
    "kb_id",
    "kbId",
    "knowledge_base_ids",
    "knowledgeBaseIds",
)

