"""Annotation schema management + annotation data API."""

import logging
from collections import Counter
from http import HTTPStatus
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from consts.error_code import ErrorCode
from consts.exceptions import AppException, UnauthorizedError
from database.evaluation_annotation_db import (
    batch_upsert_annotations,
    count_annotations_for_schema,
    create_annotation_schema,
    delete_annotation_schema,
    delete_annotations_by_evaluation_schema,
    get_annotation_values,
    list_annotation_schemas,
    update_annotation_schema,
)
from utils.auth_utils import get_current_user_id


logger = logging.getLogger("evaluation_annotation_app")

def _ok(data=None):
    """Standard success response."""
    return JSONResponse(status_code=HTTPStatus.OK, content={"message": "Success", "data": data})

router = APIRouter(prefix="/evaluation-annotations")


class CreateSchemaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    annotation_type: str = Field(default="classification")
    options: Optional[List[Dict[str, Any]]] = None


class BatchUpsertRequest(BaseModel):
    annotations: List[Dict[str, Any]] = Field(default=[])


# ══════════════════════════════════════════════════════════════════════
# Schema endpoints
# ══════════════════════════════════════════════════════════════════════

@router.get("/schemas")
async def list_schemas_api(authorization: Optional[str] = Header(None)):
    try:
        _, tenant_id = get_current_user_id(authorization)
        data = list_annotation_schemas(tenant_id=tenant_id)
        return _ok(data)
    except AppException:
        raise
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except Exception as exc:
        logger.exception("List schemas error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to list schemas")


@router.post("/schemas")
async def create_schema_api(
    payload: CreateSchemaRequest,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        data = create_annotation_schema(
            tenant_id=tenant_id, user_id=user_id,
            name=payload.name, description=payload.description,
            annotation_type=payload.annotation_type, options=payload.options,
        )
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Create schema error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to create schema")


def _check_schema_not_in_use(schema_id: int, tenant_id: str) -> None:
    from database.agent_evaluation_db import count_active_runs_using_schema
    n = count_active_runs_using_schema(schema_id, tenant_id)
    if n > 0:
        raise AppException(ErrorCode.AGENT_EVALUATION_ANNOTATION_SCHEMA_IN_USE)


@router.put("/schemas/{schema_id}")
async def update_schema_api(
    schema_id: int,
    authorization: Optional[str] = Header(None),
    name: Optional[str] = Body(None),
    description: Optional[str] = Body(None),
    options: Optional[List[Dict[str, Any]]] = Body(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        _check_schema_not_in_use(schema_id, tenant_id)
        kwargs = {k: v for k, v in {"name": name, "description": description, "options": options}.items() if v is not None}
        data = update_annotation_schema(schema_id=schema_id, tenant_id=tenant_id, **kwargs)
        if not data:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Schema not found")
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Update schema error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to update schema")


@router.delete("/schemas/{schema_id}")
async def delete_schema_api(
    schema_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        _check_schema_not_in_use(schema_id, tenant_id)
        # Block deletion if annotations reference this schema
        ann_count = count_annotations_for_schema(schema_id, tenant_id)
        if ann_count > 0:
            raise AppException(ErrorCode.AGENT_EVALUATION_ANNOTATION_SCHEMA_IN_USE)
        ok = delete_annotation_schema(schema_id=schema_id, tenant_id=tenant_id)
        if not ok:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Schema not found")
        return _ok()
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Delete schema error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete schema")


# ══════════════════════════════════════════════════════════════════════
# Annotation data endpoints
# ══════════════════════════════════════════════════════════════════════

@router.get("/{agent_evaluation_id}/annotations")
async def get_annotations_api(
    agent_evaluation_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        from database.evaluation_annotation_db import list_annotations_by_evaluation_id
        data = list_annotations_by_evaluation_id(tenant_id=tenant_id, agent_evaluation_id=agent_evaluation_id)
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Get annotations error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to get annotations")


@router.put("/{agent_evaluation_id}/annotations")
async def batch_upsert_annotations_api(
    agent_evaluation_id: int,
    payload: BatchUpsertRequest,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        batch_upsert_annotations(
            tenant_id=tenant_id, user_id=user_id, annotations=payload.annotations,
        )
        return _ok()
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Upsert annotations error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to save annotations")


@router.delete("/{agent_evaluation_id}/annotations")
async def delete_annotations_api(
    agent_evaluation_id: int,
    schema_id: int = Query(..., description="Schema id whose annotations should be deleted"),
    authorization: Optional[str] = Header(None),
):
    """Delete all annotations for a single schema within one evaluation run.

    Called when a user disables a label that already has annotation data, so
    that the data is cleaned up instead of silently lingering (and reappearing
    if the label is re-enabled later).
    """
    try:
        _, tenant_id = get_current_user_id(authorization)
        deleted = delete_annotations_by_evaluation_schema(
            tenant_id=tenant_id,
            agent_evaluation_id=agent_evaluation_id,
            schema_id=schema_id,
        )
        return _ok({"deleted": deleted})
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Delete annotations error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to delete annotations")


@router.get("/{agent_evaluation_id}/annotation-stats")
async def get_annotation_stats_api(
    agent_evaluation_id: int,
    schema_id: int = Query(...),
    authorization: Optional[str] = Header(None),
):
    try:
        _, tenant_id = get_current_user_id(authorization)
        values = get_annotation_values(
            tenant_id=tenant_id, agent_evaluation_id=agent_evaluation_id,
            schema_id=schema_id,
        )
        counter = Counter(values)
        total = sum(counter.values())
        data = [
            {"value": k, "count": v, "ratio": round(v / total, 2) if total else 0}
            for k, v in counter.most_common()
        ]
        return _ok(data)
    except UnauthorizedError:
        raise AppException(ErrorCode.COMMON_UNAUTHORIZED, "Authentication required")
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Get annotation stats error: %r", exc)
        raise AppException(ErrorCode.SYSTEM_INTERNAL_ERROR, "Failed to get annotation stats")
