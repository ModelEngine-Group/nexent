import asyncio
import socket
from unittest.mock import AsyncMock

import pytest

from backend.utils.ssrf_utils import UnsafeOutboundURLError, validate_public_url


def test_validate_public_url_accepts_public_ip():
    safe_url = asyncio.run(validate_public_url("HTTPS://8.8.8.8/image.png#fragment"))
    assert safe_url == "https://8.8.8.8/image.png"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/v1",
        "http://10.0.0.1:8000/v1",
        "http://172.19.0.11:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_validate_public_url_accepts_local_model_networks_when_enabled(url):
    asyncio.run(validate_public_url(url, allow_local_networks=True))


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://[fe80::1]/v1",
        "http://0.0.0.0:8000/v1",
    ],
)
def test_validate_public_url_still_rejects_special_addresses_when_local_networks_enabled(url):
    with pytest.raises(UnsafeOutboundURLError):
        asyncio.run(validate_public_url(url, allow_local_networks=True))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/image.png",
        "http://10.0.0.1/image.png",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/image.png",
        "file:///etc/passwd",
        "http://user:password@8.8.8.8/image.png",
    ],
)
def test_validate_public_url_rejects_unsafe_targets(url):
    with pytest.raises(UnsafeOutboundURLError):
        asyncio.run(validate_public_url(url))


@pytest.mark.parametrize("url", [None, "", "   ", "http://example.com\n/unsafe"])
def test_validate_public_url_rejects_missing_or_control_character_urls(url):
    with pytest.raises(UnsafeOutboundURLError):
        asyncio.run(validate_public_url(url))


@pytest.mark.parametrize(
    "url",
    ["http://example.com:bad/path", "http://example.com:99999/path", "http://[bad]/path"],
)
def test_validate_public_url_rejects_invalid_url_ports_or_hostnames(url):
    with pytest.raises(UnsafeOutboundURLError, match="Invalid URL"):
        asyncio.run(validate_public_url(url))


@pytest.mark.asyncio
async def test_validate_public_url_resolves_hostname_and_normalizes_result(mocker):
    loop = asyncio.get_running_loop()
    getaddrinfo = mocker.patch.object(
        loop,
        "getaddrinfo",
        new=AsyncMock(return_value=[(socket.AF_INET, 0, 0, "", ("8.8.8.8", 443))]),
    )

    from backend.utils import ssrf_utils

    result = await ssrf_utils.validate_public_url("HTTPS://Example.COM/path?q=1#fragment")

    assert result == "https://example.com/path?q=1"
    getaddrinfo.assert_awaited_once_with(
        "example.com", None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
    )


@pytest.mark.asyncio
async def test_validate_public_url_rejects_dns_errors_and_invalid_resolved_addresses(mocker):
    from backend.utils import ssrf_utils

    loop = asyncio.get_running_loop()
    mocker.patch.object(loop, "getaddrinfo", new=AsyncMock(side_effect=socket.gaierror("no host")))
    with pytest.raises(UnsafeOutboundURLError, match="could not be resolved"):
        await ssrf_utils.validate_public_url("https://unknown.example")

    mocker.patch.object(
        loop,
        "getaddrinfo",
        new=AsyncMock(return_value=[(socket.AF_INET, 0, 0, "", ("not-an-ip", 443))]),
    )
    with pytest.raises(UnsafeOutboundURLError, match="invalid address"):
        await ssrf_utils.validate_public_url("https://invalid.example")


@pytest.mark.asyncio
async def test_validate_public_url_rejects_empty_dns_results(mocker):
    loop = asyncio.get_running_loop()
    mocker.patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=[]))

    with pytest.raises(UnsafeOutboundURLError, match="only to public"):
        await validate_public_url("https://empty.example")
