"""Security policy tests for NL2AGENT remote MCP destinations."""

import socket

import pytest

from consts.exceptions import Nl2AgentValidationError
from services.nl2agent_mcp_url_security import validate_remote_mcp_url


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
        validate_remote_mcp_url(url, resolver=_resolver(url.split("//", 1)[1].split("/", 1)[0].strip("[]")))


def test_mixed_public_and_private_dns_answers_are_rejected():
    with pytest.raises(Nl2AgentValidationError, match="non-public"):
        validate_remote_mcp_url(
            "https://mcp.example/service",
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
            resolver=failed_resolver,
        )
