import io
import json
import logging
from http import HTTPStatus
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from consts.error_code import ErrorCode
from consts.evaluation_limits import (
    CASE_ANSWER_MAX_LEN,
    CASE_QUERY_MAX_LEN,
    MAX_EVALUATION_SETS,
    SET_NAME_MAX_LEN,
    SET_NAME_MIN_LEN,
)
from consts.exceptions import AppException, UnauthorizedError
from services.evaluation_set_service import (
    _generate_cases_async,
    _update_generation_status,
    add_evaluation_set_case_impl,
    batch_delete_evaluation_set_cases_impl,
    count_active_runs_using_set,
    count_evaluation_sets_impl,
    create_evaluation_set_from_cases,
    create_evaluation_set_from_jsonl,
    delete_evaluation_set_case_impl,
    delete_evaluation_set_impl,
    export_evaluation_set_impl,
    get_evaluation_set_impl,
    list_evaluation_set_cases_impl,
    list_evaluation_sets_impl,
    update_evaluation_set_case_impl,
)
from utils.auth_utils import get_current_user_id
from utils.evaluation_set_excel_utils import (
    build_evaluation_set_excel_template_bytes,
    parse_evaluation_cases_from_excel,
)
from utils.thread_utils import pool


logger = logging.getLogger(__name__)

def _ok(data=None):
    """Standard success response."""
    return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})

router = APIRouter(prefix="/evaluation-sets")

# ── Pydantic models ─────────────────────────────────────────────────


class UpdateCaseRequest(BaseModel):
    inputs: Optional[dict] = None
    label: Optional[dict] = None
    session_id: Optional[str] = None
    turn_order: Optional[int] = None


class BatchDeleteRequest(BaseModel):
    case_ids: list


MAX_DOCX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


class GenerateCasesRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=1000)
    count: int = Field(default=20, ge=1, le=200)
    model_id: int = Field(...)
    knowledge_base_names: Optional[List[str]] = None
    agent_id: Optional[int] = None
    agent_version_no: Optional[int] = None
    set_name: Optional[str] = None
    set_description: Optional[str] = None
    target_set_id: Optional[int] = None


def _parse_docx_to_text(raw: bytes) -> str:
    """Extract text content from a .docx file."""
    from io import BytesIO

    from docx import Document
    doc = Document(BytesIO(raw))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("")
async def list_evaluation_sets_api(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_evaluation_sets_impl(tenant_id=tenant_id, limit=limit, offset=offset)
        return _ok(data)
    except AppException:
        raise
    except Exception as exc:
        logger.exception("List evaluation sets error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to list evaluation sets")


@router.post("")
async def create_evaluation_set_api(
    name: str = Body(...),
    description: Optional[str] = Body(None),
    source_filename: Optional[str] = Body(None),
    jsonl_text: str = Body("", description="Raw JSONL content, empty to create empty set"),
    authorization: Optional[str] = Header(None),
):
    try:
        if not name or len(name.strip()) < SET_NAME_MIN_LEN or len(name.strip()) > SET_NAME_MAX_LEN:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR,
                f"Evaluation set name must be {SET_NAME_MIN_LEN}-{SET_NAME_MAX_LEN} characters"
            )
        user_id, tenant_id = get_current_user_id(authorization)
        existing = count_evaluation_sets_impl(tenant_id=tenant_id)
        if existing >= MAX_EVALUATION_SETS:
            raise AppException(ErrorCode.COMMON_RATE_LIMIT_EXCEEDED,f"Evaluation set limit reached: {MAX_EVALUATION_SETS}")
        meta = create_evaluation_set_from_jsonl(
            tenant_id=tenant_id, name=name.strip(), description=description,
            source_filename=source_filename, jsonl_text=jsonl_text, created_by=user_id,
        )
        return _ok(meta)
    except AppException:
        raise
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except Exception as exc:
        logger.exception("Create evaluation set error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to create evaluation set")


@router.post("/upload")
async def upload_evaluation_set_api(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    files: List[UploadFile] = File(...),
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        if not files:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR,"At least one file is required")

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
                try:
                    jsonl_text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    jsonl_text = raw.decode("utf-8", errors="replace")
                    logger.warning("Non-UTF-8 content in uploaded file %s, replaced invalid bytes", filename)
                for line in jsonl_text.strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping invalid JSONL line in upload: %.80s", line)
                        continue
                    all_cases.append({
                        "inputs": {"query": obj.get("query", ""), "context": obj.get("context")}
                        if obj.get("context")
                        else {"query": obj.get("query", "")},
                        "label": {"answer": obj.get("answer", "")},
                        "case_id": obj.get("case_id"),
                    })

        if not all_cases:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR,"No valid cases found in uploaded files")

        meta = create_evaluation_set_from_cases(
            tenant_id=tenant_id, name=name, description=description,
            source_filename=", ".join(source_filenames), cases=all_cases, created_by=user_id,
        )
        return _ok(meta)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Upload evaluation set error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to upload evaluation set")


@router.get("/template")
async def download_evaluation_set_template_api():
    data = build_evaluation_set_excel_template_bytes()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="evaluation_set_template.xlsx"'},
    )


@router.get("/{evaluation_set_id}")
async def get_evaluation_set_api(
    evaluation_set_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = get_evaluation_set_impl(evaluation_set_id=evaluation_set_id, tenant_id=tenant_id)
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Get evaluation set error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to get evaluation set")


@router.get("/{evaluation_set_id}/export")
async def export_evaluation_set_api(
    evaluation_set_id: int,
    authorization: Optional[str] = Header(None),
):
    """Export an evaluation set as an Excel (.xlsx) file."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        filename, excel_bytes = export_evaluation_set_impl(
            evaluation_set_id=evaluation_set_id, tenant_id=tenant_id,
        )
        encoded_filename = quote(filename)
        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            },
        )
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Export evaluation set error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to export evaluation set")


@router.get("/{evaluation_set_id}/cases")
async def list_evaluation_set_cases_api(
    evaluation_set_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    query: Optional[str] = Query(None, description="Fuzzy search on inputs.query"),
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        result = list_evaluation_set_cases_impl(
            evaluation_set_id=evaluation_set_id, tenant_id=tenant_id,
            limit=limit, offset=offset, query=query,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content={
            "message": "Success", "data": result["data"], "total": result["total"],
        })
    except AppException:
        raise

    except Exception as exc:
        logger.exception("List evaluation set cases error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to list evaluation set cases")


@router.post("/{evaluation_set_id}/cases")
async def add_evaluation_set_case_api(
    evaluation_set_id: int,
    payload: UpdateCaseRequest,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        query_text = str((payload.inputs or {}).get("query", ""))
        answer_text = str((payload.label or {}).get("answer", ""))
        if len(query_text) > CASE_QUERY_MAX_LEN:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR,f"Query exceeds max length: {CASE_QUERY_MAX_LEN}")
        if len(answer_text) > CASE_ANSWER_MAX_LEN:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR,f"Answer exceeds max length: {CASE_ANSWER_MAX_LEN}")
        data = add_evaluation_set_case_impl(evaluation_set_id, tenant_id, payload.inputs, payload.label, user_id,
                                             session_id=payload.session_id, turn_order=payload.turn_order)
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Add case error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to add case")


@router.put("/{evaluation_set_id}/cases/{case_id}")
async def update_evaluation_set_case_api(
    evaluation_set_id: int,
    case_id: int,
    payload: UpdateCaseRequest,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        updated = update_evaluation_set_case_impl(evaluation_set_id, case_id, tenant_id, payload.inputs, payload.label,
                                                     session_id=payload.session_id, turn_order=payload.turn_order)
        if not updated:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Case not found")
        return _ok()
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Update case error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to update case")


@router.delete("/{evaluation_set_id}/cases/{case_id}")
async def delete_evaluation_set_case_api(
    evaluation_set_id: int,
    case_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        ok = delete_evaluation_set_case_impl(case_id, tenant_id)
        if not ok:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Case not found")
        return _ok()
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Delete case error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete case")


@router.post("/{evaluation_set_id}/cases/batch-delete")
async def batch_delete_cases_api(
    evaluation_set_id: int,
    payload: BatchDeleteRequest,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        deleted = batch_delete_evaluation_set_cases_impl(evaluation_set_id, payload.case_ids, tenant_id)
        return _ok({"deleted": deleted})
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Batch delete cases error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to batch delete cases")


@router.delete("/{evaluation_set_id}")
async def delete_evaluation_set_api(
    evaluation_set_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        delete_evaluation_set_impl(evaluation_set_id, tenant_id, user_id)
        return _ok()
    except AppException:
        raise



    except Exception as exc:
        logger.exception("Delete evaluation set error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete evaluation set")


@router.post("/generate-cases-async")
async def generate_cases_async_api(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        # Support both JSON body (no file) and multipart form (with .docx file)
        content_type = request.headers.get("content-type", "")
        if "multipart" in content_type:
            form = await request.form()
            payload = GenerateCasesRequest(**json.loads(str(form["payload"])))
            file = form.get("file")
        else:
            body = await request.json()
            payload = GenerateCasesRequest(**body)
            file = None

        file_content = None
        file_name = None
        if file and isinstance(file, UploadFile):
            if not file.filename or not file.filename.lower().endswith(".docx"):
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Only .docx files are supported")
            raw = await file.read()
            if len(raw) > MAX_DOCX_FILE_SIZE:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, f"File size exceeds {MAX_DOCX_FILE_SIZE // (1024*1024)}MB limit")
            try:
                file_content = _parse_docx_to_text(raw)
            except Exception as e:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, f"Failed to parse DOCX file: {e}") from e
            file_name = file.filename

        if payload.target_set_id:
            set_id = payload.target_set_id
            n = count_active_runs_using_set(set_id, tenant_id)
            if n > 0:
                raise AppException(ErrorCode.AGENT_EVALUATION_SET_IN_USE,
                    f"Evaluation set is referenced by {n} active evaluation run(s) and cannot be modified")
            _update_generation_status(set_id, tenant_id, "GENERATING", 0)
        else:
            if not payload.set_name:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR,"set_name is required when target_set_id is not provided")
            meta = create_evaluation_set_from_jsonl(
                tenant_id=tenant_id, name=payload.set_name, description=payload.set_description,
                source_filename=None, jsonl_text="", created_by=user_id,
            )
            set_id = meta["evaluation_set_id"]
            _update_generation_status(set_id, tenant_id, "GENERATING", 0)

        is_new = not bool(payload.target_set_id)
        pool.submit(
            _generate_cases_async,
            set_id, tenant_id, user_id,
            payload.description, payload.count, payload.model_id,
            file_content, file_name, payload.agent_id,
            is_new, payload.knowledge_base_names,
        )
        return _ok({"evaluation_set_id": set_id})
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Generate cases async error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to start generation")


