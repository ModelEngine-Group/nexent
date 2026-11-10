# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Services for the independently configured AIDP search connector."""

import logging
from typing import Any, Dict, Tuple
from urllib.parse import quote, urljoin, urlparse, urlunparse

import httpx

from infrastructure.ind_aidp_images import (
    IndependentAidpServiceError as IndependentAidpServiceError,
    _decode_image_ref,
    _normalize_image_path,
    _validate_tenant_id,
    create_ind_aidp_image_url_builder as create_ind_aidp_image_url_builder,
)
from management.db.tool.repository import query_tool_instances_by_id, query_tools_by_ids

logger = logging.getLogger("ind_aidp_service")

_IMAGE_CLASS_NAME = "IndependentAidpSearchTool"
_MAX_IMAGE_SIZE = 20 * 1024 * 1024


def _normalize_base_url(server_url: str) -> str:
    if not isinstance(server_url, str) or not server_url.strip():
        raise ValueError("server_url is required")
    normalized = server_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("server_url must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("server_url cannot contain credentials, query parameters, or a fragment")
    return normalized


async def fetch_ind_aidp_knowledge_bases_impl(
    server_url: str,
    api_key: str,
    tenant_id: str = "aidp",
    page: int = 1,
    page_size: int = 100,
) -> Dict[str, Any]:
    """Return a page of knowledge bases using caller-supplied AIDP credentials."""
    base_url = _normalize_base_url(server_url)
    aidp_tenant_id = _validate_tenant_id(tenant_id)
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("api_key is required")
    list_url = urljoin(
        f"{base_url}/",
        f"KnowledgeBase/Tenants/{quote(aidp_tenant_id, safe='')}/KnowledgeBases",
    )
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=False,
            trust_env=False,
            verify=False,
        ) as client:
            response = await client.get(
                list_url,
                params={"page": page, "page_size": page_size},
                headers={"Authorization": f"Bearer {api_key.strip()}"},
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            raise IndependentAidpServiceError("AIDP authentication failed") from exc
        raise IndependentAidpServiceError(f"AIDP knowledge-base API returned HTTP {status}") from exc
    except httpx.RequestError as exc:
        raise IndependentAidpServiceError(f"AIDP connection failed: {exc}") from exc
    except ValueError as exc:
        raise IndependentAidpServiceError("AIDP knowledge-base API returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise IndependentAidpServiceError("AIDP knowledge-base response must be an object")
    return result


def _resolve_image_credentials(payload: Dict[str, Any]) -> Tuple[str, str, str, str]:
    instance = query_tool_instances_by_id(
        agent_id=int(payload["agent_id"]),
        tool_id=int(payload["tool_id"]),
        tenant_id=str(payload["tenant_id"]),
        version_no=int(payload["version_no"]),
    )
    definitions = query_tools_by_ids([int(payload["tool_id"])])
    if not instance or not definitions or definitions[0].get("class_name") != _IMAGE_CLASS_NAME:
        raise IndependentAidpServiceError("Independent AIDP tool instance is unavailable")
    params = instance.get("params") or {}
    base_url = _normalize_base_url(params.get("server_url"))
    api_key = params.get("api_key")
    aidp_tenant_id = _validate_tenant_id(params.get("tenant_id") or "aidp")
    if not isinstance(api_key, str) or not api_key.strip():
        raise IndependentAidpServiceError("Independent AIDP tool credential is unavailable")
    if aidp_tenant_id != str(payload["aidp_tenant_id"]):
        raise IndependentAidpServiceError("Independent AIDP image tenant no longer matches")
    image_path = _normalize_image_path(str(payload["image_path"]), aidp_tenant_id)
    return base_url, api_key.strip(), aidp_tenant_id, image_path


async def fetch_ind_aidp_image_impl(image_ref: str) -> Tuple[bytes, str]:
    """Fetch an image in real time with credentials loaded from the tool instance."""
    payload = _decode_image_ref(image_ref)
    base_url, api_key, aidp_tenant_id, image_path = _resolve_image_credentials(payload)
    base_parsed = urlparse(base_url)
    target_path = (
        f"/KnowledgeBase/Tenants/{quote(aidp_tenant_id, safe='')}/"
        f"KnowledgeBases/{quote(image_path, safe='/')}"
    )
    target_url = urlunparse((base_parsed.scheme, base_parsed.netloc, target_path, "", "", ""))
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
            trust_env=False,
            verify=False,
        ) as client:
            response = await client.get(
                target_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
            if not content_type.startswith("image/"):
                raise IndependentAidpServiceError("AIDP image endpoint returned non-image content")
            if len(response.content) > _MAX_IMAGE_SIZE:
                raise IndependentAidpServiceError("AIDP image exceeds the 20 MB limit")
            return response.content, content_type
    except httpx.HTTPStatusError as exc:
        raise IndependentAidpServiceError(
            f"AIDP image endpoint returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise IndependentAidpServiceError(f"AIDP image request failed: {exc}") from exc
