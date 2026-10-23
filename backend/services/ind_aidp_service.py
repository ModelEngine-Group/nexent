"""Services for the independently configured AIDP search connector."""

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Callable, Dict, Tuple
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse

import httpx

from consts.const import IND_AIDP_IMAGE_SIGNING_KEY
from database.tool_db import query_tool_instances_by_id, query_tools_by_ids

logger = logging.getLogger("ind_aidp_service")

_IMAGE_CLASS_NAME = "IndependentAidpSearchTool"
_IMAGE_PATH_PREFIX = "/KnowledgeBase/Tenants/"
_MAX_IMAGE_SIZE = 20 * 1024 * 1024


class IndependentAidpServiceError(RuntimeError):
    """Raised when the independent AIDP connector cannot complete an operation."""


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


def _validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id is required")
    normalized = tenant_id.strip()
    if any(char in normalized for char in ("/", "\\", "?", "#")):
        raise ValueError("tenant_id contains invalid path characters")
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


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _sign(encoded_payload: str) -> str:
    if not IND_AIDP_IMAGE_SIGNING_KEY:
        raise IndependentAidpServiceError(
            "Independent AIDP image signing is not configured"
        )
    digest = hmac.new(
        IND_AIDP_IMAGE_SIGNING_KEY.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _b64encode(digest)


def _normalize_image_path(file_url: str, aidp_tenant_id: str) -> str:
    if not isinstance(file_url, str) or not file_url.strip():
        raise ValueError("AIDP image path is empty")
    raw = unquote(file_url.strip())
    parsed = urlparse(raw)
    if parsed.query or parsed.fragment:
        raise ValueError("AIDP image path cannot contain a query or fragment")
    path = parsed.path if parsed.scheme else raw
    prefix = f"{_IMAGE_PATH_PREFIX}{aidp_tenant_id}/KnowledgeBases/"
    if path.startswith(prefix):
        path = path[len(prefix):]
    path = path.lstrip("/")
    if not path or path == ".." or path.startswith("../") or "/../" in path:
        raise ValueError("AIDP image path is invalid")
    return path


def create_ind_aidp_image_url_builder(
    *,
    agent_id: int,
    tool_id: int,
    tenant_id: str,
    version_no: int,
    aidp_tenant_id: str,
) -> Callable[[str], str]:
    """Create a runtime callback that turns an AIDP path into a signed proxy URL."""
    normalized_aidp_tenant = _validate_tenant_id(aidp_tenant_id)

    def build(file_url: str) -> str:
        image_path = _normalize_image_path(file_url, normalized_aidp_tenant)
        payload = {
            "agent_id": int(agent_id),
            "tool_id": int(tool_id),
            "tenant_id": str(tenant_id),
            "version_no": int(version_no),
            "aidp_tenant_id": normalized_aidp_tenant,
            "image_path": image_path,
        }
        encoded_payload = _b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        image_ref = f"{encoded_payload}.{_sign(encoded_payload)}"
        return f"/api/ind-aidp/images/{image_ref}"

    return build


def _decode_image_ref(image_ref: str) -> Dict[str, Any]:
    try:
        encoded_payload, supplied_signature = image_ref.split(".", 1)
        if not hmac.compare_digest(_sign(encoded_payload), supplied_signature):
            raise ValueError("signature mismatch")
        payload = json.loads(_b64decode(encoded_payload))
    except Exception as exc:
        raise IndependentAidpServiceError("Invalid independent AIDP image reference") from exc
    required = {
        "agent_id", "tool_id", "tenant_id", "version_no", "aidp_tenant_id", "image_path"
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise IndependentAidpServiceError("Invalid independent AIDP image reference")
    return payload


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
