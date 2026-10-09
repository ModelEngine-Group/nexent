"""D5 bounded performance and concurrency checks with configurable thresholds."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

import pytest

from d3.assets import temporary_conversation, get_test_asset
from d5.assets import Stopwatch, asset_path, threshold_ms
from shared.cases import special_case_params
from shared.config import controlled_asset_url
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.sse import assert_terminal_event, read_sse
from shared.factories.files import register_uploaded_files


CASES = [f"PERF-{number:02d}" for number in range(1, 11) if number != 6]


async def _agent_run(identity, marker: str) -> list[dict]:
    async with temporary_conversation(identity, f"D5 performance {marker}") as conversation_id:
        async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            async with api.stream(
                "POST", "/agent/run",
                json={
                    "agent_id": int(get_test_asset("agents", "basic_id")), "conversation_id": conversation_id,
                    "history": [], "is_debug": True, "query": f"Reply with exact marker {marker}.",
                },
            ) as response:
                assert_status(response, 200)
                return await read_sse(response, limit=2000)


async def _parallel_agents(identity) -> None:
    concurrency = int(get_test_asset("performance", "agent_concurrency", required=False) or 3)
    with Stopwatch() as timer:
        results = await asyncio.gather(*[_agent_run(identity, f"D5_PARALLEL_{i}") for i in range(concurrency)])
    assert timer.elapsed_ms <= threshold_ms("parallel_agent_p95_ms", 300_000)
    for index, events in enumerate(results):
        assert_terminal_event(events)
        assert f"d5_parallel_{index}" in json.dumps(events, ensure_ascii=False).lower()


async def _sse_concurrency(identity) -> None:
    concurrency = int(get_test_asset("performance", "sse_concurrency", required=False) or 5)
    with Stopwatch() as timer:
        results = await asyncio.gather(*[_agent_run(identity, f"D5_SSE_{i}") for i in range(concurrency)])
    assert timer.elapsed_ms <= threshold_ms("sse_batch_ms", 300_000)
    assert all(any(event.get("event") or event.get("type") for event in events) for events in results)


async def _large_upload(identity) -> None:
    path = asset_path("files", "large_document")
    copies = int(get_test_asset("performance", "upload_file_count", required=False) or 3)
    files = [("file", (f"{index}-{path.name}", path.read_bytes(), "application/octet-stream")) for index in range(copies)]
    with Stopwatch() as timer:
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            response = await api.post(
                "/file/upload",
                data={"destination": "minio", "folder": "knowledge_base", "index_name": str(get_test_asset("performance", "upload_kb_index"))},
                files=files,
            )
    if response.status_code in (200,207):
        register_uploaded_files(identity,response.json(),index_name=str(get_test_asset('performance','upload_kb_index')))
    assert_status(response, (200, 207))
    assert timer.elapsed_ms <= threshold_ms("multi_upload_ms", 180_000)
    body = response.json()
    assert len(body.get("file_records") or []) == copies
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        for record in body["file_records"]:
            cleanup = await api.delete(
                f"/indices/{get_test_asset('performance', 'upload_kb_index')}/documents",
                params={"file_id": record["file_id"], "scope": "full"},
            )
            assert_status(cleanup, (200, 404))


async def _vector_search(identity) -> None:
    indices = get_test_asset("performance", "large_kb_indices")
    assert isinstance(indices, list) and indices
    queries = get_test_asset("performance", "search_queries", required=False) or ["Nexent architecture", "agent configuration", "knowledge retrieval"]

    async def search(query: str):
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            response = await api.post(
                "/indices/search/hybrid", json={"query": query, "index_names": indices, "top_k": 20, "weight_accurate": 0.5},
            )
        assert_status(response, 200)
        return response

    with Stopwatch() as timer:
        responses = await asyncio.gather(*[search(str(query)) for query in queries])
    assert timer.elapsed_ms <= threshold_ms("vector_search_batch_ms", 60_000)
    assert all(response.json() for response in responses)


async def _scheduler_load(identity) -> None:
    concurrency = int(get_test_asset("performance", "scheduler_read_concurrency", required=False) or 10)

    async def listing(page: int):
        async with client("runtime", token=identity.access_token) as api:
            response = await api.get("/agent/automations", params={"page": page, "page_size": 100})
        assert_status(response, 200)
        return response.json()

    with Stopwatch() as timer:
        pages = await asyncio.gather(*[listing((index % 3) + 1) for index in range(concurrency)])
    assert timer.elapsed_ms <= threshold_ms("scheduler_listing_ms", 10_000)
    assert all((page.get("data") is not None) for page in pages)


async def _evaluation_200(identity) -> None:
    from shared.factories.evaluation import prepare_completed_run
    from shared.asset_registry import runtime_dir

    # Verify the model-backed evaluation path before launching 200 calls.
    probe_id = await prepare_completed_run(
        identity, owner="PERF-06", section="performance", key="evaluation_probe_run_id",
    )
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        probe = await api.get(f"/agent-evaluations/{probe_id}/cases")
    assert_status(probe, 200)
    probe_rows = (probe.json().get("data") or {}).get("items", [])
    (runtime_dir(required=True) / "perf-06-evaluation-probe.json").write_text(
        json.dumps({"run_id": probe_id, "cases": probe_rows}, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    assert len(probe_rows) == 1
    assert probe_rows[0].get("status") == "COMPLETED", (
        "Evaluation smoke failed before the 200-case workload: "
        + str(probe_rows[0].get("error_message") or probe_rows[0].get("status"))
    )
    # Own exactly 200 cases instead of depending on a stale external run ID.
    run_id = await prepare_completed_run(
        identity, owner="PERF-06", case_count=200,
        section="performance", key="evaluation_200_run_id",
    )
    samples = []
    # The first request warms caches; measure three independent batches.
    for attempt in range(4):
        with Stopwatch() as timer:
            async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                pages = await asyncio.gather(*[
                    api.get(f"/agent-evaluations/{run_id}/cases", params={"limit": 50, "offset": offset})
                    for offset in (0, 50, 100, 150)
                ])
                stats = await api.get(f"/agent-evaluations/{run_id}/stats")
                report = await api.get(f"/agent-evaluations/{run_id}/report")
        for response in pages:
            assert_status(response, 200)
        assert_status(stats, 200)
        assert_status(report, 200)
        rows = [row for response in pages for row in (response.json().get("data") or {}).get("items", [])]
        assert len(rows) == 200
        assert len({row["agent_evaluation_case_id"] for row in rows}) == 200
        summary = stats.json().get("data") or {}
        assert summary.get("total") == 200
        assert summary.get("pass_count", 0) + summary.get("fail_count", 0) == 200
        assert report.content.startswith(b"%PDF")
        if attempt:
            samples.append(timer.elapsed_ms)
    measurements = {
        "run_id": run_id, "case_count": 200, "warmup_batches": 1,
        "samples_ms": samples, "max_ms": max(samples),
        "threshold_ms": threshold_ms("evaluation_report_ms", 60_000),
        "scope": "Four concurrent pagination reads, statistics and PDF export; three measured batches",
    }
    (runtime_dir(required=True) / "perf-06-measurements.json").write_text(
        json.dumps(measurements, indent=2), encoding="utf-8",
    )
    assert max(samples) <= measurements["threshold_ms"]


async def _memory_budget(identity) -> None:
    long_query = "memory budget probe " * 500
    with Stopwatch() as timer:
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            response = await api.get(
                "/memory/context",
                params={"query": long_query, "agent_id": str(get_test_asset("agents", "basic_id")), "top_k": 100, "threshold": 0.0},
            )
    assert_status(response, 200)
    assert timer.elapsed_ms <= threshold_ms("memory_context_ms", 30_000)
    prompt = response.json().get("prompt_text") or ""
    assert len(prompt) <= int(get_test_asset("performance", "memory_prompt_max_chars", required=False) or 100_000)


async def _mcp_listing(identity) -> None:
    concurrency = int(get_test_asset("performance", "mcp_listing_concurrency", required=False) or 10)

    async def fetch(path: str):
        async with client("config", token=identity.access_token) as api:
            response = await api.get(path)
        assert_status(response, 200)
        return response

    with Stopwatch() as timer:
        responses = await asyncio.gather(*[
            fetch("/mcp/list") for _ in range(concurrency)
        ])
    assert timer.elapsed_ms <= threshold_ms("mcp_listing_ms", 15_000)
    assert all(len(response.content) < 10_000_000 for response in responses)


async def _markdown_page() -> None:
    url = controlled_asset_url(str(get_test_asset("performance", "large_markdown_page_path")))
    with Stopwatch() as timer:
        async with client("runtime", timeout=MODEL_TIMEOUT) as api:
            response = await api.get(url) if url.startswith("/") else None
    if response is None:
        import httpx
        with Stopwatch() as timer:
            async with httpx.AsyncClient(timeout=MODEL_TIMEOUT) as web:
                response = await web.get(url)
    assert_status(response, 200)
    assert timer.elapsed_ms <= threshold_ms("large_markdown_page_ms", 10_000)
    assert len(response.content) > 1000


async def _range_preview(identity) -> None:
    object_name = str(get_test_asset("performance", "large_attachment_object_name"))
    path = f"/file/preview/{quote(object_name, safe='/')}"
    with Stopwatch() as timer:
        async with client("config", token=identity.access_token) as api:
            responses = await asyncio.gather(*[
                api.get(path, headers={"Range": f"bytes={offset}-{offset + 65535}"})
                for offset in (0, 65536, 131072, 196608)
            ])
    assert timer.elapsed_ms <= threshold_ms("range_preview_ms", 10_000)
    for response in responses:
        assert_status(response, 206)
        assert len(response.content) == 65536
        assert response.headers.get("content-range", "").startswith("bytes ")


@pytest.mark.asyncio
async def execute_d5_performance_special(case, tenant_a_user, tenant_a_admin):
    handlers = {
        "PERF-01": lambda: _parallel_agents(tenant_a_user),
        "PERF-02": lambda: _sse_concurrency(tenant_a_user),
        "PERF-03": lambda: _large_upload(tenant_a_admin),
        "PERF-04": lambda: _vector_search(tenant_a_admin),
        "PERF-05": lambda: _scheduler_load(tenant_a_user),
        "PERF-06": lambda: _evaluation_200(tenant_a_admin),
        "PERF-07": lambda: _memory_budget(tenant_a_user),
        "PERF-08": lambda: _mcp_listing(tenant_a_admin),
        "PERF-09": _markdown_page,
        "PERF-10": lambda: _range_preview(tenant_a_user),
    }
    await handlers[case["id"]]()
