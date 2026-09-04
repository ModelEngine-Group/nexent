"""Safe, explicit discovery of optional provider token-count endpoints."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx


PROBE_SCHEMA_VERSION = 1
PROBE_ADAPTER_VERSION = "1.0.0"
MAX_COUNT = 100_000_000
MAX_RESPONSE_BYTES = 64 * 1024
SUPPORTED_TTL = timedelta(days=7)
UNSUPPORTED_TTL = timedelta(days=1)
TEMPORARY_RETRY = timedelta(minutes=15)
PROBE_TEXT = "Nexent token count probe."
logger = logging.getLogger("model_token_count_probe_service")

ProbeState = str


@dataclass(frozen=True)
class ProbeHTTPRequest:
    protocol: str
    url: str
    headers: Mapping[str, str]
    body: Mapping[str, Any]


@dataclass(frozen=True)
class ProbeHTTPResponse:
    status_code: int
    payload: Optional[Mapping[str, Any]] = None
    redirect_location: Optional[str] = None


Transport = Callable[[ProbeHTTPRequest], Awaitable[ProbeHTTPResponse]]
Resolver = Callable[[str], Iterable[str]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _default_resolver(host: str) -> Iterable[str]:
    return {item[4][0] for item in socket.getaddrinfo(host, None)}


def validate_probe_url(
    url: str,
    *,
    allow_private: bool = False,
    resolver: Resolver = _default_resolver,
) -> str:
    """Validate and normalize a configured URL before credentials are attached."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("ssrf_rejected")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("ssrf_rejected")
    try:
        addresses = tuple(resolver(parsed.hostname))
    except (OSError, socket.gaierror) as exc:
        raise ValueError("connection_failed") from exc
    if not addresses:
        raise ValueError("connection_failed")
    if not allow_private:
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise ValueError("ssrf_rejected")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip("/"), "", ""))


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


def credential_scope_fingerprint(scope_identity: str, *, salt: str) -> str:
    """Hash non-secret tenant/scope identity; API-key material is never accepted."""
    return hashlib.sha256(f"{salt}:{scope_identity}".encode()).hexdigest()[:24]


def probe_fingerprint(
    *, endpoint: str, model_identity: str, credential_scope: str, adapter_version: str
) -> str:
    value = "\0".join((endpoint, model_identity, credential_scope, adapter_version))
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _join(base_url: str, suffix: str) -> str:
    return f"{base_url.rstrip('/')}/{suffix.lstrip('/')}"


def build_probe_request(
    protocol: str,
    *,
    base_url: str,
    model_name: str,
    api_key: str,
) -> ProbeHTTPRequest:
    if protocol == "openai_responses":
        return ProbeHTTPRequest(
            protocol=protocol,
            url=_join(base_url, "responses/input_tokens"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body={"model": model_name, "input": PROBE_TEXT},
        )
    if protocol == "anthropic_messages":
        return ProbeHTTPRequest(
            protocol=protocol,
            url=_join(base_url, "messages/count_tokens"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            body={"model": model_name, "messages": [{"role": "user", "content": PROBE_TEXT}]},
        )
    if protocol == "gemini":
        return ProbeHTTPRequest(
            protocol=protocol,
            url=_join(base_url, f"models/{model_name}:countTokens"),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            body={"contents": [{"parts": [{"text": PROBE_TEXT}]}]},
        )
    raise ValueError("unsupported_protocol")


def _extract_count(protocol: str, payload: Optional[Mapping[str, Any]]) -> Optional[int]:
    if not isinstance(payload, Mapping):
        return None
    if protocol in {"openai_responses", "anthropic_messages"}:
        value = payload.get("input_tokens")
    else:
        value = payload.get("totalTokens")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def classify_probe_response(
    protocol: str, response: ProbeHTTPResponse
) -> tuple[ProbeState, str, Optional[int]]:
    status = response.status_code
    if response.redirect_location is not None or 300 <= status < 400:
        return "temporarily_unavailable", "redirect_rejected", None
    if status in {404, 405}:
        return "unsupported", "unsupported_endpoint", None
    if status in {401, 403}:
        return "authorization_error", "authorization_failed", None
    if status == 429:
        return "temporarily_unavailable", "rate_limited", None
    if status >= 500:
        return "temporarily_unavailable", "provider_5xx", None
    if not 200 <= status < 300:
        return "temporarily_unavailable", "connection_failed", None
    count = _extract_count(protocol, response.payload)
    if count is None:
        return "invalid_response", "invalid_schema", None
    if count <= 0 or count > MAX_COUNT:
        return "invalid_response", "invalid_count", None
    return "supported", "supported", count


async def _httpx_transport(request: ProbeHTTPRequest) -> ProbeHTTPResponse:
    timeout = httpx.Timeout(5.0, connect=3.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.post(
                request.url, headers=dict(request.headers), json=dict(request.body)
            )
        location = response.headers.get("location") if 300 <= response.status_code < 400 else None
        if len(response.content) > MAX_RESPONSE_BYTES:
            return ProbeHTTPResponse(response.status_code, payload=None, redirect_location=location)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            payload = None
        return ProbeHTTPResponse(response.status_code, payload=payload, redirect_location=location)
    except httpx.TimeoutException as exc:
        raise TimeoutError("timeout") from exc
    except httpx.RequestError as exc:
        raise ConnectionError("connection_failed") from exc


def should_reuse_probe(
    existing: Optional[Mapping[str, Any]],
    *,
    current_fingerprint: str,
    now: datetime,
    force: bool,
) -> bool:
    if force or not existing or existing.get("fingerprint") != current_fingerprint:
        return False
    if existing.get("status") not in {"supported", "unsupported"}:
        return False
    stale_at = _parse_time(existing.get("stale_at"))
    return stale_at is not None and stale_at > now


async def run_token_count_probe(
    *,
    inference_protocol: str,
    base_url: str,
    model_name: str,
    canonical_model_id: str,
    api_key: str,
    credential_scope: str,
    fingerprint_salt: str,
    existing: Optional[Mapping[str, Any]] = None,
    force: bool = False,
    allow_private: bool = False,
    resolver: Resolver = _default_resolver,
    transport: Transport = _httpx_transport,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Run a directed/ordered explicit probe and return sanitized metadata."""
    checked_at = now or _utcnow()
    safe_base = validate_probe_url(
        base_url, allow_private=allow_private, resolver=resolver
    )
    endpoint_fp = endpoint_fingerprint(safe_base)
    scope_fp = credential_scope_fingerprint(credential_scope, salt=fingerprint_salt)
    fingerprint = probe_fingerprint(
        endpoint=endpoint_fp,
        model_identity=canonical_model_id,
        credential_scope=scope_fp,
        adapter_version=PROBE_ADAPTER_VERSION,
    )
    if should_reuse_probe(
        existing, current_fingerprint=fingerprint, now=checked_at, force=force
    ):
        return dict(existing or {})

    directed = {
        "openai": ("openai_responses",),
        "anthropic": ("anthropic_messages",),
        "gemini": ("gemini",),
    }
    protocols = directed.get(
        inference_protocol,
        ("openai_responses", "anthropic_messages", "gemini"),
    )
    outcomes: list[dict[str, Any]] = []
    selected: Optional[str] = None
    selected_count: Optional[int] = None
    for protocol in protocols:
        request = build_probe_request(
            protocol, base_url=safe_base, model_name=model_name, api_key=api_key
        )
        # Every derived target is checked and must remain on the configured origin.
        safe_target = validate_probe_url(
            request.url, allow_private=allow_private, resolver=resolver
        )
        if urlsplit(safe_target).netloc != urlsplit(safe_base).netloc:
            state, reason, count = "temporarily_unavailable", "redirect_rejected", None
        else:
            try:
                response = await transport(request)
                state, reason, count = classify_probe_response(protocol, response)
            except TimeoutError:
                state, reason, count = "temporarily_unavailable", "timeout", None
            except ConnectionError:
                state, reason, count = "temporarily_unavailable", "connection_failed", None
        outcomes.append({"protocol": protocol, "state": state, "reason": reason})
        if state == "supported" and selected is None:
            selected, selected_count = protocol, count
        # Unknown protocols are ordered discovery: retain prior failures and
        # stop after the first valid dialect to avoid unnecessary credential use.
        if selected is not None and inference_protocol not in directed:
            break

    if selected is not None:
        status, reason = "supported", "supported"
        stale_at = checked_at + SUPPORTED_TTL
        retry_at = None
    elif outcomes and all(item["state"] == "unsupported" for item in outcomes):
        status, reason = "unsupported", "unsupported_endpoint"
        stale_at = checked_at + UNSUPPORTED_TTL
        retry_at = None
    else:
        last = outcomes[-1] if outcomes else {"state": "unknown", "reason": "unknown"}
        status, reason = last["state"], last["reason"]
        stale_at = checked_at
        retry_at = checked_at + TEMPORARY_RETRY if status == "temporarily_unavailable" else None

    metadata = {
        "schema_version": PROBE_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "selected_protocol": selected,
        "capabilities": {
            "text": "supported" if selected else status,
            "tools": "unknown",
            "media": "unknown",
        },
        **({"probe_token_count": selected_count} if selected_count is not None else {}),
        "outcomes": outcomes,
        "checked_at": _iso(checked_at),
        "stale_at": _iso(stale_at),
        **({"retry_at": _iso(retry_at)} if retry_at else {}),
        "adapter_version": PROBE_ADAPTER_VERSION,
        "endpoint_fingerprint": endpoint_fp,
        "model_identity": canonical_model_id,
        "credential_scope_fingerprint": scope_fp,
        "fingerprint": fingerprint,
    }
    logger.info(
        "token_count_probe protocol=%s state=%s reason=%s endpoint_fingerprint=%s model_identity=%s adapter_version=%s",
        selected or inference_protocol,
        status,
        reason,
        endpoint_fp,
        canonical_model_id,
        PROBE_ADAPTER_VERSION,
    )
    return metadata
