"""Security policy tests for NL2AGENT remote MCP destinations."""

import socket
import ssl
from unittest.mock import AsyncMock

import pytest

from consts.exceptions import Nl2AgentValidationError
from services.nl2agent_mcp_url_security import (
    _PinnedNetworkBackend,
    build_pinned_httpx_client_factory,
    resolve_remote_mcp_target,
    validate_remote_mcp_url,
)


def _resolver(*addresses):
    return lambda *_args: [
        (socket.AF_INET6 if ":" in address else socket.AF_INET, 0, 0, "", (address, 443))
        for address in addresses
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/mcp",
        "http://10.0.0.5/mcp",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/mcp",
    ],
)
def test_private_and_metadata_destinations_are_rejected(url):
    with pytest.raises(Nl2AgentValidationError, match="non-public"):
        validate_remote_mcp_url(
            url,
            allow_private_networks=False,
            resolver=_resolver(url.split("//", 1)[1].split("/", 1)[0].strip("[]")),
        )


def test_mixed_public_and_private_dns_answers_are_rejected():
    with pytest.raises(Nl2AgentValidationError, match="non-public"):
        validate_remote_mcp_url(
            "https://mcp.example/service",
            allow_private_networks=False,
            resolver=_resolver("93.184.216.34", "10.0.0.5"),
        )


def test_public_dns_answers_and_explicit_private_opt_in_are_supported():
    assert validate_remote_mcp_url(
        "https://mcp.example/service",
        resolver=_resolver("93.184.216.34"),
    ) == "https://mcp.example/service"
    assert validate_remote_mcp_url(
        "http://localhost/mcp",
        allow_private_networks=True,
        resolver=lambda *_args: (_ for _ in ()).throw(AssertionError()),
    ) == "http://localhost/mcp"


def test_credentials_and_dns_failures_are_rejected():
    with pytest.raises(Nl2AgentValidationError, match="must not contain credentials"):
        validate_remote_mcp_url("https://user:password@mcp.example/service")

    def failed_resolver(*_args):
        raise socket.gaierror("not found")

    with pytest.raises(Nl2AgentValidationError, match="resolved safely"):
        validate_remote_mcp_url(
            "https://missing.example/service",
            allow_private_networks=False,
            resolver=failed_resolver,
        )


@pytest.mark.asyncio
async def test_connection_uses_validated_address_without_resolving_hostname_again():
    target = resolve_remote_mcp_target(
        "https://mcp.example/service",
        resolver=_resolver("93.184.216.34"),
    )
    backend = _PinnedNetworkBackend(target)
    stream = object()
    backend._backend.connect_tcp = AsyncMock(return_value=stream)

    assert await backend.connect_tcp("mcp.example", 443) is stream
    backend._backend.connect_tcp.assert_awaited_once_with(
        "93.184.216.34",
        443,
        timeout=None,
        local_address=None,
        socket_options=None,
    )


@pytest.mark.asyncio
async def test_redirect_to_unvalidated_origin_is_blocked():
    target = resolve_remote_mcp_target(
        "https://mcp.example/service",
        resolver=_resolver("93.184.216.34"),
    )
    backend = _PinnedNetworkBackend(target)

    with pytest.raises(OSError, match="outside the validated"):
        await backend.connect_tcp("metadata.internal", 443)


@pytest.mark.asyncio
async def test_pinned_factory_resolves_even_when_private_networks_are_allowed():
    calls = []

    def resolver(*args):
        calls.append(args)
        return _resolver("10.0.0.5")(*args)

    factory = build_pinned_httpx_client_factory(
        "http://private.example/mcp",
        allow_private_networks=True,
        resolver=resolver,
    )
    client = factory()

    assert calls
    assert client._transport._pool._network_backend._target.addresses == (
        "10.0.0.5",
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_pinned_factory_preserves_tls_certificate_verification():
    factory = build_pinned_httpx_client_factory(
        "https://mcp.example/service",
        resolver=_resolver("93.184.216.34"),
    )
    client = factory()
    ssl_context = client._transport._pool._ssl_context

    assert ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert ssl_context.check_hostname is True
    await client.aclose()
