"""Network destination policy for NL2AGENT remote MCP installation."""

import ipaddress
import socket
from typing import Any, Callable
from urllib.parse import urlparse

from consts.const import NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS
from consts.exceptions import Nl2AgentValidationError


AddressResolver = Callable[..., list[Any]]


def validate_remote_mcp_url(
    url: str,
    *,
    allow_private_networks: bool = NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS,
    resolver: AddressResolver = socket.getaddrinfo,
) -> str:
    """Reject URLs that can directly address non-public networks."""
    normalized = str(url).strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise Nl2AgentValidationError(
            "MCP server URL must be HTTP or HTTPS and must not contain credentials."
        )
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise Nl2AgentValidationError("MCP server URL contains an invalid port.") from exc
    if allow_private_networks:
        return normalized
    try:
        address_info = resolver(
            parsed.hostname,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise Nl2AgentValidationError(
            "MCP server hostname could not be resolved safely."
        ) from exc
    if not address_info:
        raise Nl2AgentValidationError(
            "MCP server hostname could not be resolved safely."
        )
    for entry in address_info:
        try:
            address = ipaddress.ip_address(entry[4][0])
        except (IndexError, TypeError, ValueError) as exc:
            raise Nl2AgentValidationError(
                "MCP server hostname returned an invalid network address."
            ) from exc
        if not address.is_global:
            raise Nl2AgentValidationError(
                "MCP server URL resolves to a private or non-public network."
            )
    return normalized
