"""HTTP client factory utilities shared across services."""

import httpx
from httpx import AsyncClient


def create_httpx_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    follow_redirects: bool = True,
    **extra_kwargs,
) -> AsyncClient:
    return AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=follow_redirects,
        trust_env=False,
        verify=False,
        **extra_kwargs,
    )
