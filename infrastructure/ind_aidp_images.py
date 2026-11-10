# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Image reference format shared by the independent AIDP runner and proxy."""

import base64
import hashlib
import hmac
import json
from typing import Any, Callable, Dict
from urllib.parse import unquote, urlparse

from contracts.constants import environment
from contracts.constants.environment import IND_AIDP_IMAGE_SIGNING_KEY

_IMAGE_PATH_PREFIX = "/KnowledgeBase/Tenants/"


class IndependentAidpServiceError(RuntimeError):
    """Raised when the independent AIDP connector cannot complete an operation."""


def _validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id is required")
    normalized = tenant_id.strip()
    if any(char in normalized for char in ("/", "\\", "?", "#")):
        raise ValueError("tenant_id contains invalid path characters")
    return normalized


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


def ind_aidp_skill_revision(
    agent_id: int, version_no: int, tenant_id: str, tool_id: int, skill_instance_ids: list[int], params: dict,
) -> str:
    payload = json.dumps(
        [agent_id, version_no, tenant_id, tool_id, sorted(skill_instance_ids), params],
        separators=(",", ":"), sort_keys=True,
    )
    if not environment.JWT_SECRET:
        raise IndependentAidpServiceError("AgentOS signing is not configured")
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/agentos/ind-aidp-skill-image/v1", "sha256")
    return hmac.digest(key, payload.encode(), "sha256").hex()


def create_ind_aidp_image_url_builder(
    *,
    agent_id: int,
    tool_id: int,
    tenant_id: str,
    version_no: int,
    aidp_tenant_id: str,
    skill_revision: str | None = None,
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
        if skill_revision is not None:
            payload["skill_revision"] = skill_revision
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
