# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Fixed-size conversation load through the deployed Gateway."""

import asyncio
from contextlib import AsyncExitStack
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from d3.assets import temporary_conversation
from shared.asset_registry import AssetDependencyError, register_asset
from shared.config import controlled_asset_url, readiness_url, service_url
from shared.final_answers import final_answer_text
from shared.http import assert_status, client
from shared.postgres import postgres_sql
from shared.sse import assert_terminal_event, read_sse


TIERS = ((10, 30), (25, 30), (50, 120))
SERVICES = ("nexent-gateway", "nexent-config", "nexent-runtime", "nexent-postgresql")


def docker_json(*args):
    try:
        result = subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=12)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AssetDependencyError("services", "local-docker", detail=type(exc).__name__) from exc
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def container_state():
    return docker_json("inspect", "--format",
                       '{"state":{{json .State}},"restarts":{{json .RestartCount}},'
                       '"project":{{json (index .Config.Labels "com.docker.compose.project")}}}', *SERVICES)


def assert_stack_unchanged(before, after):
    for service, old, new in zip(SERVICES, before, after, strict=True):
        assert new["state"]["Running"], f"{service} stopped during load"
        assert not new["state"]["OOMKilled"], f"{service} was OOM-killed during load"
        assert new["restarts"] == old["restarts"] and new["state"]["StartedAt"] == old["state"]["StartedAt"], (
            f"{service} restarted during load"
        )


def percentile(values, quantile):
    if not values:
        return None
    return round(sorted(values)[math.ceil(len(values) * quantile) - 1], 3)


def summarize(target, samples, requests):
    completed = [row for row in requests if row["outcome"] == "PASS"]
    return {"target": target, "requests": len(requests), "completed": len(completed),
            "completed_conversations": len({row.get("session") for row in completed if "session" in row}),
            "success_rate": len(completed) / max(1, len(requests)),
            "client_peak": max((row["client_in_flight"] for row in samples), default=0),
            "execution_peak": max((row["runtime_active"] for row in samples), default=0),
            "waiting_estimate_peak": max((row["waiting_estimate"] for row in samples), default=0),
            "first_content_p50_seconds": percentile([row["first"] for row in completed], 0.50),
            "first_content_p95_seconds": percentile([row["first"] for row in completed], 0.95),
            "completion_p95_seconds": percentile([row["elapsed"] for row in completed], 0.95)}


async def fixture(identity, run):
    display = "daily_perf_" + run
    async with client("config", token=identity.access_token) as api:
        result = await api.post("/model/create", json={
            "model_factory": "OpenAI-API-Compatible", "model_name": "daily-fixed-stream", "model_type": "llm",
            "api_key": run, "base_url": controlled_asset_url(f"/performance/{run}/v1"),
            "display_name": display, "max_tokens": 4096, "skip_default_backfill": True})
        assert_status(result, 200)
        register_asset("owned_models", display, display, owner_case_id="PERF-02", cleanup={
            "service": "config", "identity": identity.id, "method": "POST", "path": "/model/delete",
            "params": {"display_name": display}, "allowed_statuses": [200, 404]})
        health = await api.post("/model/healthcheck", params={"display_name": display, "model_type": "llm"})
        assert_status(health, 200)
        assert health.json().get("data", health.json()).get("connectivity") is True, "Fixture model is unavailable"
        catalog = await api.get("/model/list")
        assert_status(catalog, 200)
        rows = catalog.json()
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("models") or []
        (model,) = [row for row in rows if row.get("display_name") == display]
        model_id = int(model.get("model_id") or model["id"])
        agent = await api.post("/agent/update", json={
            "name": display, "display_name": display, "description": "Owned Daily performance Agent",
            "business_description": "Controlled streaming load", "max_steps": 3, "provide_run_summary": False,
            "model_ids": [model_id], "enabled_tool_ids": [], "enabled_skill_ids": [],
            "enabled": True, "version_no": 0})
        assert_status(agent, 200)
        agent_id = int(agent.json()["agent_id"])
        register_asset("owned_agents", str(agent_id), agent_id, owner_case_id="PERF-02", cleanup={
            "service": "config", "identity": identity.id, "method": "DELETE", "path": "/agent",
            "json": {"agent_id": agent_id}, "allowed_statuses": [200, 404]})
        assert_status(await api.put(f"/agent/clear_new/{agent_id}"), 200)
        assert_status(await api.post(f"/agent/{agent_id}/publish",
                                     json={"version_name": "daily-load", "release_note": "Owned test agent"}), 200)
    return {"agent_id": agent_id, "model_id": model_id}


async def request_chat(api, agent, conversation_id):
    marker = "D5PERF_" + uuid4().hex[:12]
    started = time.monotonic()
    first = None

    def observe(event):
        nonlocal first
        data = event["data"]
        if (first is None and isinstance(data, dict) and data.get("depth", 0) == 0
                and data.get("type") in {"final_answer", "model_output_thinking"} and data.get("content")):
            first = time.monotonic() - started

    try:
        async with asyncio.timeout(20):
            async with api.stream("POST", "agent/run", json={
                **agent, "conversation_id": conversation_id, "history": [],
                "is_debug": False, "stream_cursor": True, "query": f"Reply with {marker}."}) as response:
                if response.status_code != 200:
                    return {"outcome": f"HTTP_{response.status_code}"}
                events = await read_sse(response, on_event=observe)
        assert_terminal_event(events)
        run_endings = [frame["data"] for frame in events if frame["event"] == "agentos_terminal"]
        assert len(run_endings) == 1 and isinstance(run_endings[0], dict) and run_endings[0].get("status") == "completed"
        answer = final_answer_text(events)
        if set(re.findall(r"D5PERF_[a-f0-9]{12}", answer)) != {marker}:
            return {"outcome": "ANSWER_MARKER_MISMATCH"}
        terminal_count = sum(
            isinstance(frame["data"], dict) and frame["data"].get("depth", 0) == 0
            and frame["data"].get("type") == "final_answer"
            and frame["data"].get("answer_phase") != "delta"
            for frame in events
        )
        if terminal_count != 1:
            return {"outcome": "INVALID_TERMINAL_COUNT", "terminal_count": terminal_count}
        assert first is not None
        return {"outcome": "PASS", "first": first, "elapsed": time.monotonic() - started}
    except (TimeoutError, httpx.TimeoutException):
        return {"outcome": "TIMEOUT"}
    except httpx.HTTPError:
        return {"outcome": "TRANSPORT_ERROR"}
    except AssertionError:
        return {"outcome": "INVALID_STREAM"}


def activity(conversations):
    # IDs are allocated and journaled by the fixture. Only those runs count.
    ids = ",".join(str(int(value)) for value in conversations)
    result = postgres_sql(
        "SELECT (SELECT count(*) FROM nexent.agent_execution_t WHERE status IN ('starting','running') "
        f"AND conversation_id IN ({ids})), (SELECT numbackends FROM pg_stat_database WHERE datname=current_database())"
    ).strip()
    return tuple(int(value) for value in result.split("\t"))


async def run_tier(api, probe, gateway, mock_url, agent, conversations, seconds, evidence):
    target = len(conversations)
    before = await asyncio.to_thread(container_state)
    deadline = time.monotonic() + seconds
    in_flight = 0
    health_failures = 0
    samples, requests = [], []
    evidence.update(target=target, duration_seconds=seconds, samples=samples, requests=requests)

    async def load(session, conversation):
        nonlocal in_flight
        while time.monotonic() < deadline:
            in_flight += 1
            try:
                result = await request_chat(api, agent, conversation)
                requests.append({**result, "session": session})
                assert result["outcome"] not in {"ANSWER_MARKER_MISMATCH", "INVALID_TERMINAL_COUNT"}
            finally:
                in_flight -= 1

    async def observe():
        nonlocal health_failures
        last_probe = 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            sent = in_flight
            running, connections = await asyncio.to_thread(activity, conversations)
            samples.append({"client_in_flight": sent, "runtime_active": running,
                            "waiting_estimate": max(0, sent - running), "db_connections": connections})
            if now - last_probe >= 5:
                stats = await asyncio.to_thread(docker_json, "stats", "--no-stream", "--format", "{{json .}}", *SERVICES)
                samples[-1]["containers"] = stats
                assert_stack_unchanged(before, await asyncio.to_thread(container_state))
                try:
                    statuses = await asyncio.gather(*(probe.get(url) for url in (
                        gateway + "/health/ready", readiness_url("config"), readiness_url("runtime"))))
                    healthy = all(response.status_code == 200 for response in statuses)
                except httpx.HTTPError:
                    healthy = False
                samples[-1]["ready"] = healthy
                health_failures = 0 if healthy else health_failures + 1
                assert health_failures < 3, "Gateway or downstream readiness failed three times during load"
                response = await probe.get(mock_url)
                response.raise_for_status()
                samples[-1]["mock_active"] = response.json()["model_streams"]
                last_probe = now
            await asyncio.sleep(max(0, 1 - (time.monotonic() - now)))

    try:
        async with asyncio.timeout(seconds + 60):
            async with asyncio.TaskGroup() as group:
                for session, conversation in enumerate(conversations):
                    group.create_task(load(session, conversation))
                group.create_task(observe())
            while (await asyncio.to_thread(activity, conversations))[0]:
                await asyncio.sleep(1)
    finally:
        evidence["summary"] = summarize(target, samples, requests)
    assert evidence["summary"]["client_peak"] == target, f"Load generator did not reach {target} in-flight sessions"
    assert evidence["summary"]["completed_conversations"] == target, f"Some of the {target} sessions never completed a response"
    assert evidence["summary"]["success_rate"] >= 0.99, f"Completion rate below 99% at {target} simultaneous sessions"
    assert_stack_unchanged(before, await asyncio.to_thread(container_state))


async def verify_stream_recovery(api, agent, conversation_id, *, stop=False):
    marker = "D5PERF_" + uuid4().hex[:12]
    query = f"Reply with {marker}."
    if stop:
        query += " D5PERF_HOLD"
    payload = {**agent, "conversation_id": conversation_id, "history": [],
               "is_debug": False, "stream_cursor": True, "query": query}
    async with asyncio.timeout(30):
        async with api.stream("POST", "agent/run", json=payload) as response:
            assert_status(response, 200)
            cursor = None
            async for line in response.aiter_lines():
                if line.startswith("id:"):
                    cursor = re.fullmatch(r"id: ?([0-9a-f]{32}):([1-9][0-9]*)", line)
                elif not line and cursor is not None:
                    break
            else:
                raise AssertionError("The original stream did not emit a replay cursor")
            generation, acknowledged = cursor.groups()
            if stop:
                stopped = await api.get(f"agent/stop/{generation}")
                assert_status(stopped, 200)
                assert stopped.json().get("cancellation_requested") is True
        if not stop:
            params = {"resume": "true", "run_id": generation, "after_event_id": f"{generation}:{acknowledged}"}
            async with api.stream("POST", "agent/run", params=params, json=payload) as replay:
                assert_status(replay, 200)
                assert replay.headers["X-AgentOS-Run-ID"] == generation
                events = await read_sse(replay, include_ids=True)
            assert_terminal_event(events)
            cursors = [event["id"].split(":") for event in events if "id" in event]
            assert cursors and all(run_id == generation for run_id, _ in cursors)
            indices = [int(index) for _, index in cursors]
            assert indices == sorted(set(indices)) and indices[0] > int(acknowledged)
            assert events[-1]["event"] == "agentos_terminal" and events[-1]["data"]["status"] == "completed"
            assert marker in final_answer_text(events), "Replay did not complete the original response"
        while (await asyncio.to_thread(activity, [conversation_id]))[0]:
            await asyncio.sleep(0.5)


async def exercise(identity):
    gateway = service_url("northbound").removesuffix("/api").rstrip("/")
    url = urlsplit(gateway)
    if url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.port != 5013:
        raise AssetDependencyError("services", "local-gateway", detail="Require loopback Daily Gateway on port 5013")
    initial = await asyncio.to_thread(container_state)
    if any(state["project"] != "nexent" or not state["state"]["Running"] for state in initial):
        raise AssetDependencyError("services", "local-stack", detail="Require the running Daily Docker stack")
    run = uuid4().hex
    results = {"tiers": []}
    try:
        agent = await fixture(identity, run)
        async with AsyncExitStack() as stack:
            conversations = [
                await stack.enter_async_context(temporary_conversation(identity, f"Daily concurrency {run} {i}"))
                for i in range(TIERS[-1][0])
            ]
            api = await stack.enter_async_context(httpx.AsyncClient(
                base_url=gateway + "/api/", headers={"Authorization": f"Bearer {identity.access_token}"},
                timeout=15, limits=httpx.Limits(max_connections=60), trust_env=False))
            probe = await stack.enter_async_context(httpx.AsyncClient(timeout=4, trust_env=False))
            mock_url = os.environ["NEXENT_TEST_ASSETS_LOCAL_URL"] + f"/performance/{run}/active"
            assert (await request_chat(api, agent, conversations[0]))["outcome"] == "PASS", "Warmup failed"
            for target, seconds in TIERS:
                evidence = {}
                results["tiers"].append(evidence)
                await run_tier(api, probe, gateway, mock_url, agent, conversations[:target], seconds, evidence)
            await verify_stream_recovery(api, agent, conversations[0])
            await verify_stream_recovery(api, agent, conversations[1], stop=True)
            async with temporary_conversation(identity, f"Daily concurrency recovery {run}") as fresh:
                assert (await request_chat(api, agent, fresh))["outcome"] == "PASS", "Post-load recovery failed"
            assert_stack_unchanged(initial, await asyncio.to_thread(container_state))
    finally:
        path = Path(os.environ["RESULT_DIR"]) / "runtime" / "conversation-load.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
