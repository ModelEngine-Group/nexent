# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from contracts.evaluation import CreateEvaluatorRequest, EvaluatorFields, ExportEvaluatorsRequest, GenerateEvaluatorRequest, UpdateEvaluatorRequest
from contracts.constants.evaluation import _UNAUTHORIZED_MESSAGE
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, UnauthorizedError
import io
import json
import logging
from http import HTTPStatus

from fastapi import APIRouter, Body, File, Header, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, UnauthorizedError
from management.services.evaluation.evaluators import (
    create_evaluator_impl,
    delete_evaluator_impl,
    delete_evaluator_version_impl,
    export_evaluators_impl,
    generate_evaluator_by_llm_impl,
    get_evaluator_impl,
    import_evaluators_impl,
    list_evaluator_versions_impl,
    list_evaluators_impl,
    publish_evaluator_impl,
    restore_evaluator_version_impl,
    update_evaluator_impl,
)
from gateway.authentication.normal import get_current_user_id


logger = logging.getLogger("evaluator_app")


router = APIRouter(prefix="/evaluators")


def _ok(data=None):
    """Standard success response."""
    return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})


@router.get("")
async def list_evaluators_api(
    source: str | None = Query(None, description="Filter: builtin / custom"),
    evaluator_type: str | None = Query(None, description="Filter: llm / code"),
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_evaluators_impl(
            tenant_id=tenant_id,
            source=source,
            evaluator_type=evaluator_type,
            status=None,
        )
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _UNAUTHORIZED_MESSAGE)
    except AppException:
        raise
    except Exception as exc:
        logger.exception("List evaluators error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to list evaluators")


@router.get("/{evaluator_id}")
async def get_evaluator_api(
    evaluator_id: int,
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = get_evaluator_impl(evaluator_id=evaluator_id, tenant_id=tenant_id)
        if not data:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluator not found")
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Get evaluator error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to get evaluator")


@router.post("")
async def create_evaluator_api(
    payload: CreateEvaluatorRequest,
    authorization: str | None = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        data = create_evaluator_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            name=payload.name,
            description=payload.description,
            evaluator_type=payload.evaluator_type,
            prompt=payload.prompt,
            code=payload.code,
            score_range_min=payload.score_range_min,
            score_range_max=payload.score_range_max,
            pass_threshold=payload.pass_threshold,
            input_fields=payload.input_fields,
            model_id=payload.model_id,
        )
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _UNAUTHORIZED_MESSAGE)
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Create evaluator error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to create evaluator")


@router.put("/{evaluator_id}")
async def update_evaluator_api(
    evaluator_id: int,
    payload: UpdateEvaluatorRequest,
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        kwargs = {k: v for k, v in payload.model_dump().items() if v is not None}
        exists = get_evaluator_impl(evaluator_id=evaluator_id, tenant_id=tenant_id)
        if not exists:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluator not found")
        data = update_evaluator_impl(evaluator_id=evaluator_id, tenant_id=tenant_id, **kwargs)
        if not data:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                "Only DRAFT custom evaluators can be edited",
            )
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Update evaluator error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to update evaluator")


@router.delete("/{evaluator_id}")
async def delete_evaluator_api(
    evaluator_id: int,
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        ok = delete_evaluator_impl(evaluator_id=evaluator_id, tenant_id=tenant_id)
        if not ok:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                "Only DRAFT custom evaluators can be deleted",
            )
        return _ok()
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Delete evaluator error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete evaluator")


@router.post("/{evaluator_id}/publish")
async def publish_evaluator_api(
    evaluator_id: int,
    authorization: str | None = Header(None),
    version_name: str | None = Body(None),
    release_note: str | None = Body(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = publish_evaluator_impl(
            evaluator_id=evaluator_id,
            tenant_id=tenant_id,
            version_name=version_name,
            release_note=release_note,
        )
        if not data:
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR,
                "Only DRAFT evaluators can be published",
            )
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Publish evaluator error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to publish evaluator")


@router.get("/{evaluator_id}/versions")
async def list_evaluator_versions_api(
    evaluator_id: int,
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_evaluator_versions_impl(evaluator_id=evaluator_id, tenant_id=tenant_id)
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _UNAUTHORIZED_MESSAGE)
    except AppException:
        raise
    except Exception as exc:
        logger.exception("List evaluator versions error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to list evaluator versions")


@router.post("/{evaluator_id}/versions/{version_id}/restore")
async def restore_evaluator_version_api(
    evaluator_id: int,
    version_id: int,
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = restore_evaluator_version_impl(version_id=version_id, tenant_id=tenant_id)
        if not data:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluator version not found")
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Restore evaluator version error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to restore evaluator version")


@router.delete("/{evaluator_id}/versions/{version_id}")
async def delete_evaluator_version_api(
    evaluator_id: int,
    version_id: int,
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        ok = delete_evaluator_version_impl(version_id=version_id, tenant_id=tenant_id)
        if not ok:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluator version not found")
        return _ok()
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Delete evaluator version error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete evaluator version")


@router.post("/export")
async def export_evaluators_api(
    payload: ExportEvaluatorsRequest,
    authorization: str | None = Header(None),
):
    """Export one or more custom evaluators as a JSON file."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = export_evaluators_impl(
            tenant_id=tenant_id,
            evaluator_ids=payload.evaluator_ids,
        )
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(json_bytes),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="evaluators_export.json"',
            },
        )
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Export evaluators error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to export evaluators")


@router.post("/import")
async def import_evaluators_api(
    file: UploadFile = File(...),
    authorization: str | None = Header(None),
):
    """Import evaluators from a previously exported JSON file.

    Skips evaluators whose name + type already exist in the tenant.
    Returns ``{imported, skipped, errors}``.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        raw = await file.read()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, f"Invalid JSON file: {exc}") from exc
        result = import_evaluators_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            export_data=data,
        )
        return _ok(result)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, _UNAUTHORIZED_MESSAGE)
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Import evaluators error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to import evaluators")


@router.post("/generate")
async def generate_evaluator_api(
    payload: GenerateEvaluatorRequest,
    authorization: str | None = Header(None),
):
    """Generate an evaluator configuration from a natural language description."""
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = generate_evaluator_by_llm_impl(
            description=payload.description,
            tenant_id=tenant_id,
            model_id=payload.model_id,
            agent_id=payload.agent_id,
            language=payload.language,
        )
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Generate evaluator error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to generate evaluator")
