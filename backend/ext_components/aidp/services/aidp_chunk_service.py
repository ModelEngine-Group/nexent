# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP document chunk proxy service (CRUD, file-scoped search, chunk images).

Every request addresses AIDP's fixed ``aidp`` tenant namespace under
``/KnowledgeBase/Tenants/aidp/KnowledgeBases/{kds_id}/Chunks``. Chunk ids are
normalized to ints, TEXT and TABLE chunks are the editable types, and the
file-scoped search is a dedicated FusionSearch call that reuses the SDK
retrieval policy rather than the model-facing ``aidp_search`` tool.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from urllib.parse import urljoin

import httpx
from nexent.core.ext_components.aidp.retrieval_config import (
    build_payload,
    resolve_config,
)
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from ext_components.aidp.services import aidp_client
from ext_components.aidp.services.aidp_client import (
    _AIDP_READ_TIMEOUT_SECONDS,
    _get_chunks_path,
    _get_retrieval_path,
    _get_view_image_path,
    _raise_aidp_http_error,
    _request_aidp_json,
    _validate_params,
)
from ext_components.aidp.services.aidp_service import _extract_list_payload


logger = logging.getLogger("aidp_chunk_service")

AIDP_CHUNK_TEXT_MAX_LENGTH = 10240
AIDP_CHUNK_REMOVE_MAX_IDS = 2000


def _normalize_chunk_id(value: Any) -> Any:
    """Return a chunk id in the numeric form the AIDP contract declares.

    AIDP types ``chunk_id`` (and ``page_ids``) as int64, but deployments
    serialize them as numeric strings. Converting numeric strings keeps ids
    usable as route parameters, while anything else is returned unchanged
    instead of being coerced into a different identifier.
    """
    if isinstance(value, (bool, int)):
        return value
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip())
    return value


def _file_name_stem(name: str) -> str:
    """Return a file name without its last extension.

    AIDP keeps two name shapes for the same file: the KnowledgeFiles list
    reports ``file_name`` without the extension while retrieval ``title`` and
    ``original_file_name`` keep it (verified 2026-11-18). Comparing stems lets
    the defensive title check agree with the ``contains`` filter for both
    shapes.
    """
    base = name.strip().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem, dot, _ = base.rpartition(".")
    return stem if dot else base


def _normalize_aidp_chunk(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one AIDP chunk item without inventing missing fields.

    Only types are corrected: the text, type, name/path and metadata are passed
    through as reported so the page can show an empty state instead of made-up
    content for anything AIDP omitted.
    """
    out = dict(raw)
    if "chunk_id" in out:
        out["chunk_id"] = _normalize_chunk_id(out.get("chunk_id"))

    page_ids = out.get("page_ids")
    if isinstance(page_ids, list):
        normalized_pages = [_normalize_chunk_id(page) for page in page_ids]
        out["page_ids"] = [
            page
            for page in normalized_pages
            if isinstance(page, int) and not isinstance(page, bool)
        ]
    elif page_ids is not None:
        out["page_ids"] = []

    metadata = out.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        out["metadata"] = {}
    return out


def list_aidp_chunks_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuid: str,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """List the chunks AIDP generated for one file of a knowledge base.

    ``file_uuid`` is the only query condition the contract declares: there is
    no keyword filter, so a content search cannot be forwarded from the page.
    """
    result = _request_aidp_json(
        server_url,
        api_key,
        "GET",
        _get_chunks_path(kds_id),
        context="list-chunks",
        params={"file_uuid": file_uuid, "page": page, "page_size": page_size},
    )
    if not isinstance(result, dict):
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "Unexpected AIDP chunk list response format",
        )
    items = _extract_list_payload(result)
    if items is None:
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "AIDP chunk list response does not contain a chunk list",
        )
    result["value"] = [
        _normalize_aidp_chunk(item) if isinstance(item, dict) else item
        for item in items
    ]
    return result


def get_aidp_chunk_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    chunk_id: int,
) -> Dict[str, Any]:
    """Read one chunk's current text and metadata."""
    result = _request_aidp_json(
        server_url,
        api_key,
        "GET",
        f"{_get_chunks_path(kds_id)}/{chunk_id}",
        context="get-chunk",
    )
    if not isinstance(result, dict):
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "Unexpected AIDP chunk detail response format",
        )
    return _normalize_aidp_chunk(result)


def create_aidp_chunk_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_uuid: str,
    chunk_text: str,
) -> Dict[str, Any]:
    """Add one text chunk to a file; AIDP answers with the new ``chunk_id``.

    AIDP appends the chunk to the file's chunk list and documents that the
    payload carries only ``file_uuid`` and ``chunk_text``; there is no page,
    order or coordinate input. The example response spells ``chunk_id`` as a
    numeric string, so it is normalized to the numeric form every other chunk
    endpoint uses before the value reaches the caller.
    """
    result = _request_aidp_json(
        server_url,
        api_key,
        "PUT",
        _get_chunks_path(kds_id),
        context="create-chunk",
        retry=False,
        json_body={"file_uuid": file_uuid, "chunk_text": chunk_text},
    )
    if not isinstance(result, dict):
        return {}
    if "chunk_id" in result:
        result["chunk_id"] = _normalize_chunk_id(result["chunk_id"])
    return result


def update_aidp_chunk_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    chunk_id: int,
    chunk_text: str,
) -> Dict[str, Any]:
    """Update one chunk's text and return the full chunk AIDP sends back.

    AIDP regenerates the chunk vector after a text edit and answers with the
    updated ``chunk_id``/``chunk_text``/``chunk_type``/``page_ids``/``metadata``
    object, which the page uses to refresh the detail instead of assuming how
    the update affected those fields.
    """
    result = _request_aidp_json(
        server_url,
        api_key,
        "PATCH",
        f"{_get_chunks_path(kds_id)}/{chunk_id}",
        context="update-chunk",
        retry=False,
        json_body={"chunk_text": chunk_text},
    )
    if not isinstance(result, dict):
        return {}
    return _normalize_aidp_chunk(result)


def remove_aidp_chunks_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    chunk_ids: List[int],
) -> Dict[str, Any]:
    """Remove up to 2000 chunks with ``POST /Chunks/Remove`` and a JSON body.

    The 2026-11-20 contract run confirms the removal endpoint is the POST
    ``Chunks/Remove`` route; the earlier ``DELETE /Chunks`` variant answered
    405 on the real deployment. AIDP answers ``204 No Content`` either way,
    so an empty response is the success contract, not a parse failure.
    """
    result = _request_aidp_json(
        server_url,
        api_key,
        "POST",
        f"{_get_chunks_path(kds_id)}/Remove",
        context="remove-chunks",
        retry=False,
        json_body={"chunk_ids": list(chunk_ids)},
    )
    return result if isinstance(result, dict) else {}


def get_aidp_image_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_id: str,
    tenant_id: str | None = None,
) -> tuple[bytes, str]:
    """Fetch one chunk image's binary content and its content type.

    Unlike the JSON endpoints, ViewImage answers raw image bytes on success,
    so this reads the body without JSON decoding. Failures follow AIDP's JSON
    error envelope and map through the common upstream error handler.
    """
    normalized_url = _validate_params(server_url, api_key)
    url = urljoin(
        f"{normalized_url}/", _get_view_image_path(kds_id, file_id, tenant_id)
    )
    logger.info("AIDP view-image: GET %s", url)
    try:
        client = aidp_client.http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = client.get(
            url, headers={"Authorization": f"Bearer {api_key}"}
        )
        response.raise_for_status()
    except httpx.RequestError as e:
        logger.exception("AIDP image request failed: %s", e)
        raise AppException(
            ErrorCode.AIDP_CONNECTION_ERROR,
            f"AIDP API request failed: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        _raise_aidp_http_error(e, "view-image")
    content_type = response.headers.get("Content-Type") or "image/png"
    return response.content, content_type.split(";")[0].strip()


def search_aidp_chunks_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    file_name: str,
    query: str,
    top_k: int = 20,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """Search chunks of one file through AIDP FusionSearch.

    This is a dedicated read path for the chunk search box. It deliberately
    does not call the ``aidp_search`` agent tool: the tool has its own
    model-facing response shaping, while this endpoint needs raw chunk hits
    for the current file only. The wire payload is built with the same SDK
    retrieval policy used by agents, then constrained with the documented
    ``metadata_condition.original_file_name`` filter. Only vector and
    full-text channels consume that filter, so graph retrieval is excluded.
    """
    normalized_file_name = file_name.strip()
    normalized_query = query.strip()
    if not normalized_file_name or not normalized_query:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "file_name and query are required")

    config = resolve_config({
        "search_method": "vector_search|full_text_search",
        "top_k": top_k,
        "hybrid_top_k": top_k,
        "vector_candidates": top_k,
        "full_text_candidates": top_k,
        "reranking_enable": False,
        "rewrite_enable": False,
        "query_expansion_enable": False,
        "related_search_enable": False,
        "multi_modal": True,
    })
    body = build_payload(config, normalized_query, [str(kds_id)])
    body["metadata_condition"] = {
        "logical_operator": "or",
        "conditions": [
            {
                "name": "original_file_name",
                # Real AIDP (verified 2026-11-18) rejects "=" on string fields
                # with 400 code 1002; allowed operators are contains / is /
                # in / start with. "contains" matches the file-name filter
                # semantics here because the defensive title check below
                # pins the hit to the requested file.
                "comparison_operator": "contains",
                "value": normalized_file_name,
            }
        ],
    }

    result = _request_aidp_json(
        server_url,
        api_key,
        "POST",
        _get_retrieval_path(tenant_id),
        context="chunk search",
        json_body=body,
    )
    records = result.get("result") if isinstance(result, dict) else None
    if not isinstance(records, list):
        raise AppException(
            ErrorCode.AIDP_RESPONSE_ERROR,
            "Unexpected AIDP chunk search response format",
        )

    chunks: List[Dict[str, Any]] = []
    wanted_stem = _file_name_stem(normalized_file_name)
    for hit in records:
        if not isinstance(hit, dict):
            continue
        title = hit.get("title")
        if isinstance(title, str) and title.strip():
            # Defensive check: the upstream filter is authoritative, but do not
            # surface a different file if it is ignored or unavailable. Compare
            # name stems because AIDP titles carry the extension while the
            # Nexent file list drops it.
            if _file_name_stem(title) != wanted_stem:
                continue
        chunk_id = _normalize_chunk_id(hit.get("id"))
        if not isinstance(chunk_id, int) or chunk_id < 0:
            continue
        raw_pages = hit.get("pages", hit.get("page_ids"))
        pages = []
        if isinstance(raw_pages, list):
            normalized_pages = [_normalize_chunk_id(page) for page in raw_pages]
            pages = [
                page
                for page in normalized_pages
                if isinstance(page, int) and not isinstance(page, bool)
            ]
        metadata = hit.get("metadata")
        raw_tags = hit.get("tag")
        # Ontology auto-tagging only exists on newer AIDP builds; pass the
        # list through when present and keep it absent otherwise.
        tags = [
            str(tag).strip()
            for tag in raw_tags
            if isinstance(tag, str) and tag.strip()
        ] if isinstance(raw_tags, list) else []
        chunk = {
            "chunk_id": chunk_id,
            "chunk_text": str(hit.get("text") or hit.get("chunk_text") or ""),
            "chunk_type": str(hit.get("chunk_type") or "TEXT").upper(),
            "file_name": str(title or normalized_file_name),
            "file_url": str(hit.get("file_url") or ""),
            "page_ids": pages,
            "metadata": {
                key: value
                for key, value in (metadata if isinstance(metadata, dict) else {}).items()
                if not key.startswith("_")
            },
            "metadata_json": hit.get("metadata_json") or {},
            "score": hit.get("score"),
        }
        if tags:
            chunk["tag"] = tags
        chunks.append(chunk)

    return {
        "value": chunks,
        "total_count": len(chunks),
        "has_more": False,
        "total_reliable": True,
    }

