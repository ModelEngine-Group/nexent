"""
Model Monitoring API endpoints.

Provides model performance metrics aggregated from model_monitoring_record_t.
Uses an independent database connection pool to avoid impacting business operations.
"""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from consts.const import IS_SPEED_MODE
from consts.model import ConversationResponse
from database.client import get_monitoring_db_session
from database.group_db import query_group_ids_by_user
from database.user_tenant_db import get_user_tenant_by_user_id
from utils.auth_utils import get_current_user_id

logger = logging.getLogger("monitoring_app")

router = APIRouter(prefix="/monitoring")


def _compute_time_range_filter(time_range: str) -> str:
    """Convert time_range parameter to SQL timestamp condition."""
    hours = {"24h": 24, "7d": 168, "30d": 720}.get(time_range, 24)
    return f"m.create_time >= NOW() - INTERVAL '{hours} hours'"


def _query_model_metrics_from_db(
    time_range: str, tenant_id: Optional[str] = None
) -> list[dict]:
    time_filter = _compute_time_range_filter(time_range)

    tenant_filter = ""
    params = {}
    if tenant_id:
        tenant_filter = "AND m.tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id

    query_sql = f"""
        SELECT
            m.model_id,
            m.model_name,
            MAX(COALESCE(m.model_type, 'llm')) AS model_type,
            MAX(COALESCE(m.display_name, split_part(m.model_name, '/', -1), 'Unknown')) AS display_name,
            COUNT(*) AS request_count,
            ROUND(
                COALESCE(
                    SUM(CASE WHEN m.is_error = TRUE THEN 1 ELSE 0 END)::numeric
                    * 100.0 / NULLIF(COUNT(*), 0), 0
                ), 2
            ) AS error_rate,
            ROUND(AVG(COALESCE(m.request_duration_ms, 0))::numeric, 1) AS avg_duration,
            ROUND(AVG(COALESCE(m.ttft_ms, 0))::numeric, 1) AS avg_ttft,
            ROUND(AVG(COALESCE(m.generation_rate, 0))::numeric, 1) AS token_generation_rate,
            COALESCE(SUM(COALESCE(m.total_tokens, 0)), 0) AS total_tokens
        FROM nexent.model_monitoring_record_t m
        WHERE {time_filter}
        {tenant_filter}
        AND m.delete_flag = 'N'
        GROUP BY m.model_id, m.model_name
        ORDER BY request_count DESC
    """

    try:
        with get_monitoring_db_session() as session:
            result = session.execute(text(query_sql), params)
            rows = result.fetchall()
            return [
                {
                    "model_id": row.model_id,
                    "model_name": row.model_name,
                    "model_type": row.model_type,
                    "display_name": row.display_name,
                    "request_count": row.request_count,
                    "error_rate": float(row.error_rate) if row.error_rate else 0,
                    "avg_duration": float(row.avg_duration) if row.avg_duration else 0,
                    "avg_ttft": float(row.avg_ttft) if row.avg_ttft else 0,
                    "token_generation_rate": float(row.token_generation_rate)
                    if row.token_generation_rate
                    else 0,
                    "total_tokens": int(row.total_tokens) if row.total_tokens else 0,
                }
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to query model metrics from DB: {e}")
        return []


def _filter_by_rbac(
    all_metrics: list[dict], user_id: str, tenant_id: str
) -> list[dict]:
    if IS_SPEED_MODE:
        return all_metrics

    user_tenant = get_user_tenant_by_user_id(user_id)
    user_role = str((user_tenant or {}).get("user_role", "")).upper()
    if user_role in ("ADMIN", "SU"):
        return all_metrics

    # Models have no group_id currently, return all visible metrics for non-admin
    return all_metrics


@router.get("/models", response_model=ConversationResponse)
async def list_models_endpoint(
    time_range: str = Query("24h", description="Time range: 24h, 7d, 30d"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    authorization: Optional[str] = Header(None),
):
    """List all models with aggregated monitoring metrics from database."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)

        all_metrics = _query_model_metrics_from_db(time_range, tenant_id)
        accessible_metrics = _filter_by_rbac(all_metrics, user_id, tenant_id)

        start = (page - 1) * page_size
        end = start + page_size
        paginated = accessible_metrics[start:end]

        return ConversationResponse(code=0, message="success", data=paginated)
    except Exception as e:
        logger.error(f"Failed to list monitoring models: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))
