# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP background task query operations."""

from __future__ import annotations

import logging
from typing import Any

from ext_components.aidp.services.aidp_ontology_common import (
    _log_business_failure,
    _ontology_request,
    _resolve_tenant_id,
)


logger = logging.getLogger("aidp_ontology_task_service")


def _get_tasks_path(tenant_id: str | None = None) -> str:
    return f"/KnowledgeBase/Tenants/{_resolve_tenant_id(tenant_id)}/Tasks"


def _normalize_task(item: dict[str, Any]) -> dict[str, Any]:
    task_id = item.get("id") or item.get("task_id")
    progress = item.get("progress")
    return {
        "task_id": str(task_id) if task_id is not None else None,
        "task_type": item.get("task_type") or item.get("type"),
        "status": item.get("status"),
        "progress": progress
        if isinstance(progress, int) and not isinstance(progress, bool)
        else None,
        "description": item.get("description") or "",
        "error_message": item.get("error_message") or "",
        "start_time": item.get("start_time"),
        "end_time": item.get("end_time"),
    }


def _extract_tasks(
    source: dict[str, Any],
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    raw_items = source.get("task_list")
    if not isinstance(raw_items, list):
        raw_items = source.get("value")
    if not isinstance(raw_items, list):
        raw_items = source.get("items")
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    raw_total = source.get("total")
    if raw_total is None:
        raw_total = source.get("total_count")
    total = (
        raw_total
        if isinstance(raw_total, int) and not isinstance(raw_total, bool)
        else None
    )
    raw_count = source.get("task_count")
    count = (
        raw_count
        if isinstance(raw_count, int) and not isinstance(raw_count, bool)
        else None
    )
    return items, total, count


def _task_sort_key(task: dict[str, Any]) -> tuple[float, int]:
    try:
        start = float(task.get("start_time") or 0)
    except (TypeError, ValueError):
        start = 0
    raw_id = str(task.get("task_id") or "")
    try:
        task_id = int(raw_id)
    except ValueError:
        task_id = 0
    return start, task_id


def list_tasks_impl(
    server_url: str,
    api_key: str,
    *,
    page: int = 1,
    page_size: int = 20,
    task_type: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Return newest-first tasks.

    AIDP has no sort parameter and always answers ascending id order. Fetch all
    pages once, sort locally, then apply the requested page so the first page is
    actually the latest. The task volume is small (hundreds), so this bounded
    aggregation is preferable to showing stale tasks first.
    """
    fetched: list[dict[str, Any]] = []
    total: int | None = None
    task_count: int | None = None
    fetch_page = 1
    fetch_size = 100
    while fetch_page <= 100:
        params: dict[str, Any] = {"page": fetch_page, "page_size": fetch_size}
        if task_type:
            params["task_type"] = task_type
        payload = _ontology_request(
            server_url,
            api_key,
            "GET",
            _get_tasks_path(tenant_id),
            operation="list-tasks",
            params=params,
        )
        _log_business_failure(payload, "list-tasks")
        data = payload.get("data") if isinstance(payload, dict) else None
        source = (
            data
            if isinstance(data, dict)
            else (payload if isinstance(payload, dict) else {})
        )
        items, page_total, page_count = _extract_tasks(source)
        fetched.extend(items)
        total = page_total if page_total is not None else total
        task_count = page_count if page_count is not None else task_count
        if not items or len(items) < fetch_size:
            break
        if total is not None and fetch_page * fetch_size >= total:
            break
        fetch_page += 1

    normalized = [_normalize_task(item) for item in fetched]
    normalized.sort(key=_task_sort_key, reverse=True)
    total_count = total if total is not None else len(normalized)
    start = max(page - 1, 0) * page_size
    end = start + page_size
    return {
        "value": normalized[start:end],
        "total_count": total_count,
        "task_count": task_count,
        "has_more": end < total_count,
        "total_reliable": True,
    }


def get_task_impl(
    server_url: str,
    api_key: str,
    task_id: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    payload = _ontology_request(
        server_url,
        api_key,
        "GET",
        f"{_get_tasks_path(tenant_id)}/{task_id}",
        operation="get-task",
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    source = (
        data
        if isinstance(data, dict)
        else (payload if isinstance(payload, dict) else {})
    )
    task = source.get("task") if isinstance(source, dict) else None
    if isinstance(task, dict):
        source = task
    return _normalize_task(source) if isinstance(source, dict) else {}
