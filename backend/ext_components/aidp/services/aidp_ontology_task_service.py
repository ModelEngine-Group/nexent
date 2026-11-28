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


def list_tasks_impl(
    server_url: str,
    api_key: str,
    *,
    page: int = 1,
    page_size: int = 20,
    task_type: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Return one page of tasks.

    AIDP has no sort parameter, so the page order is forwarded as-is. Sorting
    newest-first is an upstream contract gap; the proxy must not fetch every
    page to emulate it.
    """
    params: dict[str, Any] = {"page": page, "page_size": page_size}
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
    items, total, task_count = _extract_tasks(source)
    normalized = [_normalize_task(item) for item in items]
    total_count = (
        total if total is not None else (page - 1) * page_size + len(normalized)
    )
    return {
        "value": normalized,
        "total_count": total_count,
        "task_count": task_count,
        "has_more": page * page_size < total_count,
        "total_reliable": total is not None,
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
