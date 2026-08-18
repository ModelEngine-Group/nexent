import asyncio

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
