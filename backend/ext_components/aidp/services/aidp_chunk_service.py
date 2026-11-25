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
    _aidp_headers,
    _get_batch_metadata_path,
    _get_chunks_path,
    _get_retrieval_path,
    _get_tags_sync_path,
    _get_view_image_path,
    _raise_aidp_http_error,
    _request_aidp_json,
    _validate_params,
)


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


def _normalize_aidp_chunk(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the chunk id type the frontend addresses chunks with."""
    out = dict(raw)
    if "chunk_id" in out:
        out["chunk_id"] = _normalize_chunk_id(out["chunk_id"])
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
    result["value"] = [
        _normalize_aidp_chunk(item) for item in result["value"]
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
    return result


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
    headers = _aidp_headers(api_key, content_type=False)
    try:
        client = aidp_client.http_client_manager.get_sync_client(
            base_url=normalized_url,
            timeout=_AIDP_READ_TIMEOUT_SECONDS,
            verify_ssl=False,
        )
        response = client.get(url, headers=headers)
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
                # with 400 code 1002; "contains" is the allowed file-name filter.
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
    records = result["result"]

    chunks: List[Dict[str, Any]] = []
    for hit in records:
        chunks.append(
            {
                # The request is already scoped to the current KB and file by
                # ``kds_list`` and ``metadata_condition``; map the fixed
                # FusionSearch fields without re-filtering the response.
                "chunk_id": hit["id"],
                "chunk_text": hit["text"],
                "chunk_type": hit["chunk_type"].upper(),
                "file_name": hit["title"],
                "file_url": hit["file_url"],
                "page_ids": hit["pages"],
                "metadata": {
                    key: value
                    for key, value in hit["metadata"].items()
                    if not key.startswith("_")
                },
                "score": hit["score"],
            }
        )

    return {
        "value": chunks,
        "total_count": len(chunks),
        "has_more": False,
        "total_reliable": True,
    }


def update_chunk_metadata_impl(
    server_url: str,
    api_key: str,
    kds_id: str,
    *,
    od_id: int,
    metadata_json: Dict[str, Any],
    tag: List[str] | None = None,
    chunk_id_list: List[int] | None = None,
    file_uuid_list: List[str] | None = None,
    async_mode: bool = False,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """Batch-apply user metadata to chunks of one knowledge base.

    AIDP requires a non-empty ``metadata_json`` (verified 2026-11-20) and
    silently ignores a ``tag`` parameter, so only user metadata is forwarded.
    The sync route caps ``chunk_id_list`` at 300 ids; ``file_uuid_list`` stays
    capped at 100 on both variants; the async variant lifts the chunk-id cap
    and answers with an acceptance snapshot instead of per-chunk counts.
    """
    body: Dict[str, Any] = {"od_id": od_id, "metadata_json": metadata_json}
    if tag is not None:
        body["tag"] = list(tag)
    if chunk_id_list is not None:
        body["chunk_id_list"] = list(chunk_id_list)
    if file_uuid_list is not None:
        body["file_uuid_list"] = list(file_uuid_list)
    return _request_aidp_json(
        server_url,
        api_key,
        "PATCH",
        _get_batch_metadata_path(
            kds_id, async_mode=async_mode, tenant_id=tenant_id
        ),
        context="batch-chunk-metadata",
        json_body=body,
        retry=False,
    )


def sync_chunk_tags_impl(
    server_url: str,
    api_key: str,
    kb_ids: List[int],
    *,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """Trigger AIDP's incremental auto-tagging for the given knowledge bases.

    The upstream envelope is ``{code, data:{task_id}, message}`` unlike the
    bare payloads of most endpoints, so the proxy normalizes it to a task
    snapshot. Tags themselves arrive later on chunk reads; this call only
    queues the task.
    """
    payload = _request_aidp_json(
        server_url,
        api_key,
        "POST",
        _get_tags_sync_path(tenant_id),
        context="sync-chunk-tags",
        json_body={"kb_ids": list(kb_ids)},
        retry=False,
    )
    result: Dict[str, Any] = {"task_id": payload["data"]["task_id"]}
    if payload.get("message"):
        result["message"] = payload["message"]
    return result
