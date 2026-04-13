"""
Model Monitoring API endpoints.

Provides model performance, cost, quality, and alert data.
Currently returns mock data; will be backed by database in production.
"""

import logging
import random
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from consts.model import ConversationResponse
from utils.auth_utils import get_current_user_id

logger = logging.getLogger("monitoring_app")

router = APIRouter(prefix="/monitoring")

# ---------------------------------------------------------------------------
# Mock data generation utilities
# ---------------------------------------------------------------------------

_MOCK_MODELS = [
    {"id": "model-1", "name": "gpt-4o", "display_name": "GPT-4o"},
    {"id": "model-2", "name": "claude-3.5-sonnet", "display_name": "Claude 3.5 Sonnet"},
    {"id": "model-3", "name": "deepseek-chat", "display_name": "DeepSeek Chat"},
    {"id": "model-4", "name": "qwen-max", "display_name": "Qwen Max"},
    {"id": "model-5", "name": "gemini-pro", "display_name": "Gemini Pro"},
]

_FAILURE_TYPES = [
    "authentication_error",
    "rate_limit_exceeded",
    "service_unavailable",
    "timeout",
    "invalid_request",
    "model_overloaded",
]

_ALERT_TYPES = [
    "failure_rate_high",
    "error_rate_high",
    "slow_request",
    "quality_degradation",
]

_SEVERITIES = ["critical", "warning", "info"]

# Use a fixed seed so mock data is consistent within a session
_rng = random.Random(42)


def _generate_model_summary(model: dict) -> dict:
    """Generate mock summary metrics for a single model."""
    request_count = _rng.randint(500, 50000)
    error_rate = round(_rng.uniform(0.5, 3.0), 2)
    failure_rate = round(_rng.uniform(0.1, 1.0), 2)
    avg_duration = round(_rng.uniform(200, 3000), 1)
    avg_ttft = round(_rng.uniform(50, 500), 1)
    total_tokens = _rng.randint(100000, 5000000)
    total_cost = round(_rng.uniform(0.5, 50.0), 4)
    quality_score = round(_rng.uniform(70, 98), 1)

    return {
        "model_id": model["id"],
        "model_name": model["name"],
        "display_name": model["display_name"],
        "request_count": request_count,
        "error_rate": error_rate,
        "failure_rate": failure_rate,
        "avg_duration": avg_duration,
        "avg_ttft": avg_ttft,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "quality_score": quality_score,
    }


def _generate_performance_detail(model_id: str) -> dict:
    """Generate mock performance detail for a single model."""
    base_duration = _rng.uniform(200, 2000)
    return {
        "total_requests": _rng.randint(500, 50000),
        "error_rate": round(_rng.uniform(0.5, 3.0), 2),
        "failure_rate": round(_rng.uniform(0.1, 1.0), 2),
        "avg_duration": round(base_duration, 1),
        "p50_duration": round(base_duration * 0.8, 1),
        "p95_duration": round(base_duration * 1.5, 1),
        "p99_duration": round(base_duration * 2.2, 1),
        "avg_ttft": round(_rng.uniform(50, 500), 1),
        "input_tokens": _rng.randint(50000, 2000000),
        "output_tokens": _rng.randint(20000, 1000000),
        "total_tokens": _rng.randint(100000, 5000000),
        "total_cost": round(_rng.uniform(1.0, 50.0), 4),
        "today_cost": round(_rng.uniform(0.1, 5.0), 4),
        "quality_avg_score": round(_rng.uniform(70, 98), 1),
        "quality_positive_ratio": round(_rng.uniform(0.7, 0.95), 2),
    }


def _generate_error_breakdown() -> list:
    """Generate mock error breakdown."""
    types = [
        ("rate_limit", True),
        ("timeout", True),
        ("invalid_request", True),
        ("authentication_error", False),
        ("service_unavailable", False),
        ("model_overloaded", False),
    ]
    total = 100.0
    remaining = total
    result = []
    for i, (err_type, recoverable) in enumerate(types):
        if i == len(types) - 1:
            pct = round(remaining, 1)
        else:
            pct = round(_rng.uniform(5, remaining * 0.4), 1)
            remaining -= pct
        result.append({
            "error_type": err_type,
            "count": _rng.randint(10, 500),
            "percentage": pct,
            "is_recoverable": recoverable,
        })
    return result


def _generate_trend_points(interval: str, time_range: str) -> list:
    """Generate mock trend data points."""
    range_hours = {"24h": 24, "7d": 168, "30d": 720}.get(time_range, 24)
    interval_hours = {"1h": 1, "6h": 6, "1d": 24, "7d": 168}.get(interval, 1)
    point_count = max(1, range_hours // interval_hours)

    now = datetime.now(timezone.utc)
    points = []
    for i in range(point_count):
        ts = now - timedelta(hours=range_hours - (i + 1) * interval_hours)
        points.append({
            "timestamp": ts.isoformat(),
            "request_count": _rng.randint(10, 200),
            "error_rate": round(_rng.uniform(0.3, 4.0), 2),
            "failure_rate": round(_rng.uniform(0.05, 1.5), 2),
            "avg_duration": round(_rng.uniform(200, 3000), 1),
            "cost": round(_rng.uniform(0.01, 2.0), 4),
            "tokens": _rng.randint(1000, 50000),
        })
    return points


def _generate_multi_model_trend(interval: str, time_range: str, model_id: Optional[str] = None) -> list:
    """Generate trend data with per-model breakdown. If model_id is None, returns aggregated + per-model."""
    range_hours = {"24h": 24, "7d": 168, "30d": 720}.get(time_range, 24)
    interval_hours = {"1h": 1, "6h": 6, "1d": 24, "7d": 168}.get(interval, 1)
    point_count = max(1, range_hours // interval_hours)
    models_to_include = (
        [_MOCK_MODELS[0]] if model_id
        else [m for m in _MOCK_MODELS if m["id"] in ("model-1", "model-2", "model-3")]
    )

    now = datetime.now(timezone.utc)
    points = []
    for i in range(point_count):
        ts = now - timedelta(hours=range_hours - (i + 1) * interval_hours)
        model_data = {}
        total_requests = 0
        total_error_rate = 0.0
        total_failure_rate = 0.0
        total_duration = 0.0
        total_cost = 0.0
        total_tokens = 0

        for m in models_to_include:
            req = _rng.randint(5, 80)
            err = round(_rng.uniform(0.2, 5.0), 2)
            fail = round(_rng.uniform(0.02, 2.0), 2)
            dur = round(_rng.uniform(200, 3000), 1)
            cost = round(_rng.uniform(0.001, 0.8), 4)
            tok = _rng.randint(500, 20000)

            model_data[m["name"]] = {
                "request_count": req,
                "error_rate": err,
                "failure_rate": fail,
                "avg_duration": dur,
                "cost": cost,
                "tokens": tok,
            }
            total_requests += req
            total_error_rate += err
            total_failure_rate += fail
            total_duration += dur
            total_cost += cost
            total_tokens += tok

        n = len(models_to_include)
        point = {
            "timestamp": ts.isoformat(),
            "request_count": total_requests,
            "error_rate": round(total_error_rate / n, 2),
            "failure_rate": round(total_failure_rate / n, 2),
            "avg_duration": round(total_duration / n, 1),
            "cost": round(total_cost, 4),
            "tokens": total_tokens,
        }
        if not model_id:
            point["models"] = model_data
        points.append(point)
    return points


def _mask_api_key(msg: str) -> str:
    """Mask potential API keys in error messages."""
    import re
    return re.sub(r'(sk-|key-|api[_-]?key[=:\s]*)\S{8,}', r'\1****', msg, flags=re.IGNORECASE)


def _generate_failures(model_id: str, page: int, page_size: int) -> dict:
    """Generate mock failure records."""
    model = next((m for m in _MOCK_MODELS if m["id"] == model_id), _MOCK_MODELS[0])
    total = _rng.randint(5, 50)
    now = datetime.now(timezone.utc)
    items = []
    for i in range(min(page_size, total)):
        ts = now - timedelta(minutes=_rng.randint(1, 1440))
        failure_type = _rng.choice(_FAILURE_TYPES)
        raw_msg = f"Request to {model['name']} failed: {failure_type} (sk-abc123xyz456)"
        items.append({
            "id": f"fail-{model_id}-{page * page_size + i}",
            "timestamp": ts.isoformat(),
            "model_name": model["name"],
            "failure_type": failure_type,
            "error_message": _mask_api_key(raw_msg),
            "request_duration": round(_rng.uniform(500, 10000), 1),
            "status_code": _rng.choice([401, 403, 404, 429, 500, 502, 503]),
        })
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


def _generate_alerts(status: Optional[str], severity: Optional[str],
                     alert_type: Optional[str], page: int, page_size: int) -> dict:
    """Generate mock alert records."""
    now = datetime.now(timezone.utc)
    total = _rng.randint(3, 20)
    items = []
    for i in range(min(page_size, total)):
        created = now - timedelta(minutes=_rng.randint(5, 1440))
        alert_sev = severity or _rng.choice(_SEVERITIES)
        alert_t = alert_type or _rng.choice(_ALERT_TYPES)
        alert_status = status or _rng.choice(["active", "acknowledged", "resolved"])
        model = _rng.choice(_MOCK_MODELS)

        threshold_map = {
            "failure_rate_high": 1.0,
            "error_rate_high": 3.0,
            "slow_request": 5000,
            "quality_degradation": 80,
        }
        threshold = threshold_map.get(alert_t, 1.0)
        current = round(threshold * _rng.uniform(1.1, 2.5), 2)

        item = {
            "id": f"alert-{i + 1}",
            "type": alert_t,
            "severity": alert_sev,
            "model_name": model["name"],
            "message": f"{alert_t.replace('_', ' ').title()} detected for {model['display_name']}",
            "threshold": threshold,
            "current_value": current,
            "status": alert_status,
            "created_at": created.isoformat(),
        }
        if alert_status in ("acknowledged", "resolved"):
            item["acknowledged_at"] = (created + timedelta(minutes=5)).isoformat()
        if alert_status == "resolved":
            item["resolved_at"] = (created + timedelta(minutes=30)).isoformat()
        items.append(item)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.get("/models", response_model=ConversationResponse)
async def list_models_endpoint(
    time_range: str = Query("24h", description="Time range: 24h, 7d, 30d"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    authorization: Optional[str] = Header(None),
):
    """List all models with summary monitoring metrics."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        models = [_generate_model_summary(m) for m in _MOCK_MODELS]
        return ConversationResponse(code=0, message="success", data=models)
    except Exception as e:
        logger.error(f"Failed to list monitoring models: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/trend", response_model=ConversationResponse)
async def get_aggregated_trend_endpoint(
    interval: str = Query("1h", description="Interval: 1h, 6h, 1d, 7d"),
    time_range: str = Query("24h", description="Time range: 24h, 7d, 30d"),
    model_id: Optional[str] = Query(None, description="Filter to single model, omit for all-models summary"),
    authorization: Optional[str] = Header(None),
):
    """Get trend data aggregated across all models or filtered to a single model."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        points = _generate_multi_model_trend(interval, time_range, model_id)
        return ConversationResponse(code=0, message="success", data=points)
    except Exception as e:
        logger.error(f"Failed to get aggregated trend: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/models/{model_id}/summary", response_model=ConversationResponse)
async def get_model_summary_endpoint(
    model_id: str,
    authorization: Optional[str] = Header(None),
):
    """Get performance summary for a specific model."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        performance = _generate_performance_detail(model_id)
        error_breakdown = _generate_error_breakdown()
        return ConversationResponse(
            code=0, message="success",
            data={"performance": performance, "error_breakdown": error_breakdown},
        )
    except Exception as e:
        logger.error(f"Failed to get model summary: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/models/{model_id}/trend", response_model=ConversationResponse)
async def get_model_trend_endpoint(
    model_id: str,
    interval: str = Query("1h", description="Interval: 1h, 6h, 1d, 7d"),
    time_range: str = Query("24h", description="Time range: 24h, 7d, 30d"),
    authorization: Optional[str] = Header(None),
):
    """Get trend data for a specific model."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        points = _generate_trend_points(interval, time_range)
        return ConversationResponse(code=0, message="success", data=points)
    except Exception as e:
        logger.error(f"Failed to get model trend: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/models/{model_id}/failures", response_model=ConversationResponse)
async def get_model_failures_endpoint(
    model_id: str,
    failure_type: Optional[str] = Query(None, description="Filter by failure type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    authorization: Optional[str] = Header(None),
):
    """Get failure details for a specific model."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        data = _generate_failures(model_id, page, page_size)
        if failure_type:
            data["items"] = [f for f in data["items"] if f["failure_type"] == failure_type]
            data["total"] = len(data["items"])
        return ConversationResponse(code=0, message="success", data=data)
    except Exception as e:
        logger.error(f"Failed to get model failures: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/alerts", response_model=ConversationResponse)
async def list_alerts_endpoint(
    status: Optional[str] = Query(None, description="Filter by status: active, acknowledged, resolved"),
    severity: Optional[str] = Query(None, description="Filter by severity: critical, warning, info"),
    alert_type: Optional[str] = Query(None, description="Filter by alert type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    authorization: Optional[str] = Header(None),
):
    """List alerts with optional filtering."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        data = _generate_alerts(status, severity, alert_type, page, page_size)
        return ConversationResponse(code=0, message="success", data=data)
    except Exception as e:
        logger.error(f"Failed to list alerts: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/alerts/{alert_id}/acknowledge", response_model=ConversationResponse)
async def acknowledge_alert_endpoint(
    alert_id: str,
    authorization: Optional[str] = Header(None),
):
    """Acknowledge an alert."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return ConversationResponse(code=0, message="success", data={"success": True})
    except Exception as e:
        logger.error(f"Failed to acknowledge alert: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/alerts/{alert_id}/resolve", response_model=ConversationResponse)
async def resolve_alert_endpoint(
    alert_id: str,
    authorization: Optional[str] = Header(None),
):
    """Resolve an alert."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return ConversationResponse(code=0, message="success", data={"success": True})
    except Exception as e:
        logger.error(f"Failed to resolve alert: {str(e)}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))
