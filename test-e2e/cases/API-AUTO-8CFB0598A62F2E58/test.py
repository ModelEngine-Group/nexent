from __future__ import annotations

import asyncio
import os
import subprocess
from typing import Any

import httpx
import pytest

from shared.asset_registry import AutomationInfrastructureError
from shared.config import service_url
from shared.factories.compose import product_compose_args
from d3.assets import get_test_asset
from d5.assets import destructive_deployment_enabled
from shared.http import DEFAULT_TIMEOUT, assert_status, client

CASE_ID = 'API-AUTO-8CFB0598A62F2E58'

_MARKET_LISTING_PATHS = ('/api/market/agents',)
_MARKET_COLLECTION_PATHS = ('/api/market/tags', '/api/market/categories')
_REPOSITORY_LISTING_PATHS = ('/api/repository/agent', '/api/repository/skill')
_REPOSITORY_COLLECTION_PATHS = ('/api/repository/agent/tags', '/api/repository/skill/tags')
_REPOSITORY_FILTERED_PATHS = (
    '/api/repository/agent?tag=general&page=1&page_size=10',
    '/api/repository/skill?tag=general&page=1&page_size=10',
    '/api/repository/agent?tag_predicates=%5B%7B%22resource_type%22%3A%22agent%22%7D%5D',
    '/api/repository/skill?tag_predicates=%5B%7B%22resource_type%22%3A%22skill%22%7D%5D',
)


def _frontend_base_url() -> str:
    return os.environ.get('NEXENT_FRONTEND_URL', 'http://localhost:3000').rstrip('/')


def _auth_headers(token: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {token}'}


def _is_json(response: httpx.Response) -> bool:
    return 'application/json' in (response.headers.get('content-type') or '')


def _assert_listing_shape(payload: Any, path: str) -> None:
    assert isinstance(payload, dict) and 'items' in payload, (
        f'{path}: expected listing object with items; got {type(payload).__name__}'
    )


def _assert_collection_shape(payload: Any, path: str) -> None:
    assert isinstance(payload, (list, dict)), (
        f'{path}: expected JSON list or object; got {type(payload).__name__}'
    )


def _assert_no_secret_leak(text: str, identity: Any) -> None:
    assert identity.access_token not in text, 'proxy response leaked the session access token'
    if identity.refresh_token:
        assert identity.refresh_token not in text, 'proxy response leaked the session refresh token'


async def _wait_backend_ready(config_url: str, token: str) -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            async with httpx.AsyncClient(
                base_url=config_url,
                headers=_auth_headers(token),
                timeout=httpx.Timeout(5, connect=3),
            ) as cfg:
                probe = await cfg.get('/api/market/agents')
                if probe.status_code == 200:
                    return
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_error = exc
        await asyncio.sleep(1)
    raise AutomationInfrastructureError(f'config backend did not recover after start command: {last_error}')


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D3')
async def test_market_repository_proxy_topology_and_degradation(tenant_a_user) -> None:
    headers = _auth_headers(tenant_a_user.access_token)
    frontend_url = _frontend_base_url()

    listing_paths = _MARKET_LISTING_PATHS + _REPOSITORY_LISTING_PATHS
    collection_paths = _MARKET_COLLECTION_PATHS + _REPOSITORY_COLLECTION_PATHS

    async with httpx.AsyncClient(
        base_url=frontend_url,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=False,
    ) as frontend:
        for path in listing_paths:
            response = await frontend.get(path)
            assert_status(response, 200)
            assert _is_json(response), f'{path} must return JSON through the reverse proxy'
            _assert_listing_shape(response.json(), path)
            _assert_no_secret_leak(response.text, tenant_a_user)

        for path in collection_paths:
            response = await frontend.get(path)
            assert_status(response, 200)
            assert _is_json(response), f'{path} must return JSON through the reverse proxy'
            _assert_collection_shape(response.json(), path)
            _assert_no_secret_leak(response.text, tenant_a_user)

        for path in _REPOSITORY_FILTERED_PATHS:
            response = await frontend.get(path)
            assert_status(response, 200)
            assert _is_json(response), f'{path} must return JSON through the reverse proxy'
            _assert_listing_shape(response.json(), path)
            _assert_no_secret_leak(response.text, tenant_a_user)

    config_url = service_url('config')
    async with client('config', token=tenant_a_user.access_token) as cfg:
        direct = await cfg.get('/api/market/agents')
        assert_status(direct, 200)

    async with client('config', token=tenant_a_user.access_token) as cfg:
        repo_direct = await cfg.get('/api/repository/agent')
        assert_status(repo_direct, 200)

    destructive_deployment_enabled()
    compose = ['docker', *product_compose_args(str(get_test_asset('deployment', 'compose_project')))]
    try:
        subprocess.run([*compose, 'stop', 'nexent-config'], check=True, timeout=120)
    except subprocess.SubprocessError as exc:
        raise AutomationInfrastructureError(f'configured backend stop failed: {exc}') from exc

    try:
        async with httpx.AsyncClient(
            base_url=frontend_url,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=False,
        ) as frontend:
            for path in ('/api/market/agents', '/api/repository/agent'):
                response = await frontend.get(path)
                assert response.status_code == 502, (
                    f'{path} must return 502 when backend is unreachable, got {response.status_code}'
                )
    finally:
        try:
            subprocess.run([*compose, 'start', 'nexent-config'], check=True, timeout=180)
        except subprocess.SubprocessError as exc:
            raise AutomationInfrastructureError(f'configured backend restart failed: {exc}') from exc

    await _wait_backend_ready(config_url, tenant_a_user.access_token)

    async with httpx.AsyncClient(
        base_url=frontend_url,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=False,
    ) as frontend:
        for path in ('/api/market/agents', '/api/repository/agent'):
            response = await frontend.get(path)
            assert_status(response, 200)
