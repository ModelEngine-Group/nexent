"""Verify proxy transport separately from deployed Repository business routes."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest

from shared.asset_registry import AutomationInfrastructureError
from shared.config import load_yaml, service_url
from shared.http import DEFAULT_TIMEOUT, assert_status

CASE_ID = "API-AUTO-8CFB0598A62F2E58"


def _frontend_api_base():
    environment = load_yaml("environment.yaml")
    address = os.environ.get("NEXENT_FRONTEND_URL") or environment.get("base_url")
    if not address:
        raise AutomationInfrastructureError("environment.yaml base_url is required for the deployed frontend")
    parsed = urlsplit(address)
    path = parsed.path.rstrip("/")
    locale = str(environment.get("locale") or "").replace("_", "-")
    # The browser base URL can include /zh or /en; retain any deployment base path.
    if path.rsplit("/", 1)[-1].lower() in {locale.lower(), locale.split("-")[0].lower()} - {""}:
        path = path.rsplit("/", 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D3")
async def test_market_repository_proxy_topology_and_degradation(tenant_a_admin):
    node = shutil.which("node")
    if not node:
        raise AutomationInfrastructureError("Node.js is required for the isolated production proxy probe")
    probe = Path(__file__).with_name("proxy-probe.cjs")
    completed = await asyncio.to_thread(
        subprocess.run, [node, str(probe)], capture_output=True, text=True, timeout=45,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    print(completed.stdout.strip())

    headers = {"Authorization": f"Bearer {tenant_a_admin.access_token}"}
    async with httpx.AsyncClient(
        base_url=_frontend_api_base(),
        headers=headers, timeout=DEFAULT_TIMEOUT,
        follow_redirects=False,
    ) as frontend, httpx.AsyncClient(
        base_url=service_url("config"), headers=headers, timeout=DEFAULT_TIMEOUT,
        follow_redirects=False,
    ) as backend:
        for route, expected in (
            ("/api/repository/agent", 200), ("/api/repository/skill", 200),
            ("/api/repository/agent/tags", 200), ("/api/repository/skill/tags", 200),
            ("/api/repository/agent?tag=general&page=1&page_size=10", 200),
            ("/api/repository/skill?tag_predicates=%5B%5D", 200),
            # Missing definition_id/value_ids is an invalid filter, not a valid 200 request.
            ("/api/repository/skill?tag_predicates=%5B%7B%22resource_type%22%3A%22skill%22%7D%5D", 400),
            ("/api/market/agents", None), ("/api/market/tags", None), ("/api/market/categories", None),
        ):
            direct = await backend.get(route)
            forwarded = await frontend.get(route)
            if expected is not None:
                assert_status(direct, expected)
            assert forwarded.status_code == direct.status_code, f"proxy status differs for {route}"
            assert "application/json" in forwarded.headers.get("content-type", "")
            assert forwarded.json() == direct.json(), f"proxy payload differs for {route}"
            for response in (direct, forwarded):
                assert tenant_a_admin.access_token not in response.text
                if tenant_a_admin.refresh_token:
                    assert tenant_a_admin.refresh_token not in response.text
            print(f"{route}: upstream={direct.status_code}, frontend={forwarded.status_code}")
