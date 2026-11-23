# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Per-knowledge-base AIDP file summary routes.

The summary surface (read one file's summary) is split out of the legacy
management router so the feature has one focused route module, mirroring the
folder and sensitive-word routes. The public Nexent paths are unchanged.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from ext_components.aidp.apps.aidp_mgmt_common import (
    AIDP_FILE_UUID_PATTERN,
    _auth,
    _credentials,
)
from ext_components.aidp.services import aidp_permission_service as perms
from ext_components.aidp.services.aidp_summary_service import (
    get_aidp_file_summary_impl,
)


aidp_summary_router = APIRouter()

@aidp_summary_router.get(
    "/knowledge-bases/{kds_id}/documents/{file_uuid}/summary"
)
async def get_file_summary(
    request: Request,
    kds_id: Annotated[str, Path(description="Knowledge base ID")],
    file_uuid: Annotated[str, Path(pattern=AIDP_FILE_UUID_PATTERN, description="AIDP file UUID")],
) -> JSONResponse:
    """Read one file's summary; the KB and file are addressed by path."""
    user_id, tenant_id = await _auth(request)
    perms.require_permission(kds_id, user_id, tenant_id, required="READ")

    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-file-summary",
        get_aidp_file_summary_impl,
        server_url,
        api_key,
        kds_id,
        str(file_uuid),
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)
