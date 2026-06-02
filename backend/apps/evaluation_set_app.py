import io
import json
import logging
from http import HTTPStatus
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from services.evaluation_set_service import (
    create_evaluation_set_from_cases,
    create_evaluation_set_from_jsonl,
    get_evaluation_set_impl,
    list_evaluation_set_cases_impl,
    list_evaluation_sets_impl,
)
from utils.auth_utils import get_current_user_id
from utils.evaluation_set_excel_utils import build_evaluation_set_excel_template_bytes, parse_evaluation_cases_from_excel

logger = logging.getLogger("evaluation_set_app")

router = APIRouter(prefix="/evaluation-sets")


@router.get("")
async def list_evaluation_sets_api(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        data = list_evaluation_sets_impl(tenant_id=tenant_id, limit=limit, offset=offset)
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})
    except Exception as exc:
        logger.exception("List evaluation sets error: %r", exc)
        raise HTTPException(status_code=500, detail="List evaluation sets error")


@router.post("")
async def create_evaluation_set_api(
    name: str = Body(...),
    description: Optional[str] = Body(None),
    source_filename: Optional[str] = Body(None),
    jsonl_text: str = Body(..., description="Raw JSONL content"),
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        meta = create_evaluation_set_from_jsonl(
            tenant_id=tenant_id,
            name=name,
            description=description,
            source_filename=source_filename,
            jsonl_text=jsonl_text,
            created_by=user_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": meta})
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        logger.exception("Create evaluation set error: %r", exc)
        raise HTTPException(status_code=500, detail="Create evaluation set error")


@router.post("/upload")
async def upload_evaluation_set_api(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        if not files:
            raise ValueError("At least one file is required")

        all_cases: List[Dict[str, Any]] = []
        source_filenames: List[str] = []

        for file in files:
            raw = await file.read()
            filename = file.filename or ""
            source_filenames.append(filename)
            lower = filename.lower()

            if lower.endswith(".xlsx") or lower.endswith(".xls"):
                cases = parse_evaluation_cases_from_excel(filename=filename, raw=raw)
                all_cases.extend(cases)
            else:
                # Backward compatible: still accept JSONL upload
                try:
                    jsonl_text = raw.decode("utf-8")
                except Exception:
                    jsonl_text = raw.decode("utf-8", errors="ignore")

                # Parse JSONL into cases
                for line in jsonl_text.strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    all_cases.append({
                        "query": obj.get("query", ""),
                        "answer": obj.get("answer", ""),
                        "context": obj.get("context"),
                        "case_id": obj.get("case_id"),
                    })

        if not all_cases:
            raise ValueError("No valid cases found in uploaded files")

        meta = create_evaluation_set_from_cases(
            tenant_id=tenant_id,
            name=name,
            description=description,
            source_filename=", ".join(source_filenames),
            cases=all_cases,
            created_by=user_id,
        )

        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": meta})
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        logger.exception("Upload evaluation set error: %r", exc)
        raise HTTPException(status_code=500, detail="Upload evaluation set error")


@router.get("/template")
async def download_evaluation_set_template_api():
    """Download Excel template for evaluation set upload."""
    data = build_evaluation_set_excel_template_bytes()
    headers = {
        "Content-Disposition": 'attachment; filename="evaluation_set_template.xlsx"'
    }
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/{evaluation_set_id}")
async def get_evaluation_set_api(
    evaluation_set_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = get_evaluation_set_impl(evaluation_set_id=evaluation_set_id, tenant_id=tenant_id)
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})
    except Exception as exc:
        logger.exception("Get evaluation set error: %r", exc)
        raise HTTPException(status_code=500, detail="Get evaluation set error")


@router.get("/{evaluation_set_id}/cases")
async def list_evaluation_set_cases_api(
    evaluation_set_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_evaluation_set_cases_impl(
            evaluation_set_id=evaluation_set_id,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})
    except Exception as exc:
        logger.exception("List evaluation set cases error: %r", exc)
        raise HTTPException(status_code=500, detail="List evaluation set cases error")
