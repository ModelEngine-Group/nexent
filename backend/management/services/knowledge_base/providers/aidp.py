# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Services for the independently configured AIDP search connector."""

import logging
from hmac import compare_digest
from typing import Any, Dict, Tuple
from urllib.parse import quote, urljoin, urlparse, urlunparse

import httpx
from pydantic import ValidationError as PayloadValidationError

from contracts.agentos import WorkbenchSkillLookup

from contracts.errors.exceptions import ValidationError
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.ind_aidp_images import (
    IndependentAidpServiceError as IndependentAidpServiceError,
    _decode_image_ref,
    _normalize_image_path,
    _validate_tenant_id,
    create_ind_aidp_image_url_builder as create_ind_aidp_image_url_builder,
    ind_aidp_skill_revision,
    ind_aidp_workbench_revision,
)
from infrastructure.local_tool_execution import catalog_tool_parameters
from infrastructure.rdb.local_tool_records import read_skill_derived_local_tools
from infrastructure.rdb.workbench_skill_records import read_workbench_derived_tools, read_workbench_skill_rows
from management.db.conversation.prepared_turn import read_workbench_image_mounts
from management.db.tool.repository import query_tool_instances_by_id, query_tools_by_ids

from nexent.core.concurrency import run_blocking

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


def _read_skill_image_params(payload: dict) -> dict:
    scope = (int(payload["agent_id"]), int(payload["version_no"]), str(payload["tenant_id"]))
    tool_id = int(payload["tool_id"])
    try:
        matches = [
            row for row in read_skill_derived_local_tools(*scope, ["ind_aidp_search"])
            if row["tool_id"] == tool_id and row["class_name"] == _IMAGE_CLASS_NAME
        ]
    except ValidationError as exc:
        raise IndependentAidpServiceError("Independent AIDP skill tool changed") from exc
    if len(matches) != 1:
        raise IndependentAidpServiceError("Independent AIDP skill tool is unavailable")
    row = matches[0]
    params = catalog_tool_parameters(row)
    revision = ind_aidp_skill_revision(*scope, tool_id, row["skill_instance_ids"], params)
    supplied = payload["skill_revision"]
    if not isinstance(supplied, str) or not compare_digest(revision, supplied):
        raise IndependentAidpServiceError("Independent AIDP skill tool changed")
    return params


def _read_workbench_image_params(payload: dict, actor: ServicePrincipal | None) -> dict:
    if actor is None or actor.tenant_id != payload["tenant_id"]:
        raise IndependentAidpServiceError("Independent AIDP Workbench tool is unavailable")
    try:
        lookup = WorkbenchSkillLookup.model_validate(payload["workbench"])
        tool_id = int(payload["tool_id"])
        if (lookup.agent_id, lookup.agent_version) != (payload["agent_id"], payload["version_no"]):
            raise ValueError("Inconsistent Workbench image scope")
        mounts = read_workbench_image_mounts(lookup, actor.user_id, actor.tenant_id)
        if mounts is None:
            raise IndependentAidpServiceError("Independent AIDP Workbench tool is unavailable")
        rows = read_workbench_skill_rows(lookup.agent_id, lookup.agent_version, actor, mounts)
        tools = read_workbench_derived_tools(lookup.agent_id, lookup.agent_version, actor.tenant_id, list(rows.values()))
        matches = [row for row in tools if row["tool_id"] == tool_id and row["class_name"] == _IMAGE_CLASS_NAME]
    except (PayloadValidationError, ValidationError, TypeError, ValueError) as exc:
        raise IndependentAidpServiceError("Independent AIDP Workbench tool changed") from exc
    if len(matches) != 1:
        raise IndependentAidpServiceError("Independent AIDP Workbench tool is unavailable")
    row = matches[0]
    params = catalog_tool_parameters(row)
    revision = ind_aidp_workbench_revision(lookup, actor.tenant_id, tool_id, row["workbench_skill_ids"], params)
    supplied = payload.get("skill_revision")
    if not isinstance(supplied, str) or not compare_digest(revision, supplied):
        raise IndependentAidpServiceError("Independent AIDP Workbench tool changed")
    return params


def _read_image_instance_params(payload: dict) -> dict:
    instance = query_tool_instances_by_id(
        agent_id=int(payload["agent_id"]),
        tool_id=int(payload["tool_id"]),
        tenant_id=str(payload["tenant_id"]),
        version_no=int(payload["version_no"]),
    )
    definitions = query_tools_by_ids([int(payload["tool_id"])])
    if not instance or not definitions or definitions[0].get("class_name") != _IMAGE_CLASS_NAME:
        raise IndependentAidpServiceError("Independent AIDP tool instance is unavailable")
    return instance.get("params") or {}


def _resolve_image_credentials(
    payload: Dict[str, Any], actor: ServicePrincipal | None = None,
) -> Tuple[str, str, str, str]:
    if "workbench" in payload:
        params = _read_workbench_image_params(payload, actor)
    elif "skill_revision" in payload:
        params = _read_skill_image_params(payload)
    else:
        params = _read_image_instance_params(payload)
    base_url = _normalize_base_url(params.get("server_url"))
    api_key = params.get("api_key")
    aidp_tenant_id = _validate_tenant_id(params.get("tenant_id") or "aidp")
    if not isinstance(api_key, str) or not api_key.strip():
        raise IndependentAidpServiceError("Independent AIDP tool credential is unavailable")
    if aidp_tenant_id != str(payload["aidp_tenant_id"]):
        raise IndependentAidpServiceError("Independent AIDP image tenant no longer matches")
    image_path = _normalize_image_path(str(payload["image_path"]), aidp_tenant_id)
    return base_url, api_key.strip(), aidp_tenant_id, image_path


async def fetch_ind_aidp_image_impl(
    image_ref: str, actor: ServicePrincipal | None = None,
) -> Tuple[bytes, str, str]:
    """Fetch an image using currently authorized credentials and return its cache policy."""
    payload = _decode_image_ref(image_ref)
    base_url, api_key, aidp_tenant_id, image_path = await run_blocking(
        "independent-aidp-image-credentials", _resolve_image_credentials, payload, actor,
        lane="control-io", owner="management",
    )
    cache_control = "no-store" if "workbench" in payload else "private, max-age=3600"
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
            return response.content, content_type, cache_control
    except httpx.HTTPStatusError as exc:
        raise IndependentAidpServiceError(
            f"AIDP image endpoint returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise IndependentAidpServiceError(f"AIDP image request failed: {exc}") from exc
