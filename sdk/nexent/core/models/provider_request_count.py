"""Runtime use of a previously verified Provider full-request count capability."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .final_request_budget import FinalRequestShape


COUNT_ADAPTER_VERSION = "1.0.0"
MAX_COUNT = 100_000_000
MAX_RESPONSE_BYTES = 64 * 1024


def endpoint_fingerprint(url: str) -> str:
    parsed = urlsplit(url)
    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower()
            + (f":{parsed.port}" if parsed.port else ""),
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:24]


def count_final_request(
    shape: FinalRequestShape,
    *,
    metadata: Optional[Mapping[str, Any]],
    base_url: str,
    api_key: str,
    model_name: str,
    canonical_model_id: str,
    ssl_verify: bool = True,
    timeout_seconds: float = 5.0,
) -> tuple[Optional[int], Optional[str]]:
    """Return a Provider count or a stable, non-mutating fallback reason."""
    reason = _capability_reason(
        shape,
        metadata=metadata,
        base_url=base_url,
        canonical_model_id=canonical_model_id,
    )
    if reason:
        return None, reason
    protocol = str((metadata or {}).get("selected_protocol"))
    if protocol != "openai_responses":
        return None, "runtime_count_protocol_not_implemented"

    count_url = f"{base_url.rstrip('/')}/responses/input_tokens"
    if urlsplit(count_url).netloc != urlsplit(base_url).netloc:
        return None, "count_origin_mismatch"
    semantic = shape.semantic_request
    body: dict[str, Any] = {
        "model": semantic.get("model") or model_name,
        "input": semantic.get("messages") or [],
    }
    if semantic.get("tools"):
        body["tools"] = semantic["tools"]
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 3.0)),
            follow_redirects=False,
            trust_env=False,
            verify=ssl_verify,
        ) as client:
            response = client.post(
                count_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
    except httpx.TimeoutException:
        return None, "count_timeout"
    except httpx.RequestError:
        return None, "count_connection_failed"
    if 300 <= response.status_code < 400:
        return None, "count_redirect_rejected"
    if response.status_code in {401, 403}:
        return None, "count_authorization_failed"
    if response.status_code == 429:
        return None, "count_rate_limited"
    if response.status_code in {404, 405}:
        return None, "count_unsupported_endpoint"
    if response.status_code >= 500:
        return None, "count_provider_5xx"
    if not 200 <= response.status_code < 300:
        return None, "count_unexpected_status"
    if len(response.content) > MAX_RESPONSE_BYTES:
        return None, "count_response_too_large"
    try:
        payload = response.json()
    except ValueError:
        return None, "count_invalid_schema"
    count = payload.get("input_tokens") if isinstance(payload, Mapping) else None
    if not isinstance(count, int) or isinstance(count, bool) or not 0 < count <= MAX_COUNT:
        return None, "count_invalid_value"
    return count, None


def _capability_reason(
    shape: FinalRequestShape,
    *,
    metadata: Optional[Mapping[str, Any]],
    base_url: str,
    canonical_model_id: str,
) -> Optional[str]:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return "count_ssrf_rejected"
    if not metadata:
        return "count_capability_missing"
    if metadata.get("status") != "supported":
        return f"count_capability_{metadata.get('status') or 'unknown'}"
    if metadata.get("adapter_version") != COUNT_ADAPTER_VERSION:
        return "count_capability_stale_adapter"
    if metadata.get("endpoint_fingerprint") != endpoint_fingerprint(base_url):
        return "count_capability_endpoint_mismatch"
    if metadata.get("model_identity") != canonical_model_id:
        return "count_capability_model_mismatch"
    stale_at = metadata.get("stale_at")
    try:
        expiry = datetime.fromisoformat(str(stale_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "count_capability_stale"
    if expiry <= datetime.now(timezone.utc):
        return "count_capability_stale"
    capabilities = metadata.get("capabilities") or {}
    required = (
        ("tools", "media") if shape.request_shape == "tools_media" else
        ("tools",) if shape.request_shape == "tools" else
        ("media",) if shape.request_shape == "media" else
        ("text",)
    )
    if shape.reasoning_mode != "default":
        required = (*required, "reasoning")
    if any(capabilities.get(item) != "supported" for item in required):
        return "count_capability_shape_unsupported"
    return None
