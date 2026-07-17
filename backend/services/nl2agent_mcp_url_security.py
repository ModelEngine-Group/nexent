"""Network destination policy for NL2AGENT remote MCP installation."""

import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import httpcore
import httpx

from consts.const import NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS
from consts.exceptions import Nl2AgentValidationError


AddressResolver = Callable[..., list[Any]]


@dataclass(frozen=True)
class ResolvedMcpTarget:
    """One validated hostname and the addresses allowed for its connection."""

    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def _parse_remote_mcp_url(url: str) -> tuple[str, str, int]:
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
    try:
        hostname = str(ipaddress.ip_address(parsed.hostname))
    except ValueError:
        try:
            hostname = parsed.hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise Nl2AgentValidationError(
                "MCP server URL contains an invalid hostname."
            ) from exc
    return normalized, hostname, port


def resolve_remote_mcp_target(
    url: str,
    *,
    allow_private_networks: bool = NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS,
    resolver: AddressResolver = socket.getaddrinfo,
) -> ResolvedMcpTarget:
    """Resolve and validate the exact addresses an MCP connection may use."""
    normalized, hostname, port = _parse_remote_mcp_url(url)
    try:
        address_info = resolver(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError as exc:
        raise Nl2AgentValidationError(
            "MCP server hostname could not be resolved safely."
        ) from exc
    if not address_info:
        raise Nl2AgentValidationError(
            "MCP server hostname could not be resolved safely."
        )

    addresses: list[str] = []
    for entry in address_info:
        try:
            address = ipaddress.ip_address(entry[4][0])
        except (IndexError, TypeError, ValueError) as exc:
            raise Nl2AgentValidationError(
                "MCP server hostname returned an invalid network address."
            ) from exc
        if not allow_private_networks and not address.is_global:
            raise Nl2AgentValidationError(
                "MCP server URL resolves to a private or non-public network."
            )
        canonical = str(address)
        if canonical not in addresses:
            addresses.append(canonical)
    return ResolvedMcpTarget(normalized, hostname, port, tuple(addresses))


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect an original HTTP origin only through its validated addresses."""

    def __init__(self, target: ResolvedMcpTarget):
        self._target = target
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        requested_host = host.decode("ascii") if isinstance(host, bytes) else str(host)
        if requested_host.casefold() != self._target.hostname.casefold() or port != self._target.port:
            raise OSError("MCP redirect target is outside the validated network destination.")
        last_error: OSError | None = None
        for address in self._target.addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except OSError as exc:
                last_error = exc
        raise last_error or OSError("MCP server has no validated network address.")

    async def connect_unix_socket(self, *args, **kwargs):
        raise OSError("Unix sockets are not allowed for remote MCP connections.")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedAsyncHttpTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport that preserves Host/SNI while replacing DNS resolution."""

    def __init__(self, target: ResolvedMcpTarget):
        super().__init__(verify=True, trust_env=False)
        ssl_context = ssl.create_default_context()
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            network_backend=_PinnedNetworkBackend(target),
        )


def build_pinned_httpx_client_factory(
    url: str,
    *,
    allow_private_networks: bool = NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS,
    resolver: AddressResolver = socket.getaddrinfo,
) -> Callable[..., httpx.AsyncClient]:
    """Return an MCP client factory pinned to one validated DNS snapshot."""
    target = resolve_remote_mcp_target(
        url,
        allow_private_networks=allow_private_networks,
        resolver=resolver,
    )

    def create_client(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        follow_redirects: bool = True,
        **extra_kwargs,
    ) -> httpx.AsyncClient:
        for controlled_option in ("transport", "verify", "trust_env", "proxy"):
            extra_kwargs.pop(controlled_option, None)
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=follow_redirects,
            trust_env=False,
            transport=_PinnedAsyncHttpTransport(target),
            **extra_kwargs,
        )

    return create_client


def validate_remote_mcp_url(
    url: str,
    *,
    allow_private_networks: bool = NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS,
    resolver: AddressResolver = socket.getaddrinfo,
) -> str:
    """Reject URLs that can directly address non-public networks."""
    normalized, _, _ = _parse_remote_mcp_url(url)
    if allow_private_networks:
        return normalized
    return resolve_remote_mcp_target(
        normalized,
        allow_private_networks=False,
        resolver=resolver,
    ).url
