# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
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


def create_verified_httpx_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    follow_redirects: bool = True,
    **extra_kwargs,
) -> AsyncClient:
    """Create an httpx client that verifies the peer TLS certificate.

    Use for external endpoints whose certificates must be validated, such as
    remote MCP servers with ssl_verify enabled; create_httpx_client stays the
    internal trust factory for self-signed service-to-service calls.
    """
    return AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=follow_redirects,
        trust_env=False,
        verify=True,
        **extra_kwargs,
    )
