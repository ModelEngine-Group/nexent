# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge-base list result normalization and composition."""

from typing import Any, Optional

from contracts.constants.constants import PERMISSION_READ


def apply_read_only_to_asset_indices_info(result: dict[str, Any]) -> dict[str, Any]:
    """Copy asset-owned rows and expose them as read-only."""
    indices_info = result.get("indices_info")
    if not indices_info:
        return result
    normalized = dict(result)
    normalized["indices_info"] = [
        {**info, "permission": PERMISSION_READ} for info in indices_info
    ]
    return normalized


def _sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("update_time") or ""),
        str(item.get("knowledge_id") or "").zfill(20),
        str(item.get("name") or ""),
    )


def _merge_ordered_info(
    primary_info: list[dict[str, Any]], asset_info: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = []
    primary_index = asset_index = 0
    while primary_index < len(primary_info) and asset_index < len(asset_info):
        if _sort_key(primary_info[primary_index]) >= _sort_key(asset_info[asset_index]):
            merged.append(primary_info[primary_index])
            primary_index += 1
        else:
            merged.append(asset_info[asset_index])
            asset_index += 1
    merged.extend(primary_info[primary_index:])
    merged.extend(asset_info[asset_index:])
    return merged


def merge_indices_results(
    primary: dict[str, Any],
    asset_owner: dict[str, Any],
    *,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Merge tenant and asset-owner results, optionally returning a global page."""
    asset_owner = apply_read_only_to_asset_indices_info(asset_owner)
    combined_indices = primary.get("indices", []) + asset_owner.get("indices", [])
    has_info = "indices_info" in primary or "indices_info" in asset_owner
    if offset is None or limit is None:
        result = {"indices": combined_indices, "count": len(combined_indices)}
        if has_info:
            result["indices_info"] = primary.get("indices_info", []) + asset_owner.get(
                "indices_info", []
            )
        return result

    combined_info = _merge_ordered_info(
        primary.get("indices_info", []),
        asset_owner.get("indices_info", []),
    )
    page_info = combined_info[offset : offset + limit]
    page_indices = (
        [item["name"] for item in page_info]
        if combined_info
        else combined_indices[offset : offset + limit]
    )
    total = int(primary.get("total", primary.get("count", 0))) + int(
        asset_owner.get("total", asset_owner.get("count", 0))
    )
    next_offset = offset + len(page_indices)
    source_facets = set(primary.get("facets", {}).get("sources", []))
    source_facets.update(asset_owner.get("facets", {}).get("sources", []))
    model_facets = set(primary.get("facets", {}).get("models", []))
    model_facets.update(asset_owner.get("facets", {}).get("models", []))
    result = {
        "indices": page_indices,
        "count": len(page_indices),
        "total": total,
        "next_offset": next_offset if next_offset < total else None,
        "facets": {"sources": sorted(source_facets), "models": sorted(model_facets)},
        "estimated_row_height": 112,
        "estimated_item_heights": None,
    }
    if has_info:
        result["indices_info"] = page_info
    return result


def merge_list_indices_results(
    primary: dict[str, Any], asset_owner: dict[str, Any]
) -> dict[str, Any]:
    return merge_indices_results(primary, asset_owner)


def merge_paginated_list_indices_results(
    primary: dict[str, Any],
    asset_owner: dict[str, Any],
    offset: int,
    limit: int,
) -> dict[str, Any]:
    return merge_indices_results(primary, asset_owner, offset=offset, limit=limit)


def prepare_indices_page(
    visible_knowledgebases: list[dict[str, Any]],
    pagination_enabled: bool,
    offset: int,
    limit: int | None,
    keyword: str | None,
    sources: list[str] | None,
    models: list[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply list filters and optional pagination to ordered visible records."""
    facets = {
        "sources": sorted(
            {
                str(record.get("knowledge_sources"))
                for record in visible_knowledgebases
                if record.get("knowledge_sources")
            }
        ),
        "models": sorted(
            {
                str(record.get("embedding_model_name"))
                for record in visible_knowledgebases
                if record.get("embedding_model_name")
            }
        ),
    }
    normalized_keyword = (keyword or "").strip().lower()
    selected_sources = {source for source in (sources or []) if source}
    selected_models = {model for model in (models or []) if model}
    filtered = [
        record
        for record in visible_knowledgebases
        if (
            not normalized_keyword
            or normalized_keyword in str(record.get("knowledge_name") or "").lower()
            or normalized_keyword in str(record.get("description") or "").lower()
            or normalized_keyword in str(record.get("nickname") or "").lower()
        )
        and (
            not selected_sources
            or record.get("knowledge_sources") in selected_sources
        )
        and (
            not selected_models
            or record.get("embedding_model_name") in selected_models
        )
    ]
    if not pagination_enabled:
        return filtered, {}
    if limit is None:
        raise ValueError("limit is required when pagination is enabled")

    total = len(filtered)
    page = filtered[offset : offset + limit]
    next_offset = offset + len(page)
    return page, {
        "total": total,
        "next_offset": next_offset if next_offset < total else None,
        "facets": facets,
    }
