from __future__ import annotations

import pytest

from shared.http import assert_status, client

RUNTIME_LANES = {
    "agent-run",
    "control-io",
    "model-tool-io",
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


async def _fetch_snapshot(service: str) -> dict:
    async with client(service) as api:
        response = await api.get("/internal/thread-capacity")
    assert_status(response, 200)
    body = response.json()
    assert isinstance(body, dict), f"snapshot must be a JSON object, got {type(body).__name__}"
    return body


async def _openapi_paths(service: str) -> set[str]:
    async with client(service) as api:
        response = await api.get("/openapi.json")
    assert_status(response, 200)
    schema = response.json()
    paths = schema.get("paths") if isinstance(schema, dict) else {}
    return {str(path) for path in (paths or {}).keys()}


@pytest.mark.stage("D2")
@pytest.mark.case_id("API-AUTO-95BBFF3CC39D73F0")
@pytest.mark.asyncio
async def test_thread_capacity_returns_process_local_snapshot_and_stays_out_of_openapi():
    runtime_snapshot = await _fetch_snapshot("runtime")
    config_snapshot = await _fetch_snapshot("config")

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

    for service in ("runtime", "config"):
        paths = await _openapi_paths(service)
        assert "/internal/thread-capacity" not in paths, (
            f"{service} openapi paths must not expose /internal/thread-capacity"
        )
