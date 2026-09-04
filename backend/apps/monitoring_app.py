"""
Model Monitoring API endpoints.

Provides model performance metrics aggregated from model_monitoring_record_t.
Uses an independent database connection pool to avoid impacting business operations.
"""

import logging
from http import HTTPStatus
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import text

from consts.const import (
    ENABLE_TELEMETRY,
    MONITORING_DASHBOARD_URL,
    MONITORING_PROVIDER,
)
from consts.model import ConversationResponse
from consts.exceptions import TokenExpiredError
from database.client import get_monitoring_db_session
from utils.auth_utils import get_current_user_id

logger = logging.getLogger("monitoring_app")

router = APIRouter(prefix="/monitoring")


def _normalize_monitoring_provider(value: str | None) -> str:
    return str(value or "otlp").strip().lower()


def get_monitoring_status() -> dict[str, Any]:
    """Return telemetry state and the monitoring UI entrypoint for frontend use."""
    telemetry_enabled = ENABLE_TELEMETRY
    provider = _normalize_monitoring_provider(MONITORING_PROVIDER)
    dashboard_url = MONITORING_DASHBOARD_URL.strip() or None

    return {
        "telemetry_enabled": telemetry_enabled,
        "provider": provider,
        "dashboard_url": dashboard_url,
        "dashboard_port": None,
        "dashboard_path": None,
    }


def _compute_time_range_filter(time_range: str) -> str:
    """Convert time_range parameter to SQL timestamp condition."""
    hours = {"24h": 24, "7d": 168, "30d": 720}.get(time_range, 24)
    return f"m.create_time >= NOW() - INTERVAL '{hours} hours'"


def _query_model_metrics_from_db(
    time_range: str, tenant_id: str | None = None
) -> list[dict[str, Any]]:
    time_filter = _compute_time_range_filter(time_range)

    tenant_filter = ""
    params: dict[str, str] = {}
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
            ROUND(AVG(CASE WHEN m.is_streaming = TRUE THEN m.ttft_ms ELSE NULL END)::numeric, 1) AS avg_ttft,
            ROUND(AVG(CASE WHEN m.is_streaming = TRUE THEN m.generation_rate ELSE NULL END)::numeric, 1) AS token_generation_rate,
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


def _query_context_budget_metrics_from_db(
    time_range: str, tenant_id: str | None = None
) -> list[dict[str, Any]]:
    """Aggregate content-free P3 evidence by Provider/model/profile version."""
    time_filter = _compute_time_range_filter(time_range)
    tenant_filter = "AND m.tenant_id = :tenant_id" if tenant_id else ""
    params = {"tenant_id": tenant_id} if tenant_id else {}
    query_sql = f"""
        SELECT
            COALESCE(m.context_budget_evidence->>'provider_protocol', 'unknown') AS provider_protocol,
            m.model_name,
            COALESCE(m.capability_profile_version, 'unknown') AS capability_profile_version,
            COUNT(*) FILTER (WHERE m.context_budget_evidence IS NOT NULL) AS request_count,
            COUNT(*) FILTER (WHERE COALESCE((m.context_budget_evidence->>'provider_overflow')::boolean, FALSE)) AS overflow_count,
            COUNT(*) FILTER (WHERE COALESCE((m.context_budget_evidence->>'compression_attempted')::boolean, FALSE)) AS compacted_count,
            ROUND(AVG(CASE WHEN COALESCE((m.context_budget_evidence->>'compression_attempted')::boolean, FALSE)
                AND (m.context_budget_evidence->>'context_raw_tokens')::numeric > 0
                THEN 1 - (m.context_budget_evidence->>'context_final_tokens')::numeric
                    / (m.context_budget_evidence->>'context_raw_tokens')::numeric END), 4) AS avg_compression_ratio,
            COUNT(*) FILTER (WHERE (m.context_budget_evidence->>'provider_prompt_usage_tokens')::numeric > 0) AS estimate_sample_count,
            ROUND(AVG(CASE WHEN (m.context_budget_evidence->>'provider_prompt_usage_tokens')::numeric > 0
                THEN ABS((m.context_budget_evidence->>'raw_estimate_tokens')::numeric
                    - (m.context_budget_evidence->>'provider_prompt_usage_tokens')::numeric)
                    / (m.context_budget_evidence->>'provider_prompt_usage_tokens')::numeric END), 4) AS mean_absolute_estimate_error,
            COUNT(*) FILTER (WHERE COALESCE((m.context_budget_evidence->>'recovery_attempted')::boolean, FALSE)) AS recovery_attempt_count,
            COUNT(*) FILTER (WHERE COALESCE((m.context_budget_evidence->>'recovery_succeeded')::boolean, FALSE)) AS recovery_success_count
        FROM nexent.model_monitoring_record_t m
        WHERE {time_filter} {tenant_filter} AND m.delete_flag = 'N'
          AND m.context_budget_evidence IS NOT NULL
        GROUP BY provider_protocol, m.model_name, capability_profile_version
        ORDER BY request_count DESC
    """
    try:
        with get_monitoring_db_session() as session:
            rows = session.execute(text(query_sql), params).fetchall()
            output = []
            for row in rows:
                requests = int(row.request_count or 0)
                attempts = int(row.recovery_attempt_count or 0)
                compacted = int(row.compacted_count or 0)
                output.append({
                    "provider_protocol": row.provider_protocol,
                    "model_name": row.model_name,
                    "capability_profile_version": row.capability_profile_version,
                    "request_count": requests,
                    "overflow_count": int(row.overflow_count or 0),
                    "overflow_rate": (int(row.overflow_count or 0) / requests) if requests else None,
                    "compacted_count": compacted,
                    "compaction_incidence": (compacted / requests) if requests else None,
                    "avg_compression_ratio": float(row.avg_compression_ratio) if row.avg_compression_ratio is not None else None,
                    "estimate_sample_count": int(row.estimate_sample_count or 0),
                    "mean_absolute_estimate_error": float(row.mean_absolute_estimate_error) if row.mean_absolute_estimate_error is not None else None,
                    "recovery_attempt_count": attempts,
                    "recovery_success_count": int(row.recovery_success_count or 0),
                    "recovery_success_rate": (int(row.recovery_success_count or 0) / attempts) if attempts else None,
                })
            return output
    except Exception as exc:
        logger.error("Failed to query context budget metrics: %s", exc)
        return []


@router.get("/models", response_model=ConversationResponse)
async def list_models_endpoint(
    time_range: Annotated[str, Query(
        description="Time range: 24h, 7d, 30d")] = "24h",
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(
        ge=1, le=100, description="Items per page")] = 20,
    authorization: Annotated[str | None, Header()] = None,
):
    """List all models with aggregated monitoring metrics from database."""
    try:
        _, tenant_id = get_current_user_id(authorization)

        all_metrics = _query_model_metrics_from_db(time_range, tenant_id)

        start = (page - 1) * page_size
        end = start + page_size
        paginated = all_metrics[start:end]

        return ConversationResponse(code=0, message="success", data=paginated)
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list monitoring models: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/status", response_model=ConversationResponse)
async def get_monitoring_status_endpoint():
    """Return whether monitoring UI should be shown in the frontend."""
    return ConversationResponse(
        code=0,
        message="success",
        data=get_monitoring_status(),
    )


@router.get("/context-budget", response_model=ConversationResponse)
async def get_context_budget_metrics_endpoint(
    time_range: Annotated[str, Query(description="Time range: 24h, 7d, 30d")] = "24h",
    authorization: Annotated[str | None, Header()] = None,
):
    _, tenant_id = get_current_user_id(authorization)
    return ConversationResponse(
        code=0,
        message="success",
        data=_query_context_budget_metrics_from_db(time_range, tenant_id),
    )
