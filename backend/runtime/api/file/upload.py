# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from http import HTTPStatus
from typing import List, Optional
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from management.services.file.service import resolve_minio_upload_folder, upload_to_minio
from management.services.monitor.audit import AUDIT_DETAIL_LIST_LIMIT, record_security_event
from gateway.authentication.identity import get_current_user_id

logger = logging.getLogger("file_management_app")


file_management_runtime_router = APIRouter(prefix="/file")


@file_management_runtime_router.post("/storage")
async def storage_upload_files(
    http_request: Request,
    files: List[UploadFile] = File(..., description="List of files to upload"),
    folder: str = Form("attachments", description="Storage folder path (optional)"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Upload one or more files to MinIO storage.

    - **files**: List of files to upload
    - **folder**: Storage folder path (optional, defaults to 'attachments')
                   Knowledge-base source files must use `/file/upload` with an
                   `index_name` so their storage-ledger ownership is recorded.
                   Other folders (like 'attachments') are isolated by user_id.

    Returns upload results including file information and access URLs
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        if folder == "knowledge_base":
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=("Knowledge-base source uploads must specify an index_name through /api/file/upload"),
            )

        actual_folder = resolve_minio_upload_folder(folder, user_id, tenant_id)
        results = await upload_to_minio(files=files, folder=actual_folder)

        # Chat-attachment upload path; identifiers only, content never logged.
        record_security_event(
            "file_storage_upload",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={
                "folder": folder,
                "files_count": len(files),
                "filenames": [f.filename for f in files][:AUDIT_DETAIL_LIST_LIMIT],
            },
        )

        return {
            "message": f"Processed {len(results)} files",
            "success_count": sum(1 for r in results if r.get("success", False)),
            "failed_count": sum(1 for r in results if not r.get("success", False)),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Storage upload error: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Storage upload error.")

    # Return upload results for all files
    return {
        "message": f"Processed {len(results)} files",
        "success_count": sum(1 for r in results if r.get("success", False)),
        "failed_count": sum(1 for r in results if not r.get("success", False)),
        "results": results,
    }
