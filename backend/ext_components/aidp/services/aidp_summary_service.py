# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP file summary proxy service (read one file summary).

Summaries belong to one ingested AIDP file and are addressed under
``/KnowledgeBase/Tenants/aidp/KnowledgeBases/{kds_id}/KnowledgeFiles``. The
2026-11-25 AIDP contract takes the file UUID in a POST body and returns the
summary object directly; the proxy wraps it back into the frontend's
``{result: ...}`` envelope. An empty object means summaries are off or not
generated yet. AIDP has no summary-retry endpoint, so the proxy exposes no
regeneration call.
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


def _get_file_summary_path(kds_id: str, tenant_id: str | None = None) -> str:
    """Build the file-summary read path; the file UUID travels in the body."""
    return (
        f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}"
        f"/KnowledgeBases/{kds_id}/KnowledgeFiles/Summary"
    )


def get_aidp_file_summary_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuid: str,
) -> Dict[str, Any]:
    """Read one file's summary.

    AIDP's 2026-11-25 contract accepts ``file_uuid`` in a POST body and
    returns the summary object directly (``summary_status`` / ``summary_text``
    / ``error_reason``). The BFF keeps the frontend's ``{result: ...}``
    envelope; an empty object means summaries are off or not generated yet.
    """
    result = _request_aidp_json(
        server_url,
        api_key,
        "POST",
        _get_file_summary_path(kds_id),
        context="get-file-summary",
        json_body={"file_uuid": file_uuid},
        retry=True,
    )
    return {"result": result}


# ==================== Knowledge-file history (all-status listing) ====================


