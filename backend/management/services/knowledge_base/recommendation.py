# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Recommend authorized knowledge metadata without changing Agent bindings."""

import json
import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz

MANAGED_KNOWLEDGE_NAMES = {"knowledge_base_search", "aidp_search"}
_GENERIC_TERMS = {
    "知识库",
    "知识",
    "检索",
    "搜索",
    "内部资料",
    "knowledge",
    "knowledgebase",
    "search",
    "retrieval",
    "knowledge_base_search",
    "aidp_search",
}


def selection_values(value: Any) -> list[str]:
    """Read local arrays and legacy AIDP JSON/CSV ranges without losing IDs."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = value.split(",") if not value.strip().startswith("[") else []
    return (
        list(
            dict.fromkeys(
                str(item).strip()
                for item in value
                if isinstance(item, (str, int))
                and not isinstance(item, bool)
                and str(item).strip()
            )
        )
        if isinstance(value, list)
        else []
    )


def load_visible_knowledge(
    tool_name: str, *, user_id: str, tenant_id: str
) -> list[dict[str, Any]]:
    """Reuse permission-scoped provider catalogs; return inert metadata only."""
    if tool_name == "aidp_search":
        from management.services.knowledge_base.scope import (
            _resolve_aidp_access_snapshot,
        )

        snapshot = _resolve_aidp_access_snapshot(user_id, tenant_id)
        return [
            {
                "id": str(row["kb_id"]),
                "binding_value": str(row["kb_id"]),
                "name": row.get("kds_name")
                or row.get("name")
                or row.get("kb_name")
                or str(row["kb_id"]),
                "description": row.get("description") or "",
                "summary": row.get("summary") or "",
            }
            for row in snapshot.accessible_rows
            if row.get("kb_id")
            and str(row.get("resource_status") or "ACTIVE").upper() == "ACTIVE"
        ]

    from consts.const import ASSET_OWNER_TENANT_ID
    from management.db.knowledge_base.repository import get_knowledge_metadata_by_index_names
    from management.services.knowledge_base.common import get_vector_db_core
    from management.services.knowledge_base.service import ElasticSearchService

    core = get_vector_db_core()
    indices = set()
    for scope_tenant in dict.fromkeys([tenant_id, ASSET_OWNER_TENANT_ID]):
        visible = ElasticSearchService.list_indices(
            user_id=user_id,
            target_tenant_id=scope_tenant,
            include_stats=False,
            vdb_core=core,
        )
        indices.update(visible.get("indices") or [])
    records = get_knowledge_metadata_by_index_names(list(indices)) if indices else []
    return [
        {
            "id": str(row["knowledge_id"]),
            "binding_value": row["index_name"],
            "name": row.get("knowledge_name") or row["index_name"],
            "description": row.get("description") or "",
            "summary": row.get("knowledge_describe") or row.get("summary") or "",
            "embedding_model_id": row.get("embedding_model_id"),
            "is_multimodal": row.get("is_multimodal"),
        }
        for row in records
        if row.get("index_name") in indices and row.get("knowledge_id") is not None
    ]


def _normalize(text: Any) -> str:
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", str(text or "")).casefold()
    ).strip()


def _metadata_similarity(term: str, text: str) -> float:
    """Avoid matching short English tokens inside unrelated words."""
    if term.isascii() and len(term) <= 3:
        return 1.0 if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) else 0.0
    return (
        1.0 if term in text or text and text in term else fuzz.WRatio(term, text) / 100
    )


def rank_knowledge(
    catalog: list[dict[str, Any]],
    queries: list[str],
    bound_values: list[str],
    *,
    tool_name: str,
    multimodal: bool | None = None,
) -> list[dict[str, Any]]:
    """Subtract direct bindings before conservative metadata matching and caps."""
    bound = set(bound_values)
    terms = list(
        dict.fromkeys(_normalize(query) for query in queries if _normalize(query))
    )
    terms = [term for term in terms if len(term) >= 2 and term not in _GENERIC_TERMS]
    current_models = {
        row.get("embedding_model_id")
        for row in catalog
        if row["binding_value"] in bound
    }
    ranked = []
    for row in catalog:
        if row["binding_value"] in bound:
            continue
        if tool_name == "knowledge_base_search":
            if current_models and row.get("embedding_model_id") not in current_models:
                continue
            if (
                multimodal is not None
                and row.get("is_multimodal") is not None
                and bool(row["is_multimodal"]) != bool(multimodal)
            ):
                continue
        name = _normalize(row["name"])
        description = _normalize(
            f"{row.get('description', '')} {row.get('summary', '')}"
        )
        score = max(
            (
                max(
                    _metadata_similarity(term, name),
                    _metadata_similarity(term, description) * 0.9,
                )
                for term in terms
            ),
            default=0,
        )
        if score >= 0.78:
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1]["binding_value"]))
    if tool_name == "knowledge_base_search" and ranked:
        model = ranked[0][1].get("embedding_model_id")
        ranked = [
            (score, row)
            for score, row in ranked
            if row.get("embedding_model_id") == model
        ]
    limit = min(5, max(0, 10 - len(bound))) if tool_name == "aidp_search" else 5
    return [
        {key: row[key] for key in ("id", "binding_value", "name")}
        | {"score": round(score, 4)}
        for score, row in ranked[:limit]
    ]


def merge_selection(
    config: list[dict[str, Any]], tool_name: str, values: list[str]
) -> list[dict[str, Any]]:
    """Preserve retrieval settings and add the canonical selected range."""
    name = "kds_list" if tool_name == "aidp_search" else "index_names"
    transient = (
        {
            "display_names",
            "server_url",
            "api_key",
            "tenant_id",
            "kds_name_to_id_map",
            "observer",
        }
        if tool_name == "aidp_search"
        else set()
    )
    result = [
        dict(param)
        for param in config
        if param.get("name") != name and param.get("name") not in transient
    ]
    existing = next((param for param in config if param.get("name") == name), {})
    result.append(
        {
            **existing,
            "name": name,
            "type": "string" if name == "kds_list" else "array",
            "required": True,
            "value": json.dumps(values, ensure_ascii=False)
            if name == "kds_list"
            else values,
        }
    )
    return result
