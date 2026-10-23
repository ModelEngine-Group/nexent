"""D3 evaluation-set, evaluator, run, result, annotation and report scenarios."""

from __future__ import annotations
from shared.factories.evaluation import _create_set, _delete_set
from shared.resource_ids import absent_numeric_id

import asyncio
from uuid import uuid4

import pytest

from d3.assets import asset_path, model_id, get_test_asset
from shared.cases import case_params
from shared.asset_registry import AssetTimeoutError, register_asset
from shared.http import MODEL_TIMEOUT, assert_status, client


CASES = [
    "API-132", "API-133", "API-134", "API-135", "API-136", "API-137",
    "AGT-057", "AGT-058", "API-138", "API-139", "AGT-059", "AGT-060",
    "AGT-061", "API-140", "API-141", "AGT-062", "AGT-063",
]


def _data(response) -> dict | list:
    return response.json().get("data")






async def _evaluation_set(identity, valid: bool) -> None:
    if not valid:
        async with client("config", token=identity.access_token) as api:
            blank = await api.post("/evaluation-sets", json={"name": "", "description": "invalid"})
            too_long = await api.post("/evaluation-sets", json={"name": "x" * 300})
            missing = await api.get(f"/evaluation-sets/{absent_numeric_id(__name__)}")
        assert_status(blank, (400, 422))
        assert_status(too_long, (400, 422))
        assert_status(missing, 404)
        return
    set_id = await _create_set(identity)
    try:
        async with client("config", token=identity.access_token) as api:
            listing = await api.get("/evaluation-sets", params={"limit": 50, "offset": 0})
            detail = await api.get(f"/evaluation-sets/{set_id}")
            empty_cases = await api.get(f"/evaluation-sets/{set_id}/cases")
        for response in (listing, detail, empty_cases):
            assert_status(response, 200)
        assert str(set_id) in listing.text
        assert empty_cases.json().get("total") == 0
    finally:
        await _delete_set(identity, set_id)


async def _evaluation_upload(identity, valid: bool) -> None:
    if not valid:
        async with client("config", token=identity.access_token) as api:
            response = await api.post(
                "/evaluation-sets/upload",
                data={"name": f"d3-invalid-{uuid4().hex[:8]}"},
                files=[("files", ("cases.txt", b"query,answer", "text/plain"))],
            )
        assert_status(response, (400, 422))
        return
    path = asset_path("files", "evaluation_excel")
    async with client("config", token=identity.access_token) as api:
        template = await api.get("/evaluation-sets/template")
        uploaded = await api.post(
            "/evaluation-sets/upload",
            data={"name": f"d3-upload-{uuid4().hex[:8]}", "description": "D3 Excel import"},
            files=[("files", (path.name, path.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        )
    assert_status(template, 200)
    assert template.content[:2] == b"PK"
    assert_status(uploaded, 200)
    set_id = int((_data(uploaded) or {}).get("evaluation_set_id") or (_data(uploaded) or {}).get("id"))
    try:
        async with client("config", token=identity.access_token) as api:
            exported = await api.get(f"/evaluation-sets/{set_id}/export")
        assert_status(exported, 200)
        assert exported.content[:2] == b"PK"
    finally:
        await _delete_set(identity, set_id)


async def _case_crud(identity, valid: bool) -> None:
    set_id = await _create_set(identity, name_prefix="d3-case")
    try:
        async with client("config", token=identity.access_token) as api:
            if not valid:
                missing = await api.put(f"/evaluation-sets/{set_id}/cases/{absent_numeric_id(__name__)}", json={"inputs": {"query": "x"}})
                oversized = await api.post(
                    f"/evaluation-sets/{set_id}/cases", json={"inputs": {"query": "q" * 100_000}, "label": {"answer": "a"}},
                )
                assert_status(missing, 404)
                assert_status(oversized, (400, 422))
                return
            created = await api.post(
                f"/evaluation-sets/{set_id}/cases",
                json={"inputs": {"query": "What is D3?"}, "label": {"answer": "Scenario integration"}, "session_id": "d3-session", "turn_order": 1},
            )
            assert_status(created, 200)
            created_list = await api.get(f"/evaluation-sets/{set_id}/cases")
            assert_status(created_list, 200)
            created_rows = created_list.json().get("data") or []
            assert len(created_rows) == 1
            case_id = int(created_rows[0]["evaluation_set_case_id"])
            updated = await api.put(
                f"/evaluation-sets/{set_id}/cases/{case_id}",
                json={"inputs": {"query": "What is D3 automation?"}, "label": {"answer": "A real integration stage"}},
            )
            listed = await api.get(f"/evaluation-sets/{set_id}/cases", params={"query": "automation"})
            second = await api.post(
                f"/evaluation-sets/{set_id}/cases", json={"inputs": {"query": "Second"}, "label": {"answer": "Second answer"}},
            )
            assert_status(second, 200)
            all_rows_response = await api.get(f"/evaluation-sets/{set_id}/cases", params={"limit": 200})
            assert_status(all_rows_response, 200)
            all_rows = all_rows_response.json().get("data") or []
            second_id = int(next(row["evaluation_set_case_id"] for row in all_rows if int(row["evaluation_set_case_id"]) != case_id))
            batch = await api.post(f"/evaluation-sets/{set_id}/cases/batch-delete", json={"case_ids": [second_id]})
            deleted = await api.delete(f"/evaluation-sets/{set_id}/cases/{case_id}")
        for response in (updated, listed, second, batch, deleted):
            assert_status(response, 200)
        assert listed.json().get("total") == 1
    finally:
        await _delete_set(identity, set_id)


async def _generate_cases(identity, dependency_failure: bool) -> None:
    payload = {
        "description": "Generate deterministic health-check questions for the configured basic Agent.",
        "count": 2,
        "model_id": absent_numeric_id(__name__) if dependency_failure else await model_id("llm", identity),
        "agent_id": int(get_test_asset("agents", "basic_id")),
        "agent_version_no": 0,
        "set_name": f"d3-generated-{uuid4().hex[:8]}",
    }
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        response = await api.post("/evaluation-sets/generate-cases-async", json=payload)
    if dependency_failure:
        assert_status(response, (200, 400, 404, 500, 502, 503, 504))
        return
    assert_status(response, 200)
    set_id = int((_data(response) or {})["evaluation_set_id"])
    try:
        async with client("config", token=identity.access_token) as api:
            detail = await api.get(f"/evaluation-sets/{set_id}")
        assert_status(detail, 200)
        assert (_data(detail) or {}).get("generation_status") in {"GENERATING", "COMPLETED", "FAILED"}
    finally:
        await _delete_set(identity, set_id)


async def _evaluator(identity, valid: bool) -> None:
    if not valid:
        async with client("config", token=identity.access_token) as api:
            range_error = await api.post(
                "/evaluators", json={"name": "invalid", "evaluator_type": "llm", "score_range_min": 10, "score_range_max": 1},
            )
            missing = await api.get(f"/evaluators/{absent_numeric_id(__name__)}")
        assert_status(range_error, 422)
        assert_status(missing, 404)
        return
    name = f"d3-evaluator-{uuid4().hex[:8]}"
    async with client("config", token=identity.access_token) as api:
        created = await api.post(
            "/evaluators",
            json={
                "name": name, "description": "D3 deterministic evaluator", "evaluator_type": "code",
                "code": (
                    "def evaluate(query, expected, actual, runtime_events, **kwargs):\n"
                    "    return {'score': 1.0, 'reason': 'ok'}"
                ),
                "score_range_min": 0, "score_range_max": 1, "pass_threshold": 0.8,
                "input_fields": [{"name": "output", "required": True}],
            },
        )
        assert_status(created, 200)
        evaluator_id = int((_data(created) or {}).get("evaluator_id") or (_data(created) or {}).get("id"))
        fetched = await api.get(f"/evaluators/{evaluator_id}")
        updated = await api.put(f"/evaluators/{evaluator_id}", json={"description": "D3 updated"})
        versions = await api.get(f"/evaluators/{evaluator_id}/versions")
        listing = await api.get("/evaluators", params={"source": "custom", "evaluator_type": "code"})
        deleted = await api.delete(f"/evaluators/{evaluator_id}")
    for response in (fetched, updated, versions, listing, deleted):
        assert_status(response, 200)
    assert name in listing.text


async def _evaluation_run(identity, mode: str) -> None:
    if mode == "boundary":
        async with client("config", token=identity.access_token) as api:
            missing = await api.get(f"/agent-evaluations/{absent_numeric_id(__name__)}")
            invalid = await api.post("/agent-evaluations", json={"agent_id": absent_numeric_id(__name__), "judge_model_id": absent_numeric_id(__name__), "query_count": 0})
        assert_status(missing, 404)
        assert_status(invalid, (400, 404, 422))
        return
    set_id = await _create_set(identity, name_prefix="d3-run")
    retained = False
    try:
        async with client("config", token=identity.access_token) as api:
            seeded = await api.post(
                f"/evaluation-sets/{set_id}/cases",
                json={"inputs": {"query": "Reply D3_EVAL_OK"}, "label": {"answer": "D3_EVAL_OK"}},
            )
        assert_status(seeded, 200)
        judge = absent_numeric_id(__name__) if mode == "dependency" else await model_id("llm", identity)
        # From this point POST may commit a PENDING run even when background
        # dispatch fails and the API returns 500. Leave set/run cleanup to the
        # registry, which can discover a partial run by this exact owned set.
        retained = True
        async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
            created = await api.post(
                "/agent-evaluations",
                json={"agent_id": int(get_test_asset("agents", "basic_id")), "judge_model_id": judge, "evaluation_set_id": set_id, "agent_version_no": 0},
            )
        if created.status_code == 200:
            created_data = _data(created) or {}
            run_id = int(created_data["agent_evaluation_id"])
            register_asset(
                "evaluation", "completed_run_id", run_id, owner_case_id="AGT-059",
                cleanup={
                    "service": "config", "identity": "tenant_a_admin", "method": "DELETE",
                    "path": f"/agent-evaluations/{run_id}", "allowed_statuses": [200, 404],
                },
            )
            register_asset("evaluation", "completed_set_id", set_id, owner_case_id="AGT-059")
        if mode == "dependency":
            assert_status(created, (200, 400, 404, 500, 502, 503, 504))
            return
        assert_status(created, 200)

        # Assertion 6: the run executes inside the runtime process. The only
        # legal way into the runtime dispatch endpoint is the internal JWT, so
        # user-token and anonymous probes must fail closed at that boundary
        # while the background dispatch already performed PENDING->RUNNING.
        async with client("runtime", token=identity.access_token) as api:
            user_token_dispatch = await api.post(
                "/agent-evaluations/internal/run",
                json={"agent_evaluation_id": run_id},
            )
        assert_status(user_token_dispatch, 401)
        async with client("runtime") as api:
            anonymous_dispatch = await api.post(
                "/agent-evaluations/internal/run",
                json={"agent_evaluation_id": run_id},
            )
        assert_status(anonymous_dispatch, 401)

        detail = None
        observed: list[str] = []
        for _ in range(100):
            async with client("config", token=identity.access_token) as api:
                detail = await api.get(f"/agent-evaluations/{run_id}")
            assert_status(detail, 200)
            status = str((_data(detail) or {}).get("status") or "").upper()
            if status and (not observed or observed[-1] != status):
                observed.append(status)
            if status in {"COMPLETED", "SUCCEEDED", "SUCCESS", "FAILED", "CANCELED", "CANCELLED"}:
                break
            await asyncio.sleep(3)
        else:
            raise AssetTimeoutError(f"evaluation run {run_id} did not finish within 300 seconds")
        assert status in {"COMPLETED", "SUCCEEDED", "SUCCESS"}, f"evaluation run ended as {status}"
        assert "RUNNING" in observed, (
            f"runtime dispatch never moved the run through PENDING->RUNNING: {observed}"
        )
        assert "PENDING" not in observed[observed.index("RUNNING") + 1:], (
            f"status must never regress after the atomic claim: {observed}"
        )

        # Agent version binding is frozen at creation and stays stable.
        bound_version = (_data(detail) or {}).get("agent_version_no")
        assert bound_version is not None
        assert bound_version == created_data.get("agent_version_no"), (
            "evaluation run must keep the agent version bound at creation"
        )

        # A single effective dispatch: exactly one result row per seeded case.
        async with client("config", token=identity.access_token) as api:
            case_rows = await api.get(f"/agent-evaluations/{run_id}/cases", params={"limit": 100, "offset": 0})
        assert_status(case_rows, 200)
        case_payload = _data(case_rows) or {}
        rows = case_payload.get("data") if isinstance(case_payload, dict) else case_payload
        rows = rows if isinstance(rows, list) else (case_payload.get("items") or [])
        assert len(rows) == 1, (
            f"one seeded case must yield exactly one result row (claim ran once): {rows}"
        )
        async with client("config", token=identity.access_token) as api:
            listing = await api.get("/agent-evaluations", params={"agent_id": int(get_test_asset("agents", "basic_id"))})
        for response in (detail, listing):
            assert_status(response, 200)
    finally:
        if not retained:
            await _delete_set(identity, set_id)


async def _results(identity) -> None:
    run_id = int(get_test_asset("evaluation", "completed_run_id"))
    async with client("config", token=identity.access_token) as api:
        cases = await api.get(
            f"/agent-evaluations/{run_id}/cases",
            params={"limit": 10, "offset": 0, "sort_order": "desc", "pass_filter": "pass"},
        )
        stats = await api.get(f"/agent-evaluations/{run_id}/stats")
    assert_status(cases, 200)
    assert_status(stats, 200)
    assert isinstance(_data(cases), dict)
    stats_data = _data(stats) or {}
    assert {"pass_count", "fail_count", "total"}.issubset(stats_data)


async def _annotations(identity) -> None:
    name = f"d3-schema-{uuid4().hex[:8]}"
    async with client("config", token=identity.access_token) as api:
        created = await api.post(
            "/evaluation-annotations/schemas",
            json={"name": name, "description": "D3 annotation", "annotation_type": "classification", "options": [{"label": "good", "value": "good"}]},
        )
        assert_status(created, 200)
        schema_id = int((_data(created) or {}).get("schema_id") or (_data(created) or {}).get("id"))
        listing = await api.get("/evaluation-annotations/schemas")
        updated = await api.put(f"/evaluation-annotations/schemas/{schema_id}", json={"description": "D3 updated schema"})
        deleted = await api.delete(f"/evaluation-annotations/schemas/{schema_id}")
    for response in (listing, updated, deleted):
        assert_status(response, 200)
    assert name in listing.text


async def _analysis_report(identity, dependency_failure: bool) -> None:
    run_id = int(get_test_asset("evaluation", "completed_run_id"))
    async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        analyzed = await api.post(f"/agent-evaluations/{run_id}/analyze", params={"force": dependency_failure})
        if dependency_failure:
            assert_status(analyzed, (200, 409, 500, 502, 503, 504))
            return
        cached = await api.post(f"/agent-evaluations/{run_id}/analyze", params={"force": False})
        report = await api.get(f"/agent-evaluations/{run_id}/report")
    assert_status(analyzed, 200)
    assert_status(cached, 200)
    assert_status(report, 200)
    assert report.content.startswith(b"%PDF")
    assert report.headers.get("content-type", "").startswith("application/pdf")


@pytest.mark.asyncio
async def execute_d3_evaluation(case, tenant_a_admin):
    case_id = case["id"]
    if case_id in {"API-132", "API-133"}:
        await _evaluation_set(tenant_a_admin, case_id == "API-132")
    elif case_id in {"API-134", "API-135"}:
        await _evaluation_upload(tenant_a_admin, case_id == "API-134")
    elif case_id in {"API-136", "API-137"}:
        await _case_crud(tenant_a_admin, case_id == "API-136")
    elif case_id in {"AGT-057", "AGT-058"}:
        await _generate_cases(tenant_a_admin, case_id == "AGT-058")
    elif case_id in {"API-138", "API-139"}:
        await _evaluator(tenant_a_admin, case_id == "API-138")
    elif case_id in {"AGT-059", "AGT-060", "AGT-061"}:
        await _evaluation_run(tenant_a_admin, {"AGT-059": "core", "AGT-060": "boundary", "AGT-061": "dependency"}[case_id])
    elif case_id == "API-140":
        await _results(tenant_a_admin)
    elif case_id == "API-141":
        await _annotations(tenant_a_admin)
    elif case_id in {"AGT-062", "AGT-063"}:
        await _analysis_report(tenant_a_admin, case_id == "AGT-063")
    else:
        raise AssertionError(f"unmapped D3 case {case_id}")
