# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP file summary proxy service (read one file summary).

Summaries belong to one ingested AIDP file and are addressed under
``/KnowledgeBase/Tenants/aidp/KnowledgeBases/{kds_id}/KnowledgeFiles``. The
read returns AIDP's ``result`` object as-is; an empty object means summaries
are off or not generated yet. AIDP has no summary-retry endpoint, so the proxy
exposes no regeneration call.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

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


def get_aidp_file_summary_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuid: str,
) -> Dict[str, Any]:
    """Read one file's summary.

    The fixed response is ``{result: {summary_text, summary_status,
    summary_model}}``; an empty ``result`` means summaries are off or not
    generated yet and is returned unchanged.
    """
    result = _request_aidp_json(
        server_url,
        api_key,
        "GET",
        _get_file_summary_path(kds_id, file_uuid),
        context="get-file-summary",
        retry=True,
    )
    return {"result": result["result"]}


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

