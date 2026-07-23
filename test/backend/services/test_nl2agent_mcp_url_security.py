"""Security policy tests for NL2AGENT remote MCP destinations."""

import socket
import ssl
from unittest.mock import AsyncMock

import httpx
import pytest

from consts.exceptions import Nl2AgentValidationError
from services import nl2agent_mcp_url_security as security
from services.nl2agent_mcp_url_security import (
    _PinnedAsyncHttpTransport,
    _PinnedNetworkBackend,
    build_pinned_httpx_client_factory,
    resolve_remote_mcp_target,
    validate_remote_mcp_url,
)


def _resolver(*addresses):
    def resolve(_hostname, port, *_args):
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                0,
                "",
                (address, port),
            )
            for address in addresses
        ]

    return resolve


@pytest.mark.parametrize(
    "url, message",
    [
        ("http://127.0.0.1/mcp", "restricted"),
        ("http://[::1]/mcp", "restricted"),
        ("http://169.254.1.1/mcp", "restricted"),
        ("http://169.254.169.254/latest/meta-data", "metadata"),
        ("http://169.254.170.2/credentials", "metadata"),
        ("http://[fd00:ec2::254]/mcp", "metadata"),
        ("http://0.0.0.0/mcp", "restricted"),
        ("http://224.0.0.1/mcp", "restricted"),
    ],
)
def test_dangerous_destinations_are_always_rejected(url, message):
    with pytest.raises(Nl2AgentValidationError, match=message):
        validate_remote_mcp_url(url, allow_private_networks=True)


@pytest.mark.parametrize(
    "address", ["10.0.0.5", "172.16.0.5", "192.168.1.5", "fd12::5"]
)
def test_private_destinations_are_allowed_by_default(address):
    assert (
        validate_remote_mcp_url(
            "https://mcp.internal/service",
            resolver=_resolver(address),
        )
        == "https://mcp.internal/service"
    )


@pytest.mark.parametrize(
    "address", ["10.0.0.5", "172.16.0.5", "192.168.1.5", "fd12::5"]
)
def test_explicit_public_only_policy_rejects_private_destinations(address):
    with pytest.raises(Nl2AgentValidationError, match="non-public"):
        validate_remote_mcp_url(
            "https://mcp.internal/service",
            allow_private_networks=False,
            resolver=_resolver(address),
        )


def test_environment_policy_false_rejects_private_destinations(monkeypatch):
    monkeypatch.setattr(security, "NL2AGENT_ALLOW_PRIVATE_MCP_NETWORKS", False)

    with pytest.raises(Nl2AgentValidationError, match="non-public"):
        validate_remote_mcp_url(
            "https://mcp.internal/service",
            resolver=_resolver("10.0.0.5"),
        )


def test_mixed_public_and_private_dns_answers_are_rejected_in_public_only_mode():
    with pytest.raises(Nl2AgentValidationError, match="non-public"):
        validate_remote_mcp_url(
            "https://mcp.example/service",
            allow_private_networks=False,
            resolver=_resolver("93.184.216.34", "10.0.0.5"),
        )


def test_public_dns_answers_are_supported():
    assert (
        validate_remote_mcp_url(
            "https://mcp.example/service",
            allow_private_networks=False,
            resolver=_resolver("93.184.216.34"),
        )
        == "https://mcp.example/service"
    )


@pytest.mark.parametrize(
    "url, message",
    [
        ("https://user:password@mcp.example/service", "must not contain credentials"),
        ("ftp://mcp.example/service", "must be HTTP or HTTPS"),
        ("http://mcp.example:0/service", "invalid port"),
        ("http://mcp.example:70000/service", "invalid port"),
    ],
)
def test_invalid_url_shapes_are_rejected(url, message):
    with pytest.raises(Nl2AgentValidationError, match=message):
        validate_remote_mcp_url(url, resolver=_resolver("93.184.216.34"))


def test_dns_failures_are_rejected():
    def failed_resolver(*_args):
        raise socket.gaierror("not found")

    with pytest.raises(Nl2AgentValidationError, match="resolved safely"):
        validate_remote_mcp_url(
            "https://missing.example/service",
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
async def test_pinned_backend_rejects_an_unvalidated_origin():
    target = resolve_remote_mcp_target(
        "https://mcp.example/service",
        resolver=_resolver("93.184.216.34"),
    )
    backend = _PinnedNetworkBackend(target)

    with pytest.raises(OSError, match="outside the validated"):
        await backend.connect_tcp("metadata.internal", 443)


@pytest.mark.asyncio
async def test_initial_connection_revalidates_dns_to_prevent_rebinding():
    answers = iter(("93.184.216.34", "10.0.0.5"))

    def rebinding_resolver(*args):
        return _resolver(next(answers))(*args)

    factory = build_pinned_httpx_client_factory(
        "https://mcp.example/service",
        allow_private_networks=False,
        resolver=rebinding_resolver,
    )
    client = factory()
    try:
        with pytest.raises(Nl2AgentValidationError, match="non-public"):
            await client.get("https://mcp.example/service")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redirect_target_is_resolved_and_rejected(monkeypatch):
    targets = []

    class RedirectingPinnedTransport:
        def __init__(self, target):
            targets.append(target)

        async def handle_async_request(self, request):
            return httpx.Response(
                302,
                headers={"location": "http://169.254.169.254/latest/meta-data"},
                request=request,
            )

        async def aclose(self):
            return None

    monkeypatch.setattr(
        security, "_PinnedAsyncHttpTransport", RedirectingPinnedTransport
    )
    factory = build_pinned_httpx_client_factory(
        "https://mcp.example/service",
        resolver=_resolver("93.184.216.34"),
    )
    client = factory(follow_redirects=True)
    try:
        with pytest.raises(Nl2AgentValidationError, match="metadata"):
            await client.get("https://mcp.example/service")
    finally:
        await client.aclose()

    assert [target.hostname for target in targets] == ["mcp.example"]


@pytest.mark.asyncio
async def test_pinned_factory_resolves_private_addresses_when_allowed():
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
    assert isinstance(client._transport, security._ValidatingAsyncHttpTransport)
    await client.aclose()


@pytest.mark.asyncio
async def test_pinned_transport_preserves_tls_certificate_verification():
    target = resolve_remote_mcp_target(
        "https://mcp.example/service",
        resolver=_resolver("93.184.216.34"),
    )
    transport = _PinnedAsyncHttpTransport(target)
    ssl_context = transport._pool._ssl_context

    assert ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert ssl_context.check_hostname is True
    await transport.aclose()
