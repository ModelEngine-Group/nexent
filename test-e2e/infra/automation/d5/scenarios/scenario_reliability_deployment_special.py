"""D5 fault-recovery and deployment special matrix."""

from __future__ import annotations

import asyncio
import json
import re
import time
from urllib.parse import quote

import httpx
import pytest

from d3.assets import temporary_conversation, temporary_knowledge_base, get_test_asset
from shared.factories.files import _upload_kb_file
from d5.assets import bash_path, destructive_deployment_enabled, require_command, run_command, run_posix_contract
from d5.scenarios.scenario_security_reliability_deployment import (
    _docker_deployment,
    _kubernetes_deployment,
    _merged_migration_equivalence,
    _v260_merged_migration_equivalence,
    _migration_idempotency,
)
from shared.asset_registry import runtime_dir
from shared.factories.compose import product_compose_args
from shared.factories.tenant import isolated_accounts
from shared.cases import special_case_params
from shared.config import repo_root
from shared.http import MODEL_TIMEOUT, assert_status, client, config_save_payload, redacted_response_body
from shared.sse import read_sse


CASES = [
    "REL-01", "REL-02", "REL-03", "REL-04", "REL-05",
    "DEP-01", "DEP-02", "DEP-03", "DEP-04", "DEP-06",
]


def _compose() -> tuple[str, list[str]]:
    docker = require_command("docker")
    project = str(get_test_asset("deployment", "compose_project"))
    return docker, product_compose_args(project)


async def _compose_service(action: str, service: str, *, timeout: float = 600) -> str:
    docker, base = _compose()
    code, output = await run_command(docker, *base, action, service, timeout=timeout)
    assert code == 0, output
    return output


async def _wait_runtime_ready(identity, *, timeout: float = 120) -> None:
    """Wait for HTTP readiness after a deliberate container/database restart."""
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            async with client("runtime", token=identity.access_token, timeout=10) as api:
                response = await api.get(
                    "/conversation/list",
                    params={"today_start_ms": 0, "week_start_ms": 0, "limit": 1},
                )
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.TransportError as exc:
            last_error = type(exc).__name__
        await asyncio.sleep(2)
    raise AssertionError(f"runtime did not recover within {timeout}s after restart: {last_error}")


async def _wait_data_process_ready(*, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            async with client("data_process", timeout=10) as api:
                response = await api.get("/tasks")
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.TransportError as exc:
            last_error = type(exc).__name__
        await asyncio.sleep(2)
    raise AssertionError(f"data-process did not recover within {timeout}s: {last_error}")


async def _scheduler_restart(identity) -> None:
    destructive_deployment_enabled()
    task_id = int(get_test_asset("reliability", "scheduler_task_id"))
    async with client("runtime", token=identity.access_token) as api:
        before = await api.get(f"/agent/automations/{task_id}/runs", params={"page": 1, "page_size": 100})
    assert_status(before, 200)
    await _compose_service("restart", "nexent-runtime")
    await _wait_runtime_ready(identity)
    async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        health = await api.get(
            "/conversation/list", params={"today_start_ms": 0, "week_start_ms": 0, "limit": 1},
        )
    assert_status(health, 200)
    async with client("runtime", token=identity.access_token) as api:
        after = await api.get(f"/agent/automations/{task_id}/runs", params={"page": 1, "page_size": 100})
    assert_status(after, 200)
    before_ids = [row.get("run_id") for row in (before.json().get("data") or {}).get("items", [])]
    after_ids = [row.get("run_id") for row in (after.json().get("data") or {}).get("items", [])]
    assert len(after_ids) == len(set(after_ids))
    assert set(before_ids).issubset(after_ids)


async def _provider_failure(identity) -> None:
    agent_id = int(get_test_asset("agents", "basic_id"))
    fault_model_id = int(get_test_asset("reliability", "fault_model_id"))
    async with temporary_conversation(identity, "D5 provider failure") as conversation_id:
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream(
                "POST", "/agent/run",
                json={
                    "agent_id": agent_id, "model_id": fault_model_id, "conversation_id": conversation_id,
                    "query": "Provider 429/5xx/timeout recovery probe", "history": [], "is_debug": True,
                },
            ) as response:
                assert_status(response, 200)
                try:
                    events = await asyncio.wait_for(read_sse(response, limit=2000), timeout=60)
                except asyncio.TimeoutError as exc:
                    raise AssertionError(
                        "provider fault did not converge to a terminal event within 60 seconds"
                    ) from exc
    text = json.dumps(events, ensure_ascii=False).lower()
    assert "error" in text or "timeout" in text or "rate" in text or "fail" in text
    assert "api_key" not in text and "authorization" not in text


async def _data_process_recovery(identity) -> None:
    destructive_deployment_enabled()
    async with temporary_knowledge_base(identity, prefix="d5-data-recovery") as kb:
        uploaded = await _upload_kb_file(identity, kb["index_name"])
        file_data = {
            "path_or_url": uploaded["object_name"], "filename": uploaded["payload"]["uploaded_filenames"][0],
            "file_id": uploaded["record"]["file_id"],
        }
        await _compose_service("stop", "nexent-data-process")
        try:
            async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                failed = await api.post(
                    "/file/process",
                    json={"files": [file_data], "index_name": kb["index_name"], "destination": "minio", "chunking_strategy": "basic"},
                )
            assert_status(failed, (500, 502, 503, 504))
        finally:
            await _compose_service("start", "nexent-data-process")
        await _wait_data_process_ready()
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            retry = await api.post(
                "/file/process",
                json={"files": [file_data], "index_name": kb["index_name"], "destination": "minio", "chunking_strategy": "basic"},
            )
        assert_status(retry, 201)


async def _redis_recovery(identity) -> None:
    destructive_deployment_enabled()
    from shared.factories.agent import retrieval_agent

    async with retrieval_agent(identity) as agent_id, temporary_conversation(identity, "D5 Redis recovery") as conversation_id:
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            baseline = await api.get(f"/conversation/{conversation_id}")
        assert_status(baseline, 200)

        # A conversation alone has no active run: /agent/stop correctly returns
        # 200 already_stopped even when Redis is unavailable. Inject the fault
        # only after the live stream has emitted its run-start event.
        fault_injected = False
        stream_finished = False
        outage_stop = None
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream("POST", "/agent/run", json={
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "history": [],
                "is_debug": False,
                "query": "Explain the recovery process in detail, including each step and its reason.",
            }) as response:
                assert_status(response, 200)
                try:
                    async with asyncio.timeout(240):
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                stream_finished = True
                                break
                            try:
                                event = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            if not fault_injected and isinstance(event, dict) and event.get("type") == "agent_new_run":
                                fault_injected = True
                                await _compose_service("stop", "redis")
                                try:
                                    async with client("runtime", token=identity.access_token, timeout=30) as stopper:
                                        outage_stop = await stopper.get(f"/agent/stop/{conversation_id}")
                                except httpx.TransportError:
                                    # A transport failure during the outage is
                                    # acceptable; recovery and retry are still required.
                                    pass
                                finally:
                                    await _compose_service("start", "redis")
                                await _wait_runtime_ready(identity)
                        else:
                            stream_finished = True
                finally:
                    if fault_injected:
                        # Idempotent even when the normal path already started it.
                        await _compose_service("start", "redis")

        assert fault_injected, "agent run ended before Redis fault injection; recovery was not tested"
        if outage_stop is not None:
            assert_status(outage_stop, (200, 500, 502, 503, 504))
            if outage_stop.status_code == 200:
                assert outage_stop.json().get("already_stopped") is not True, (
                    "active run was falsely reported as already stopped during Redis outage"
                )
        assert stream_finished, "agent run stream did not converge after Redis recovery"
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            stopped = await api.get(f"/agent/stop/{conversation_id}")
            health = await api.get(
                "/conversation/list", params={"today_start_ms": 0, "week_start_ms": 0, "limit": 1},
            )
            recovered = await api.get(f"/conversation/{conversation_id}")
        assert_status(stopped, 200)
        assert_status(health, 200)
        assert_status(recovered, 200)


async def _config_partial_failure(identity) -> None:
    destructive_deployment_enabled()
    async with client("config", token=identity.access_token) as api:
        loaded = await api.get("/config/load_config")
    assert_status(loaded, 200)
    current = config_save_payload(loaded.json())
    await _compose_service("stop", "nexent-runtime")
    try:
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            partial = await api.post("/config/save_config", json=current)
        assert_status(partial, (200, 400, 500, 502, 503, 504))
    finally:
        await _compose_service("start", "nexent-runtime")
    await _wait_runtime_ready(identity)
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        retried = await api.post("/config/save_config", json=current)
        verified = await api.get("/config/load_config")
    assert_status(retried, 200)
    assert_status(verified, 200)
    assert config_save_payload(verified.json()) == current


async def _config_partial_failure_isolated() -> None:
    async with isolated_accounts(["tenant_a_admin"]) as accounts:
        await _config_partial_failure(accounts["tenant_a_admin"])


async def _docker_persistence(identity) -> None:
    destructive_deployment_enabled()
    async with temporary_conversation(identity, "D5 Docker persistence") as conversation_id:
        await _compose_service("restart", "nexent-postgresql", timeout=900)
        await _compose_service("restart", "nexent-runtime", timeout=900)
        await _wait_runtime_ready(identity)
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            recovered = await api.get(f"/conversation/{conversation_id}")
        assert_status(recovered, 200)
        assert str(conversation_id) in recovered.text


async def _migration_upgrade_compatibility(identity) -> None:
    """DEP-04: legacy snapshot + merged overlay equivalence, then P0 smoke."""
    await _migration_idempotency()
    await _merged_migration_equivalence()
    await _v260_merged_migration_equivalence()
    bash = require_command("bash")
    for contract in (
        repo_root() / "deploy" / "tests" / "test_unified_tag_management.sh",
        repo_root() / "deploy" / "tests" / "test_sql_migrations.sh",
    ):
        code, output = await run_command(bash, str(contract), timeout=1200)
        assert code == 0, f"migration contract failed: {contract.name}\n{output}"
    async with temporary_conversation(identity, "D5 migration smoke") as conversation_id:
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream(
                "POST", "/agent/run",
                json={
                    "agent_id": int(get_test_asset("agents", "basic_id")),
                    "conversation_id": conversation_id,
                    "query": "Reply with the exact marker DEP04_SMOKE_OK.",
                    "history": [], "is_debug": False,
                },
            ) as response:
                assert_status(response, 200)
                try:
                    events = await asyncio.wait_for(read_sse(response, limit=2000), timeout=300)
                except asyncio.TimeoutError as exc:
                    raise AssertionError("post-migration smoke run did not converge within 300s") from exc
    text = json.dumps(events, ensure_ascii=False).lower()
    assert "dep04_smoke_ok" in text, "real LLM smoke after migration equivalence checks failed"
    async with client("runtime", token=identity.access_token) as api:
        recovered = await api.get(f"/conversation/{conversation_id}")
    assert_status(recovered, 200)
    assert "dep04_smoke_ok" in recovered.text.lower(), "persisted run must survive the scratch-migration checks"


async def _backup_upgrade_rollback_contracts() -> None:
    """DEP-06: deterministic Docker/Kubernetes backup and rollback assets."""
    for contract in (
        repo_root() / "deploy" / "tests" / "test_docker_backup.sh",
        repo_root() / "deploy" / "tests" / "test_k8s_backup.sh",
    ):
        assert contract.is_file(), f"missing backup contract: {contract}"
        code, output = await run_posix_contract(contract, timeout=1200)
        assert code == 0, f"backup contract failed: {contract.name}\n{output}"


_REL06_TERMINAL = {"COMPLETED", "PROCESS_FAILED", "FORWARD_FAILED"}
_REL06_WORKER_LOG_RE = re.compile(
    r"Starting (process-worker|process-part-worker|forward-worker|forward-part-worker|forward-aggregate-worker)"
    r" worker for queue: (\w+) with concurrency: (\d+)"
)


def _rel06_expected_topology() -> tuple[dict[str, tuple[str, int]], list[str]]:
    """Recompute backend/data_process_service.py::_build_worker_configs from const.py defaults."""
    text = (repo_root() / "backend" / "consts" / "const.py").read_text(encoding="utf-8")
    dp = int(re.search(r'DP_PART_PROCESSOR_COUNT = int\(os\.getenv\("DP_PART_PROCESSOR_COUNT", "(\d+)"\)\)', text).group(1))
    actor_cpus = int(re.search(r'RAY_ACTOR_NUM_CPUS = int\(os\.getenv\("RAY_ACTOR_NUM_CPUS", "(\d+)"\)\)', text).group(1))
    queues = re.search(r'QUEUES = os\.getenv\(\s*"QUEUES",\s*"([^"]+)",', text).group(1).split(",")
    total_cpus = dp * actor_cpus
    process = min(dp, max(1, total_cpus // actor_cpus))
    forward = min(8, total_cpus * 2)
    aggregate = min(2, total_cpus)
    expected = {
        "process-worker": ("process_q", process),
        "process-part-worker": ("process_part_q", process),
        "forward-worker": ("forward_q", forward),
        "forward-part-worker": ("forward_part_q", forward),
        "forward-aggregate-worker": ("forward_aggregate_q", aggregate),
    }
    assert [queue for queue, _ in expected.values()] == queues, "const.py QUEUES default must match the five worker queues"
    return expected, queues


async def _rel06_worker_topology() -> dict[str, tuple[str, int]]:
    docker, base = _compose()
    code, output = await run_command(
        docker, *base, "logs", "--no-color", "--tail", "20000", "nexent-data-process", timeout=300,
    )
    assert code == 0, "could not read nexent-data-process startup logs"
    observed: dict[str, tuple[str, int]] = {}
    for name, queue, concurrency in _REL06_WORKER_LOG_RE.findall(output):
        observed[name] = (queue, int(concurrency))
    return observed


async def _rel06_broker_db() -> str:
    docker, base = _compose()
    code, output = await run_command(docker, *base, "exec", "-T", "nexent-data-process", "printenv", "REDIS_URL", timeout=120)
    assert code == 0, "REDIS_URL is not readable inside nexent-data-process"
    tail = output.strip().splitlines()[-1].rsplit("/", 1)[-1]
    return tail if tail.isdigit() else "0"


async def _rel06_queue_depth(broker_db: str, queue: str) -> int:
    docker, base = _compose()
    code, output = await run_command(
        docker, *base, "exec", "-T", "redis", "redis-cli", "-n", broker_db, "llen", queue, timeout=60,
    )
    assert code == 0, f"redis-cli llen failed for queue {queue}"
    return int(output.strip().splitlines()[-1])


async def _rel06_file_status(api, index: str) -> dict[str, str]:
    response = await api.get(f"/indices/{index}/files")
    assert_status(response, 200)
    return {str(row.get("path_or_url") or ""): str(row.get("status") or "") for row in response.json().get("files", [])}


async def _rel06_wait_es_ready(index: str, identity, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            async with client("config", token=identity.access_token) as api:
                response = await api.get(f"/indices/{index}/files")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(5)
    raise AssertionError(f"elasticsearch did not recover within {timeout_s}s")


async def _rel06_wait_drain(broker_db: str, queues: list[str], timeout_s: int) -> dict[str, int]:
    deadline = time.monotonic() + timeout_s
    while True:
        depths = {queue: await _rel06_queue_depth(broker_db, queue) for queue in queues}
        if all(depth == 0 for depth in depths.values()):
            return depths
        assert time.monotonic() < deadline, f"worker queues did not converge to zero within {timeout_s}s: {depths}"
        await asyncio.sleep(5)


async def _rel06_wait_task_failures(index: str, object_names: set[str], timeout_s: int) -> str:
    """While the aggregate dependency is down, confirm an explicit failure is reported."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        async with client("data_process") as api:
            response = await api.get(f"/tasks/indices/{index}")
        if response.status_code == 200:
            rows = response.json()
            for row in rows.get("tasks", []) if isinstance(rows, dict) else rows or []:
                if str(row.get("path_or_url") or "") not in object_names:
                    continue
                state = str(row.get("status") or "").upper()
                if state in {"FAILURE", "REVOKED"} or row.get("error"):
                    return f"task {row.get('task_name')} reported state={state or 'FAILURE'}"
        await asyncio.sleep(5)
    return ""


def _rel06_assert_no_secrets(text: str) -> None:
    lowered = (text or "").lower()
    for marker in ("password", "secret", "minioadmin", "access_key", "accesskey", "api_key", "apikey", "bearer "):
        assert marker not in lowered, f"failure report leaked credential marker {marker!r}"


def _rel06_record(evidence: dict) -> None:
    directory = runtime_dir()
    if directory is not None:
        (directory / "rel06-forward-queue-isolation.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=1, default=str), encoding="utf-8",
        )


def _rel06_spec(uploaded: dict) -> dict:
    return {
        "path_or_url": uploaded["object_name"],
        "filename": uploaded["payload"]["uploaded_filenames"][0],
        "file_id": uploaded["record"]["file_id"],
    }


async def _forward_queue_isolation(identity) -> None:
    """REL-06: forward part/aggregate queue isolation with a deadlock-free large import."""
    destructive_deployment_enabled()
    expected_topology, queues = _rel06_expected_topology()
    observed = await _rel06_worker_topology()
    assert observed == expected_topology, (
        f"worker topology must match _build_worker_configs: observed={observed} expected={expected_topology}"
    )
    import_timeout = int(get_test_asset("reliability", "queue_isolation_timeout_s", required=False) or 1800)
    drain_timeout = int(get_test_asset("reliability", "queue_drain_timeout_s", required=False) or 300)
    recovery_timeout = int(get_test_asset("reliability", "queue_recovery_timeout_s", required=False) or 900)
    broker_db = await _rel06_broker_db()
    token = identity.access_token
    file_count = observed["forward-part-worker"][1] + 2
    evidence: dict = {
        "worker_topology": {name: {"queue": queue, "concurrency": concurrency} for name, (queue, concurrency) in observed.items()},
        "import_file_count": file_count,
        "queue_depth_samples": [],
        "terminal_states": {},
        "failure_report": None,
    }
    async with temporary_knowledge_base(identity, prefix="d5-rel06") as kb:
        index = kb["index_name"]
        try:
            big_files = [await _upload_kb_file(identity, index, asset_key="office") for _ in range(file_count)]
            big_names = {uploaded["object_name"] for uploaded in big_files}
            async with client("config", token=token, timeout=MODEL_TIMEOUT) as api:
                submitted = await api.post(
                    "/file/process",
                    json={
                        "files": [_rel06_spec(uploaded) for uploaded in big_files],
                        "index_name": index, "destination": "minio", "chunking_strategy": "basic",
                    },
                )
            assert_status(submitted, 201)
            deadline = time.monotonic() + import_timeout
            statuses: dict[str, str] = {}
            while True:
                evidence["queue_depth_samples"].append({queue: await _rel06_queue_depth(broker_db, queue) for queue in queues})
                async with client("config", token=token) as api:
                    statuses = await _rel06_file_status(api, index)
                if big_names.issubset(set(statuses)) and all(statuses[name] in _REL06_TERMINAL for name in big_names):
                    break
                assert time.monotonic() < deadline, (
                    f"large import did not reach terminal states within {import_timeout}s; "
                    f"aggregate callbacks may be starved: { {name: statuses.get(name) for name in big_names} }"
                )
                await asyncio.sleep(5)
            evidence["terminal_states"]["large_import"] = {name: statuses[name] for name in big_names}
            hung = {name: statuses[name] for name in big_names if statuses[name] != "COMPLETED"}
            assert not hung, f"forward part/aggregate isolation failed, non-COMPLETED terminals: {hung}"
            evidence["queue_depth_zero_after_import"] = await _rel06_wait_drain(broker_db, queues, drain_timeout)

            fault_files = [await _upload_kb_file(identity, index, asset_key="office") for _ in range(2)]
            fault_names = {uploaded["object_name"] for uploaded in fault_files}
            await _compose_service("stop", "nexent-elasticsearch")
            explicit_failure = ""
            try:
                async with client("config", token=token, timeout=MODEL_TIMEOUT) as api:
                    fault_submit = await api.post(
                        "/file/process",
                        json={
                            "files": [_rel06_spec(uploaded) for uploaded in fault_files],
                            "index_name": index, "destination": "minio", "chunking_strategy": "basic",
                        },
                    )
                if fault_submit.status_code == 201:
                    explicit_failure = await _rel06_wait_task_failures(index, fault_names, recovery_timeout)
                else:
                    assert_status(fault_submit, (500, 502, 503, 504))
                    explicit_failure = f"submission rejected: {redacted_response_body(fault_submit)}"
            finally:
                await _compose_service("start", "nexent-elasticsearch")
            await _rel06_wait_es_ready(index, identity, 300)
            async with client("config", token=token) as api:
                statuses = await _rel06_file_status(api, index)
            pending = {name: statuses.get(name, "MISSING") for name in fault_names if statuses.get(name) not in _REL06_TERMINAL}
            assert not pending, f"injected-failure tasks are dangling after recovery: {pending}"
            evidence["terminal_states"]["fault_injection"] = {name: statuses[name] for name in fault_names}
            failed_names = {name for name in fault_names if statuses[name] != "COMPLETED"}
            assert explicit_failure or failed_names, "dependency outage was never reported explicitly"
            evidence["failure_report"] = explicit_failure
            _rel06_assert_no_secrets(explicit_failure)
            if failed_names:
                async with client("config", token=token) as api:
                    error_info = await api.get(f"/indices/{index}/documents/{quote(next(iter(failed_names)), safe='')}/error-info")
                assert_status(error_info, 200)
                _rel06_assert_no_secrets(redacted_response_body(error_info))
                retry_files = [uploaded for uploaded in fault_files if uploaded["object_name"] in failed_names]
                async with client("config", token=token, timeout=MODEL_TIMEOUT) as api:
                    retry = await api.post(
                        "/file/process",
                        json={
                            "files": [_rel06_spec(uploaded) for uploaded in retry_files],
                            "index_name": index, "destination": "minio", "chunking_strategy": "basic",
                        },
                    )
                assert_status(retry, 201)
                retry_names = {uploaded["object_name"] for uploaded in retry_files}
                deadline = time.monotonic() + recovery_timeout
                while True:
                    async with client("config", token=token) as api:
                        statuses = await _rel06_file_status(api, index)
                    if retry_names.issubset(set(statuses)) and all(statuses[name] == "COMPLETED" for name in retry_names):
                        break
                    assert time.monotonic() < deadline, (
                        f"retry after dependency recovery did not converge within {recovery_timeout}s: "
                        f"{ {name: statuses.get(name) for name in retry_names} }"
                    )
                    await asyncio.sleep(5)
                evidence["terminal_states"]["fault_retry"] = {name: "COMPLETED" for name in retry_names}
            evidence["queue_depth_zero_after_recovery"] = await _rel06_wait_drain(broker_db, queues, drain_timeout)
        finally:
            _rel06_record(evidence)


@pytest.mark.asyncio
async def execute_d5_reliability_deployment_special(case, tenant_a_admin, tenant_a_user):
    handlers = {
        "REL-01": lambda: _scheduler_restart(tenant_a_user),
        "REL-02": lambda: _provider_failure(tenant_a_user),
        "REL-03": lambda: _data_process_recovery(tenant_a_admin),
        "REL-04": lambda: _redis_recovery(tenant_a_admin),
        "REL-05": _config_partial_failure_isolated,
        "REL-06": lambda: _forward_queue_isolation(tenant_a_admin),
        "DEP-01": _docker_deployment,
        "DEP-02": lambda: _docker_persistence(tenant_a_user),
        "DEP-03": _kubernetes_deployment,
        "DEP-04": lambda: _migration_upgrade_compatibility(tenant_a_user),
        "DEP-06": _backup_upgrade_rollback_contracts,
    }
    await handlers[case["id"]]()
