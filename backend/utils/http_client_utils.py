"""HTTP client factory utilities shared across services."""

import httpx
from httpx import AsyncClient


def create_httpx_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> AsyncClient:
    return AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        trust_env=False,
        verify=False,
    )
