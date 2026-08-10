import io
import json
import logging
from http import HTTPStatus

from fastapi import APIRouter, Body, File, Header, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from consts.error_code import ErrorCode
from consts.exceptions import AppException, UnauthorizedError
from services.evaluator_service import (
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
from utils.auth_utils import get_current_user_id


logger = logging.getLogger("evaluator_app")

router = APIRouter(prefix="/evaluators")


def _ok(data=None):
    """Standard success response."""
    return JSONResponse(
        status_code=HTTPStatus.OK, content={"message": "Success", "data": data}
    )


class GenerateEvaluatorRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    model_id: int = Field(..., description="LLM model ID to use for generation")
    agent_id: int | None = Field(
        default=None, description="Optional agent ID for context-aware generation"
    )


class ExportEvaluatorsRequest(BaseModel):
    evaluator_ids: list[int] = Field(..., min_length=1, max_length=100)


class EvaluatorFields(BaseModel):
    """Shared fields for create/update evaluator requests."""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)
    prompt: str | None = Field(default=None, max_length=5_000)
    prompt_en: str | None = Field(default=None, max_length=5_000)
    code: str | None = Field(default=None, max_length=20_000)
    score_range_min: float | None = None
    score_range_max: float | None = None
    pass_threshold: float | None = None
    input_fields: list[dict] | None = None
    model_id: int | None = None

    @model_validator(mode="after")
    def validate_score_range(self):
        import math

        lo, hi, th = self.score_range_min, self.score_range_max, self.pass_threshold
        if lo is not None and hi is not None:
            if any(math.isnan(v) or math.isinf(v) for v in (lo, hi) if v is not None):
                raise ValueError("Score range parameters must not be NaN or Infinity")
            if lo >= hi:
                raise ValueError(
                    f"score_range_min ({lo}) must be less than score_range_max ({hi})"
                )
            if th is not None and (th <= lo or th >= hi):
                raise ValueError(
                    f"pass_threshold ({th}) must be between score_range_min ({lo}) and score_range_max ({hi})"
                )
        if hi is not None and hi > 100.0:
            raise ValueError(f"score_range_max must not exceed 100, got {hi}")
        return self


class CreateEvaluatorRequest(EvaluatorFields):
    name: str = Field(..., min_length=1, max_length=50)  # type: ignore[assignment]
    evaluator_type: str = Field(default="llm")


class UpdateEvaluatorRequest(EvaluatorFields):
    """All fields optional — only supplied fields are updated."""


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
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
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
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluator not found"
            )
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
            prompt_en=payload.prompt_en,
            code=payload.code,
            score_range_min=payload.score_range_min,
            score_range_max=payload.score_range_max,
            pass_threshold=payload.pass_threshold,
            input_fields=payload.input_fields,
            model_id=payload.model_id,
        )
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Create evaluator error: %r", exc)
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to create evaluator"
        )


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
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluator not found"
            )
        data = update_evaluator_impl(
            evaluator_id=evaluator_id, tenant_id=tenant_id, **kwargs
        )
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
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to update evaluator"
        )


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
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete evaluator"
        )


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
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to publish evaluator"
        )


@router.get("/{evaluator_id}/versions")
async def list_evaluator_versions_api(
    evaluator_id: int,
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_evaluator_versions_impl(
            evaluator_id=evaluator_id, tenant_id=tenant_id
        )
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("List evaluator versions error: %r", exc)
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to list evaluator versions"
        )


@router.post("/{evaluator_id}/versions/{version_id}/restore")
async def restore_evaluator_version_api(
    evaluator_id: int,
    version_id: int,
    authorization: str | None = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = restore_evaluator_version_impl(
            version_id=version_id, tenant_id=tenant_id
        )
        if not data:
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluator version not found"
            )
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Restore evaluator version error: %r", exc)
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to restore evaluator version"
        )


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
            raise AppException(
                ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Evaluator version not found"
            )
        return _ok()
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Delete evaluator version error: %r", exc)
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete evaluator version"
        )


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
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to export evaluators"
        )


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
            raise AppException(
                ErrorCode.COMMON_VALIDATION_ERROR, f"Invalid JSON file: {exc}"
            ) from exc
        result = import_evaluators_impl(
            tenant_id=tenant_id,
            user_id=user_id,
            export_data=data,
        )
        return _ok(result)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Import evaluators error: %r", exc)
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to import evaluators"
        )


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
        )
        return _ok(data)
    except AppException:
        raise

    except Exception as exc:
        logger.exception("Generate evaluator error: %r", exc)
        raise AppException(
            ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to generate evaluator"
        )
