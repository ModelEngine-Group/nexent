"""Generic OpenAI-compatible provider.

Used as the fallback for any provider that is not covered by a dedicated
implementation (silicon / modelengine / dashscope / tokenpony).  It simply
calls the standard ``GET {base_url}/models`` endpoint and returns the raw
model list annotated with the canonical fields expected downstream.
"""

import asyncio
import ipaddress
import logging
import socket
from typing import Dict, List
from urllib.parse import urlsplit

import httpx

from services.providers.base import (
    AbstractModelProvider,
    _classify_provider_error,
    _extract_capacity_hints_from_raw,
)

logger = logging.getLogger("model_provider")

# Documented local-LLM exemption: operators may point at a local
# OpenAI-compatible server. Loopback is not a cross-origin target.
_LOCAL_LLM_EXEMPT_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _reject_non_public_ip(ip) -> None:
    """Raise when an address belongs to a non-routable/reserved range."""
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError(
            "Provider base_url points to a private/reserved network host"
        )


def _validate_provider_base_url(base_url: str) -> str:
    """Reject URLs that must never be fetched server-side (SSRF guard).

    The base_url comes from operator-supplied provider configuration, so a
    crafted value could otherwise point the fetch at internal endpoints
    (cloud metadata, loopback services, link-local routers). Rules:
    - scheme must be http or https
    - a host must be present
    - loopback / link-local / private-network literal IPs are rejected. Local
      development against a local LLM is intentionally still allowed for
      127.0.0.1/localhost via the documented exemption below.

    Returns the lower-cased hostname for follow-up DNS resolution checks.
    """
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported provider base_url scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("Provider base_url has no host")

    host = parsed.hostname.lower()
    if host in _LOCAL_LLM_EXEMPT_HOSTS:
        return host

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host  # plain DNS name — resolved and checked separately

    _reject_non_public_ip(ip)
    return host


def _resolve_host_ips(host: str) -> List[str]:
    """Resolve a hostname to its literal IP addresses (blocking)."""
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


async def _assert_resolved_ips_public(host: str) -> None:
    """Resolve the DNS name and reject any non-public resolved address.

    The hostname-string checks in _validate_provider_base_url cannot see what
    a DNS name resolves to, so a domain pointing at a cloud-metadata endpoint
    or an internal 10.x service would otherwise slip through. Resolving here
    and validating every returned address closes that path. The residual
    time-of-check/time-of-use window (DNS rebinding) is an accepted trade-off:
    fully closing it would require pinning the resolved IP into the transport,
    which httpx does not support.
    """
    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.run_in_executor(None, _resolve_host_ips, host)
    except socket.gaierror as exc:
        raise ValueError(
            f"Provider base_url host cannot be resolved: {host}"
        ) from exc
    for address in addresses:
        _reject_non_public_ip(ipaddress.ip_address(address))


class OpenAICompatibleProvider(AbstractModelProvider):
    """Fetch models from any OpenAI-compatible ``/v1/models`` endpoint."""

    async def get_models(self, provider_config: Dict) -> List[Dict]:
        try:
            model_api_key: str = provider_config["api_key"]
            base_url: str = provider_config.get("base_url", "") or ""
            # TLS verification is on by default. Operators pointing at a
            # self-signed internal endpoint can opt out explicitly through
            # the ssl_verify flag instead of silently disabling it for
            # everyone.
            ssl_verify: bool = provider_config.get("ssl_verify", True)

            # SSRF guard: reject schemes without a host, non-routable literal
            # IPs, and DNS names that resolve into private/reserved ranges
            # before the operator-supplied URL is fetched.
            host = _validate_provider_base_url(base_url)
            if host not in _LOCAL_LLM_EXEMPT_HOSTS:
                await _assert_resolved_ips_public(host)

            # Normalise the base URL: strip trailing slashes, ensure it ends
            # with the ``/models`` path.
            url = base_url.rstrip("/")
            if not url.endswith("/models"):
                url = f"{url}/models"

            headers = {"Authorization": f"Bearer {model_api_key}"}

            async with httpx.AsyncClient(verify=ssl_verify, timeout=30) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()

            raw_list: List[Dict] = payload.get("data", [])
            if not isinstance(raw_list, list):
                raw_list = []

            # Annotate each model with canonical fields. model_type is left
            # empty here — the caller (create_provider_models_for_tenant)
            # infers it from the model name when model_type is not specified.
            model_list: List[Dict] = []
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id", "")).strip()
                if not model_id:
                    continue
                annotated = {
                    "id": model_id,
                    "model_tag": "chat",
                }
                # Merge capacity hints if the provider included any.
                hints = _extract_capacity_hints_from_raw(item)
                annotated.update(hints)
                model_list.append(annotated)

            return model_list

        except (httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError, Exception) as e:
            if isinstance(e, httpx.HTTPStatusError):
                status_code = e.response.status_code
                error_message = str(e)
                return _classify_provider_error(
                    "OpenAI-compatible", status_code=status_code, error_message=error_message
                )
            return _classify_provider_error(
                "OpenAI-compatible", exception=e
            )
