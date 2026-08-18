"""Small SSRF checks for request-supplied outbound URLs."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeOutboundURLError(ValueError):
    """Raised when an outbound URL may target a non-public network address."""


async def validate_public_url(
    url: str,
    allowed_schemes: tuple[str, ...] = ("http", "https"),
) -> None:
    """Require a URL whose hostname resolves only to public IP addresses."""
    if not isinstance(url, str) or not url.strip():
        raise UnsafeOutboundURLError("URL is required")

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeOutboundURLError("Invalid URL") from exc

    if parsed.scheme.lower() not in allowed_schemes or not parsed.hostname:
        raise UnsafeOutboundURLError("Only public HTTP(S) URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeOutboundURLError("URLs containing credentials are not allowed")
    if any(ord(character) < 32 for character in url):
        raise UnsafeOutboundURLError("Invalid URL")

    hostname = parsed.hostname.rstrip(".")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            resolved = await loop.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise UnsafeOutboundURLError("URL hostname could not be resolved") from exc

        addresses = []
        for entry in resolved:
            try:
                addresses.append(ipaddress.ip_address(entry[4][0]))
            except ValueError as exc:
                raise UnsafeOutboundURLError("URL hostname resolved to an invalid address") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise UnsafeOutboundURLError("URL must resolve only to public network addresses")
