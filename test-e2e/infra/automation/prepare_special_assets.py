"""Create batch-scoped D5 performance and reliability assets through product APIs."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from d3.assets import create_registered_knowledge_base, model_id, model_request
from shared.asset_registry import register_asset, register_asset_failure, resolve_asset
from shared.auth import sign_in
from shared.config import test_root
from shared.http import MODEL_TIMEOUT, assert_status, client


def _object_name(payload: dict) -> str:
    paths = payload.get("uploaded_file_paths") or []
    if paths:
        return str(paths[0])
    for item in payload.get("results") or []:
        if item.get("success"):
            value = item.get("object_name") or item.get("path") or item.get("file_path")
            if value:
                return str(value)
    raise AssertionError(f"upload response omitted object name: {payload}")


async def prepare_knowledge(identity) -> None:
    existing_index = resolve_asset("performance", "upload_kb_index", required=False)
    if existing_index:
        if not resolve_asset("performance", "large_kb_indices", required=False):
            register_asset("performance", "large_kb_indices", [str(existing_index)], owner_case_id="PERF-04")
        return
    embedding_id = await prepare_performance_embedding(identity)
    kb = await create_registered_knowledge_base(
        identity,
        owner_case_id="PERF-03",
        role="performance",
        prefix="daily-performance-kb",
        quota_limit_bytes=100_000_000,
        embedding_model_id=embedding_id,
    )
    index_name = str(kb["index_name"])
    register_asset("performance", "upload_kb_index", index_name, owner_case_id="PERF-03")
    register_asset("performance", "large_kb_indices", [index_name], owner_case_id="PERF-04")


async def prepare_performance_embedding(identity) -> int:
    existing = resolve_asset("performance", "embedding_model_id", required=False)
    if existing:
        return int(existing)
    display_name = f"daily-performance-embedding-{uuid4().hex[:8]}"
    payload = model_request("embedding", display_name=display_name)
    payload["model_name"] = str(payload["model_name"]).split(",", 1)[0].strip()
    payload["base_url"] = str(payload["base_url"]).rstrip("/")
    if not payload["base_url"].endswith("/embeddings"):
        payload["base_url"] += "/embeddings"
    payload["expected_chunk_size"] = int(payload.get("expected_chunk_size") or 1024)
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        created = await api.post("/model/create", json=payload)
    assert_status(created, 200)
    async with client("config", token=identity.access_token) as api:
        listed = await api.get("/model/list")
    assert_status(listed, 200)
    match = next(
        (row for row in (listed.json().get("data") or []) if row.get("display_name") == display_name),
        None,
    )
    if not match:
        raise AssertionError(f"performance embedding model {display_name} not returned by /model/list")
    embedding_id = int(match.get("model_id") or match["id"])
    register_asset(
        "performance", "embedding_model_id", embedding_id, owner_case_id="PERF-04",
        cleanup={
            "service": "config", "identity": "tenant_a_admin", "method": "POST",
            "path": f"/model/delete?display_name={quote(display_name)}", "allowed_statuses": [200, 404],
        },
    )
    return embedding_id


async def prepare_large_attachment(identity) -> None:
    if resolve_asset("performance", "large_attachment_object_name", required=False):
        return
    # The preview endpoint supports documents, not MP4.  Generate a stable,
    # batch-independent text payload large enough to exercise HTTP ranges.
    filename = "controlled-large-preview.txt"
    payload = ("CONTROLLED_RANGE_PREVIEW\n" * 20_000).encode("utf-8")
    if len(payload) < 262_144:
        raise AssertionError("generated large attachment must be at least 256 KiB")
    async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        response = await api.post(
            "/file/storage",
            data={"folder": "attachments"},
            files=[("files", (filename, payload, "text/plain"))],
        )
    assert_status(response, 200)
    object_name = _object_name(response.json())
    register_asset(
        "performance",
        "large_attachment_object_name",
        object_name,
        owner_case_id="PERF-10",
        cleanup={
            "service": "runtime",
            "identity": "tenant_a_user",
            "method": "DELETE",
            "path": f"/file/storage/{quote(object_name, safe='/')}",
            "allowed_statuses": [200, 404],
        },
    )


async def prepare_fault_model(identity) -> None:
    if resolve_asset("reliability", "fault_model_id", required=False):
        return
    # The runner allocates a fresh port for every batch and exports the fully
    # resolved container-reachable URL.  A configured template URL is only a
    # fallback; hard-coding the historical 19192 port makes later D3/D5 calls
    # target a service that is no longer running.
    controlled_url = (
        os.getenv("NEXENT_TEST_ASSETS_URL")
        or os.getenv("NEXENT_TEST_ASSETS_CONTAINER_URL")
    )
    if not controlled_url:
        raise RuntimeError(
            "NEXENT_TEST_ASSETS_URL is required before preparing the controlled fault model"
        )
    controlled_url = controlled_url.rstrip("/")
    display_name = f"daily-fault-{uuid4().hex[:8]}"
    payload = model_request("llm", display_name=display_name)
    payload.update({
        "model_name": "controlled-fault-model",
        "api_key": "controlled-test-key",
        "base_url": f"{controlled_url}/fault/v1",
    })
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        created = await api.post("/model/create", json=payload)
    assert_status(created, 200)
    async with client("config", token=identity.access_token) as api:
        listed = await api.get("/model/list")
    assert_status(listed, 200)
    rows = listed.json().get("data") or []
    match = next((row for row in rows if row.get("display_name") == display_name), None)
    if not match:
        raise AssertionError(f"fault model {display_name} not returned by /model/list")
    fault_id = int(match.get("model_id") or match["id"])
    register_asset(
        "reliability",
        "fault_model_id",
        fault_id,
        owner_case_id="REL-02",
        cleanup={
            "service": "config",
            "identity": "tenant_a_admin",
            "method": "POST",
            "path": f"/model/delete?display_name={quote(display_name)}",
            "allowed_statuses": [200, 404],
        },
    )


async def prepare_evaluation_200(identity) -> None:
    if os.getenv("NEXENT_TEST_PREPARE_EVALUATION_200", "true").lower() != "true":
        return
    if resolve_asset("performance", "evaluation_200_run_id", required=False):
        return
    from d3.test_evaluation_scenarios import _create_set

    set_id = await _create_set(identity, name_prefix="daily-perf-200")
    register_asset(
        "performance", "evaluation_200_set_id", set_id, owner_case_id="PERF-06",
        cleanup={
            "service": "config", "identity": "tenant_a_admin", "method": "DELETE",
            "path": f"/evaluation-sets/{set_id}", "allowed_statuses": [200, 404, 409],
        },
    )

    semaphore = asyncio.Semaphore(12)

    async def add_case(index: int) -> None:
        async with semaphore:
            async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                response = await api.post(
                    f"/evaluation-sets/{set_id}/cases",
                    json={
                        "inputs": {"query": f"Reply with exact marker PERF_EVAL_{index:03d}"},
                        "label": {"answer": f"PERF_EVAL_{index:03d}"},
                    },
                )
            assert_status(response, 200)

    await asyncio.gather(*(add_case(index) for index in range(200)))
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        created = await api.post(
            "/agent-evaluations",
            json={
                "agent_id": int(resolve_asset("agents", "basic_id")),
                "judge_model_id": await model_id("llm", identity),
                "evaluation_set_id": set_id,
                "agent_version_no": 0,
            },
        )
    assert_status(created, 200)
    run_id = int((created.json().get("data") or {})["agent_evaluation_id"])
    register_asset(
        "performance", "evaluation_200_pending_run_id", run_id, owner_case_id="PERF-06",
        cleanup={
            "service": "config", "identity": "tenant_a_admin", "method": "DELETE",
            "path": f"/agent-evaluations/{run_id}", "allowed_statuses": [200, 404],
        },
    )
    status = ""
    for _ in range(600):
        async with client("config", token=identity.access_token) as api:
            detail = await api.get(f"/agent-evaluations/{run_id}")
        assert_status(detail, 200)
        status = str((detail.json().get("data") or {}).get("status") or "").upper()
        if status in {"COMPLETED", "SUCCEEDED", "SUCCESS", "FAILED", "CANCELED", "CANCELLED"}:
            break
        await asyncio.sleep(3)
    if status not in {"COMPLETED", "SUCCEEDED", "SUCCESS"}:
        raise AssertionError(f"200-case evaluation run {run_id} ended as {status or 'TIMEOUT'}")
    register_asset("performance", "evaluation_200_run_id", run_id, owner_case_id="PERF-06")


async def guarded(name: str, section: str, key: str, operation) -> None:
    try:
        await operation
    except Exception as exc:
        register_asset_failure(section, key, owner_case_id=name, reason=str(exc))
        print(f"{name}: FAILED: {exc}", flush=True)
    else:
        print(f"{name}: READY", flush=True)


async def main(case_ids: set[str] | None = None) -> None:
    admin = await sign_in("tenant_a_admin")
    user = await sign_in("tenant_a_user")
    operations = (
        ({"PERF-03", "PERF-04"}, "PERF-03", "performance", "upload_kb_index", prepare_knowledge(admin)),
        ({"PERF-10"}, "PERF-10", "performance", "large_attachment_object_name", prepare_large_attachment(user)),
        ({"REL-02"}, "REL-02", "reliability", "fault_model_id", prepare_fault_model(admin)),
        ({"PERF-06"}, "PERF-06", "performance", "evaluation_200_run_id", prepare_evaluation_200(admin)),
    )
    for owners, name, section, key, operation in operations:
        if case_ids is None or owners & case_ids:
            await guarded(name, section, key, operation)
        else:
            operation.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", default=[])
    arguments = parser.parse_args()
    asyncio.run(main(set(arguments.case) if arguments.case else None))
