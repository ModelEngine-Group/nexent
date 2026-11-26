# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from __future__ import annotations

from secrets import token_hex

import httpx
import pytest

from contracts.constants import environment
from gateway.identity.downstream import IDENTITY_HEADER, sign_identity
from nexent.core.concurrency import ThreadManager
from shared.http import assert_status, client

RUNTIME_LANES = {
    "agent-run",
    "control-io",
    "model-tool-io",
    "model-embedding",
    "mcp-session",
    "sandbox",
    "background-service",
    "evaluation",
}

CONFIG_LANES = {
    "control-io",
    "background-service",
    "evaluation",
    "model-tool-io",
}


def _lane_names(snapshot: dict) -> set[str]:
    lanes = snapshot.get("lanes")
    if isinstance(lanes, dict):
        return {str(name) for name in lanes.keys()}
    if isinstance(lanes, list):
        names: set[str] = set()
        for entry in lanes:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("lane") or entry.get("lane_name")
                if name is not None:
                    names.add(str(name))
        return names
    return set()


def _normalized_state(snapshot: dict) -> str:
    state = snapshot.get("state")
    if isinstance(state, dict):
        state = state.get("value")
    value = str(state)
    return value.lower()


async def _probe(app, manager: ThreadManager, audience: str):
    identity = {"user_id": "capacity-probe", "tenant_id": "capacity-fixture", "kind": "session"}
    path = "/internal/thread-capacity"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
        assert_status(await api.get(path), 401)

        async def read_internal(route: str):
            token = sign_identity(identity, audience, "GET", route, b"")
            response = await api.get(route, headers={IDENTITY_HEADER: token})
            assert_status(response, 200)
            return response.json()

        manager.start()
        try:
            snapshot = await read_internal(path)
            assert path not in (await read_internal("/openapi.json"))["paths"]
            return snapshot
        finally:
            await manager.shutdown(timeout=5)


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-AUTO-95BBFF3CC39D73F0")
@pytest.mark.asyncio
async def test_thread_capacity_returns_process_local_snapshot_and_stays_out_of_openapi(monkeypatch):
    from management.api import application as config
    from runtime.api import application as runtime

    # Use synthetic signing keys in isolated ASGI apps. The deployed Gateway is
    # probed separately and its signing configuration is never read.
    monkeypatch.setattr(environment, "JWT_SECRET", token_hex(32))
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", token_hex(32))
    monkeypatch.setattr(environment, "GATEWAY_AUTH_ENABLED", True)
    runtime_manager = ThreadManager("runtime", runtime.runtime_thread_manager._policies)
    config_manager = ThreadManager("config", config.config_thread_manager._policies)
    monkeypatch.setattr(runtime, "runtime_thread_manager", runtime_manager)
    monkeypatch.setattr(config, "config_thread_manager", config_manager)
    for app in (runtime.app, config.app):
        monkeypatch.setattr(app, "middleware_stack", None)

    runtime_snapshot = await _probe(runtime.app, runtime_manager, "runtime")
    config_snapshot = await _probe(config.app, config_manager, "management")
    async with client("config") as gateway:
        assert_status(await gateway.get("/internal/thread-capacity"), 404)

    for service, snapshot, expected_lanes in (
        ("runtime", runtime_snapshot, RUNTIME_LANES),
        ("config", config_snapshot, CONFIG_LANES),
    ):
        assert _normalized_state(snapshot) == "running", (
            f"{service} snapshot state={snapshot.get('state')!r}, expected running"
        )
        stuck = snapshot.get("stuck_count")
        assert isinstance(stuck, int) and stuck >= 0, (
            f"{service} snapshot stuck_count must be a non-negative int, got {stuck!r}"
        )
        lanes = _lane_names(snapshot)
        assert lanes == expected_lanes, (
            f"{service} snapshot lanes={sorted(lanes)} != expected {sorted(expected_lanes)}"
        )

    assert _lane_names(runtime_snapshot) != _lane_names(config_snapshot), (
        "runtime and config snapshots must not expose identical lane topology"
    )

    for service, snapshot in (("runtime", runtime_snapshot), ("config", config_snapshot)):
        service_name = snapshot.get("service_name")
        assert service_name == service, (
            f"{service} snapshot service_name={service_name!r}, expected {service!r}"
        )
