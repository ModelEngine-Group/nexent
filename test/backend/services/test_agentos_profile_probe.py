# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed profile probes reach Runtime and retain tenant and cancellation boundaries."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from contracts.agentos import ModelAdministrationOperation
from contracts.constants import environment
from contracts.errors.exceptions import RuntimeUpstreamError
from contracts.model_administration import ModelProfileProbe
from infrastructure.agentos_client import AgentOSClient
from nexent.core.model_service.profiles.configuration import build_outlet_draft
from nexent.core.model_service.profiles.configuration_inputs import ModelProfilePreviewRequest
from runtime.agentos.middleware import AgentOSMiddleware
from runtime.agentos.model_administration import create_model_administration_router
from runtime.model import profile_probe


@pytest.fixture
def profile():
    return build_outlet_draft(ModelProfilePreviewRequest(request_model_id="fixture-model",
        provider_info={"base_url": "https://provider.invalid/v1"}), "tenant")[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant", ["tenant", "foreign"])
async def test_signed_profile_probe_checks_actor_tenant_and_returns_safe_result(monkeypatch, profile, tenant):
    monkeypatch.setattr(environment, "JWT_SECRET", "isolated-agentos-profile-signing-key")
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_model_administration_router())
    probe = AsyncMock(return_value={"ok": True, "error": None})
    monkeypatch.setattr(profile_probe, "probe_model_profile", probe)
    client = AgentOSClient("http://runtime", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), **kwargs,
    ))
    payload = ModelProfileProbe(profile=profile.model_dump(mode="json"), api_key="private-probe-key",
                                http_headers={"X-Workspace": "workspace"})
    if tenant != "tenant":
        with pytest.raises(RuntimeUpstreamError) as error:
            await client.model_command(ModelAdministrationOperation.PROFILE_PROBE, payload, "owner", tenant)
        assert error.value.status_code == 400
        assert b"private-probe-key" not in error.value.content
        probe.assert_not_awaited()
    else:
        assert await client.model_command(ModelAdministrationOperation.PROFILE_PROBE, payload, "owner", tenant) == {
            "ok": True, "error": None}
        probe.assert_awaited_once_with(profile, "private-probe-key", http_headers={"X-Workspace": "workspace"})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disconnect", "caller_cancel", "checker_error"])
async def test_runtime_probe_reaps_provider_task_on_all_cancellation_paths(monkeypatch, profile, failure):
    started, closed = asyncio.Event(), asyncio.Event()

    async def blocked(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    async def disconnected():
        if failure == "checker_error":
            raise RuntimeError("disconnect checker failed")
        return failure == "disconnect" and started.is_set()

    monkeypatch.setattr(profile_probe, "probe_model_profile", blocked)
    task = asyncio.create_task(profile_probe.probe_until_disconnect(profile, "key", {}, disconnected))
    await asyncio.wait_for(started.wait(), 1)
    if failure == "caller_cancel":
        task.cancel()
    with pytest.raises(RuntimeError if failure == "checker_error" else asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert closed.is_set()
