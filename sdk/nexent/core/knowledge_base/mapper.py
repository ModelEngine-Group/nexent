"""Mapping helpers between Nexent's standard adapter API and AIDP."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_CAPTION_ENABLE,
    DEFAULT_CHUNK_OVERLAP_NUM,
    DEFAULT_CHUNK_TOKEN_NUM,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_IS_PERSONAL,
    DEFAULT_SIMILARITY,
    DEFAULT_SMARTSPLIT,
    DEFAULT_TOP_K,
    DEFAULT_VLM_MODEL,
)


def success_response(data: Any) -> dict[str, Any]:
    return {"code": 0, "data": data, "message": "success"}


def error_response(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "data": None, "message": message}


def timestamp_to_iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return str(value)
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_kms_config(raw: dict[str, Any]) -> dict[str, Any]:
    config = raw.get("kms_config_str") or "{}"
    if not isinstance(config, str):
        return {}
    try:
        parsed = json.loads(config)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def map_kb_status(state: Any) -> str:
    try:
        state_value = int(state)
    except (TypeError, ValueError):
        return "active"
    return "active" if state_value == 4 else "inactive"


def map_knowledge_base(raw: dict[str, Any], document_count: int | None = None) -> dict[str, Any]:
    config = parse_kms_config(raw)
    create_time = raw.get("create_time") or raw.get("created_at")
    update_time = raw.get("update_time") or raw.get("updated_at") or create_time
    return {
        "id": str(raw.get("kds_id") or raw.get("id") or ""),
        "name": str(raw.get("kds_name") or raw.get("name") or ""),
        "description": str(raw.get("description") or ""),
        "embedding_model": str(config.get("embedding_model") or raw.get("embedding_model") or DEFAULT_EMBEDDING_MODEL),
        "document_count": int(document_count if document_count is not None else raw.get("document_count") or 0),
        "status": map_kb_status(raw.get("state") or raw.get("status")),
        "created_at": timestamp_to_iso(create_time),
        "updated_at": timestamp_to_iso(update_time),
    }


def map_knowledge_base_list(raw: dict[str, Any], page: int, page_size: int, total_count: int) -> dict[str, Any]:
    items = raw.get("value")
    if not isinstance(items, list):
        items = []
    return {
        "list": [map_knowledge_base(item) for item in items if isinstance(item, dict)],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total_count,
    }


def build_create_payload(body: dict[str, Any]) -> dict[str, Any]:
    is_multimodal = bool(body.get("is_multimodal", False))
    return {
        "name": body["name"],
        "description": body.get("description") or "",
        "chunk_token_num": DEFAULT_CHUNK_TOKEN_NUM,
        "chunk_overlap_num": DEFAULT_CHUNK_OVERLAP_NUM,
        "embedding_model": body.get("embedding_model") or DEFAULT_EMBEDDING_MODEL,
        "vlm_model": body.get("vision_model") or DEFAULT_VLM_MODEL,
        "is_personal": DEFAULT_IS_PERSONAL,
        "topk": DEFAULT_TOP_K,
        "similarity": DEFAULT_SIMILARITY,
        "smartsplit": DEFAULT_SMARTSPLIT,
        "caption_enable": 1 if is_multimodal else DEFAULT_CAPTION_ENABLE,
    }


def build_update_payload(body: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if body.get("name") is not None:
        payload["name"] = body["name"]
    if body.get("description") is not None:
        payload["description"] = body["description"]
    return payload


def encode_document_id(file_info: dict[str, Any]) -> str:
    identity = {
        "file_name": file_info.get("file_name") or file_info.get("name") or "",
        "file_ino_no": file_info.get("file_ino_no") or file_info.get("file_ino") or "",
        "file_system_id": file_info.get("file_system_id") or file_info.get("fs_id") or "",
        "import_source_dir": file_info.get("import_source_dir") or file_info.get("dir_path") or "",
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def map_upload_response(raw: dict[str, Any]) -> dict[str, Any]:
    success_list = raw.get("success_list") if isinstance(raw, dict) else []
    failed_list = raw.get("failed_list") if isinstance(raw, dict) else []
    if not isinstance(success_list, list):
        success_list = []
    if not isinstance(failed_list, list):
        failed_list = []
    return {
        "document_ids": [encode_document_id(item) for item in success_list if isinstance(item, dict)],
        "failed_files": [
            {
                "name": str(item.get("file_name") or ""),
                "error": str(item.get("reason_cn") or item.get("reason") or ""),
            }
            for item in failed_list
            if isinstance(item, dict)
        ],
    }


def map_document(raw: dict[str, Any], knowledge_base_id: str) -> dict[str, Any]:
    file_name = str(raw.get("file_name") or "")
    file_type = str(raw.get("file_type") or Path(file_name).suffix.lstrip("."))
    return {
        "id": encode_document_id(raw),
        "name": file_name,
        "knowledge_base_id": str(knowledge_base_id),
        "size": int(raw.get("file_size") or 0),
        "type": file_type,
        "status": "completed",
        "chunk_count": 0,
        "token_count": 0,
        "created_at": timestamp_to_iso(raw.get("first_upload_time")),
        "updated_at": timestamp_to_iso(raw.get("update_time") or raw.get("first_upload_time")),
    }


def map_document_list(raw: dict[str, Any], knowledge_base_id: str, page: int, page_size: int) -> dict[str, Any]:
    items = raw.get("value")
    if not isinstance(items, list):
        items = []
    total = int(raw.get("total_count") or len(items))
    return {
        "list": [map_document(item, knowledge_base_id) for item in items if isinstance(item, dict)],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


SEARCH_METHOD_MAP = {
    "semantic_search": "vector_search",
    "keyword_search": "full_text_search",
    "hybrid_search": "hybrid_search",
}


def build_retrieve_payload(body: dict[str, Any]) -> dict[str, Any]:
    retrieval_model = body.get("retrieval_model") or {}
    if not isinstance(retrieval_model, dict):
        retrieval_model = {}
    search_method = retrieval_model.get("search_method") or "semantic_search"
    payload: dict[str, Any] = {
        "query": body["query"],
        "kds_list": [str(item) for item in body.get("knowledge_base_ids") or []],
        "search_method": SEARCH_METHOD_MAP.get(search_method, "vector_search"),
        "reranking_enable": bool(retrieval_model.get("reranking_enable", False)),
        "rewrite_enable": False,
        "related_search_enable": False,
        "score_threshold": retrieval_model.get("score_threshold") if retrieval_model.get("score_threshold_enabled") else 0.0,
        "top_k": int(retrieval_model.get("top_k") or 5),
        "multi_modal": True,
    }
    if payload["reranking_enable"]:
        payload["reranking_mode"] = "performance"
    return payload


def map_retrieve_response(raw: dict[str, Any], query: str, knowledge_base_ids: list[str]) -> dict[str, Any]:
    items = raw.get("result")
    if not isinstance(items, list):
        items = []
    records = []
    fallback_kb_id = knowledge_base_ids[0] if len(knowledge_base_ids) == 1 else ""
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        title = str(item.get("title") or metadata.get("file_name") or "")
        records.append(
            {
                "segment": {
                    "id": str(item.get("id") or ""),
                    "position": index,
                    "document_id": str(metadata.get("document_id") or title),
                    "document_name": title,
                    "knowledge_base_id": str(metadata.get("kds_id") or fallback_kb_id),
                    "knowledge_base_name": str(metadata.get("kds_name") or ""),
                    "content": str(item.get("text") or ""),
                    "keywords": [],
                    "tokens": 0,
                    "index_node_id": str(item.get("id") or ""),
                    "hit_count": 0,
                    "enabled": True,
                },
                "score": float(item.get("score") or 0),
            }
        )
    records.sort(key=lambda record: record["score"], reverse=True)
    return {"query": query, "records": records}
