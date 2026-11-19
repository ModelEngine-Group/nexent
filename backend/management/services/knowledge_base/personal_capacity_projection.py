# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Pure public personal-capacity projections, with no database or SDK access."""

from typing import Any

from management.services.knowledge_base.quota_formatting import (
    bytes_to_readable as _bytes_to_readable,
)
from management.services.knowledge_base.quota_formatting import (
    vector_bytes_for_display,
    vector_size_for_display,
)
from management.services.permission.identity.display import enrich_cas_usernames


def storage_usage(inputs, observed):
    rows = inputs['knowledge_bases']
    stats, details = {}, {}
    for row in rows:
        index = row.get('index_name')
        if not index:
            continue
        source = inputs['source_bytes_by_kb'].get(row['knowledge_id'], 0)
        physical = observed.get(row['knowledge_id'])
        size = vector_size_for_display(physical.size_bytes) if physical is not None else None
        stats[index] = source
        details[index] = {
            'store_size': size, 'store_size_bytes': vector_bytes_for_display(physical.size_bytes) if physical is not None else 0,
            'source_size': _bytes_to_readable(source), 'source_size_bytes': source,
            'total_size': _bytes_to_readable(source), 'total_size_bytes': source,
            'doc_count': physical.source_count if physical is not None else 0,
            'chunk_count': physical.record_count if physical is not None else 0,
        }
    return {'kbs': rows, 'stats': stats, 'details': details, 'total_bytes': sum(stats.values()),
            'total_es_bytes': sum(row['store_size_bytes'] for row in details.values())}


def group_usage(usage_data, quotas):
    grouped = group_storage(usage_data)
    for user, row in grouped.items():
        row['effective_quota_bytes'], row['quota_source'] = quotas.get(user, (None, 'unlimited'))
    return grouped


def group_storage(
    usage_data: dict[str, Any],
    user_ids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Aggregate unified personal storage by KB creator."""
    grouped: dict[str, dict[str, Any]] = {}
    for kb in usage_data["kbs"]:
        user_id = kb.get("created_by")
        if not user_id or (user_ids is not None and user_id not in user_ids):
            continue
        item = grouped.setdefault(
            user_id,
            {"kbs": [], "kb_count": 0, "total_bytes": 0},
        )
        item["kbs"].append(kb)
        item["kb_count"] += 1
        item["total_bytes"] += usage_data["stats"].get(kb.get("index_name", ""), 0)
        detail = usage_data.get("details", {}).get(kb.get("index_name", ""), {})
        item["es_physical_bytes"] = item.get("es_physical_bytes", 0) + int(
            detail.get("store_size_bytes", 0) or 0
        )

    for user_id in user_ids or set():
        grouped.setdefault(
            user_id,
            {"kbs": [], "kb_count": 0, "total_bytes": 0, "es_physical_bytes": 0},
        )

    return grouped


def list_users(
    usage_data, quotas, email_map, identities,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "total_bytes",
    sort_order: str = "desc",
    keyword: str | None = None,
) -> dict[str, Any]:
    """List personal KB storage aggregated by creator with pagination."""
    user_usage = group_usage(usage_data, quotas)
    user_ids = sorted(user_usage)

    items = []
    for user_id in user_ids:
        user_data = user_usage[user_id]
        quota_limit_bytes = user_data["effective_quota_bytes"]
        quota_source = user_data["quota_source"]
        total_bytes = user_data["total_bytes"]
        es_physical_bytes = user_data.get("es_physical_bytes")
        items.append(
            {
                "user_id": user_id,
                "user_name": email_map.get(user_id) or user_id,
                "email": email_map.get(user_id),
                "kb_count": user_data["kb_count"],
                "total_bytes": total_bytes,
                "total_readable": _bytes_to_readable(total_bytes),
                "es_physical_bytes": es_physical_bytes,
                "es_physical_readable": _bytes_to_readable(es_physical_bytes),
                "quota_limit_bytes": quota_limit_bytes,
                "quota_limit_readable": _bytes_to_readable(quota_limit_bytes),
                "effective_quota_bytes": quota_limit_bytes,
                "effective_quota_readable": _bytes_to_readable(quota_limit_bytes),
                "quota_source": quota_source,
                "usage_rate": (
                    round(total_bytes / quota_limit_bytes * 100, 2)
                    if quota_limit_bytes and quota_limit_bytes > 0
                    else None
                ),
            }
        )

    if keyword:
        lowered_keyword = keyword.strip().lower()
        if lowered_keyword:
            items = [
                item
                for item in items
                if lowered_keyword in str(item["user_name"]).lower()
                or lowered_keyword in (item.get("email") or "").lower()
            ]

    sort_keys = {
        "user_name": lambda item: str(item["user_name"]).lower(),
        "kb_count": lambda item: item["kb_count"],
        "total_bytes": lambda item: item["total_bytes"],
        "quota_limit_bytes": lambda item: (
            item["quota_limit_bytes"]
            if item["quota_limit_bytes"] is not None
            else -1
        ),
        "usage_rate": lambda item: (
            item["usage_rate"] if item["usage_rate"] is not None else -1
        ),
    }
    key_func = sort_keys.get(sort_by, sort_keys["total_bytes"])
    items.sort(key=key_func, reverse=sort_order.lower() != "asc")

    total = len(items)
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    start = (page - 1) * page_size
    paged = items[start : start + page_size] if page_size > 0 else items

    enrich_cas_usernames(paged, {"cas_username": "user_id"}, identities=identities)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "items": paged,
    }


def kb_details(
    usage_data,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List a user's personal KB records with unified storage details."""
    kb_list = usage_data["kbs"]
    kb_list.sort(
        key=lambda kb: str(
            kb.get("last_doc_update_time") or kb.get("update_time") or ""
        ),
        reverse=True,
    )

    total = len(kb_list)
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    start = (page - 1) * page_size
    paged = kb_list[start : start + page_size] if page_size > 0 else kb_list

    kbs = []
    for kb in paged:
        index_name = kb.get("index_name", "")
        detail = usage_data["details"].get(index_name, {})
        quota_limit_bytes = kb.get("quota_limit_bytes")
        kbs.append(
            {
                "kb_id": kb.get("knowledge_id"),
                "knowledge_id": kb.get("knowledge_id"),
                "index_name": index_name,
                "name": kb.get("knowledge_name") or index_name,
                "source": kb.get("knowledge_sources"),
                "doc_count": detail.get("doc_count", 0),
                "chunk_count": detail.get("chunk_count", 0),
                "store_size": detail.get("store_size"),
                "store_size_bytes": detail.get("store_size_bytes", 0),
                "es_physical_size": detail.get("store_size"),
                "es_physical_size_bytes": detail.get("store_size_bytes", 0),
                "source_size": detail.get("source_size"),
                "source_size_bytes": detail.get("source_size_bytes", 0),
                "total_size": detail.get("total_size"),
                "total_size_bytes": detail.get("total_size_bytes", 0),
                "quota_limit_bytes": quota_limit_bytes,
                "quota_limit_readable": _bytes_to_readable(quota_limit_bytes),
                "updated_at": (
                    kb.get("last_doc_update_time") or kb.get("update_time")
                ),
            }
        )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "kbs": kbs,
    }


def summary(usage_data, quotas, default_quota) -> dict[str, Any]:
    """Return aggregate personal KB capacity stats for the tenant."""
    kb_list = usage_data["kbs"]
    user_usage = group_usage(usage_data, quotas)
    allocated_quota_bytes = 0
    for user_data in user_usage.values():
        quota_limit_bytes = user_data["effective_quota_bytes"]
        if quota_limit_bytes is not None:
            allocated_quota_bytes += quota_limit_bytes

    return {
        "user_count": len(user_usage),
        "kb_count": len(kb_list),
        "total_bytes": usage_data["total_bytes"],
        "total_readable": _bytes_to_readable(usage_data["total_bytes"]),
        "total_es_physical_bytes": usage_data["total_es_bytes"],
        "total_es_physical_readable": _bytes_to_readable(
            usage_data["total_es_bytes"]
        ),
        "allocated_quota_bytes": allocated_quota_bytes,
        "allocated_quota_readable": _bytes_to_readable(allocated_quota_bytes),
        "default_quota_bytes": default_quota,
        "default_quota_readable": _bytes_to_readable(default_quota),
    }
