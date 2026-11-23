# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from local_auth_http import bearer, register, seed_membership_roles
from local_auth_http import native_runtime as native_runtime, runtime as runtime


@pytest.mark.case_id("EVOLUTION-MCP-RESULT-D2-001")
@pytest.mark.stage("D2")
def test_tool_repair_http(runtime, monkeypatch):
    from backend.http.server.exception_handlers import register_exception_handlers
    from contracts.evolution import DevelopmentExperimentRequest
    from infrastructure.rdb.mcp_execution_records import McpRecord
    from nexent.core.agents.resources.replay_tools import argument_digest
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.api.evaluation.evolution import router
    from management.db.evaluation import experiments as jobs
    from management.db.evaluation.replay_cases import save_replay_case
    from management.services.evaluation import tool_repairs as repair
    from management.services.evaluation.experiments import snapshot_digest
    from management.thread_management import config_thread_manager
    from nexent.core.concurrency import set_default_thread_manager, clear_default_thread_manager
    from permissions.rbac import init_rbac

    identity, _, _, models = runtime
    load_system_configuration()
    login = register(identity)
    editor = login["user"]["id"]
    second = identity.post(
        "/api/user/signup",
        json={
            "email": "designer@example.com",
            "password": "Password123",
            "invite_code": "NATIVE-INVITE",
            "auto_login": True,
        },
    ).json()["data"]
    designer = second["user"]["id"]
    editor_header = bearer(login["session"]["access_token"])
    designer_header = bearer(second["session"]["access_token"])
    tenant, agent = "tenant-native", 12
    models.TableBase.metadata.create_all(db_client.engine)
    path = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with db_client.engine.begin() as conn, conn.connection.driver_connection.cursor() as cur:
        for n in (18, 19, 20, 25, 28):
            (file,) = path.glob(f"v2.9.0_{n:03}_*.sql")
            cur.execute(file.read_text(encoding="utf-8"))
    seed_membership_roles(editor, ["DEV"])
    seed_membership_roles(designer, ["DEV"])
    init_rbac()
    with get_db_session() as session:
        for version in (0, 1):
            session.add(
                models.AgentInfo(
                    agent_id=agent,
                    version_no=version,
                    tenant_id=tenant,
                    name="intake",
                    created_by=editor,
                    updated_by=editor,
                    delete_flag="N",
                    ingroup_permission="PRIVATE",
                )
            )
            session.flush()

        session.add(
            McpRecord(
                mcp_id=8,
                tenant_id=tenant,
                user_id=designer,
                created_by=designer,
                mcp_name="ledger",
                mcp_server="http://127.0.0.1:19974/mcp",
                enabled=True,
                status=True,
                delete_flag="N",
                group_ids="",
                ingroup_permission="READ_ONLY",
            )
        )
    binding = SimpleNamespace(
        tool_id="mcp",
        version="1",
        parameters={"tool_name": "post_receipt", "server_id": 8, "instance_id": 4, "revision": "a" * 64},
    )
    spec = SimpleNamespace(
        resource=SimpleNamespace(agent_id=agent, version_no=1, tools=[binding]),
        model_dump=lambda **kw: {
            "models": {"llm": {"alias": "pilot"}},
            "resource": {"model_alias": "pilot", "subagents": [], "tools": [binding.parameters]},
        },
    )
    digest = snapshot_digest(spec)
    records = {}
    for reference, correct in [("FIX1", False), ("KEEP2", True)]:
        args = {"reference": reference}
        expected = {
            "kind": "text",
            "value": "accepted",
            "fixture": {"initial": {"receipt": ""}, "final": {"receipt": reference}},
        }
        rule = {
            "name": "post_receipt",
            "min_calls": 1,
            "max_calls": 1,
            "arguments": args,
            "expected_mcp_reply": expected,
        }
        task = {
            "query": f"Record receipt {reference}",
            "expected": "accepted",
            "family": "ledger",
            "attachments": [],
            "tool_use": {"rules": [rule]},
        }
        case = save_replay_case(tenant, agent, 1, editor, task)
        observed = {
            "tool": "post_receipt",
            "remote": "post_receipt",
            "kind": "text",
            "error": False,
            "inputs": argument_digest(args),
            "before": argument_digest({"receipt": ""}),
            "after": argument_digest({"receipt": reference if correct else "bad"}),
            "content": argument_digest("accepted"),
            "exact_fields": True,
            "call": 1,
            "input_matches": True,
            "reply_matches": True,
            "state_matches": correct,
        }
        records[case["case_id"]] = (case["digest"], correct, observed)
    ids = list(records)

    def experiment(label):
        req = DevelopmentExperimentRequest(
            agent_id=agent,
            version_no=1,
            evaluator_id=1,
            case_ids=ids,
            candidate_type="baseline",
            request_id=label,
        )
        plan = {
            "request": req.model_dump(),
            "cases": {str(k): v[0] for k, v in records.items()},
            "snapshots": {"base": digest},
            "evaluator": {"version_no": 1},
        }
        eid = jobs.submit(tenant, editor, req, plan)
        while trial := jobs.claim(eid):
            case_digest, correct, observed = records[trial["case_id"]]
            status = "pass" if correct else "fail"
            assert jobs.finish(
                trial,
                status,
                {
                    "case_digest": case_digest,
                    "snapshot_digest": digest,
                    "tool_use": {
                        "status": status,
                        "issues": [] if correct else [{"tool": "post_receipt", "reason": "wrong_mcp_state"}],
                        "mcp_evidence": [{**observed, "after": "d" * 64} if label == "drift" else observed],
                    },
                },
            )
        return eid

    eid, repeat, drift = (experiment(label) for label in ("original", "repeat", "drift"))

    async def snapshot(*args):
        return spec

    monkeypatch.setattr(repair, "_snapshot", snapshot)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    config_thread_manager.start()
    set_default_thread_manager(config_thread_manager)
    try:
        with TestClient(app) as client:
            url = f"/api/agent-evolution/experiments/{eid}/tool-repair-feedback"
            body = {
                "tool_name": "post_receipt",
                "goal": "Preserve case in receipt",
                "failure_case_id": ids[0],
                "protection_case_id": ids[1],
                "repeat_experiment_id": repeat,
                "share_tool_examples": True,
            }
            assert client.post(url, headers=designer_header, json=body).status_code == 403
            assert (
                client.post(url, headers=editor_header, json={**body, "share_tool_examples": False}).status_code
                == 422
            )
            for other in (eid, drift):
                assert (
                    client.post(
                        url, headers=editor_header, json={**body, "repeat_experiment_id": other}
                    ).status_code
                    == 400
                )
            saved = client.post(url, headers=editor_header, json=body)
            assert saved.is_success, saved.text
            fid = saved.json()["data"]["feedback_id"]
            assert client.post(url, headers=editor_header, json=body).json()["data"]["feedback_id"] == fid
            read = f"/api/agent-evolution/feedback/{fid}/tool-repair-brief"
            assert client.get(read, headers=editor_header).status_code == 403
            brief = client.get(read, headers=designer_header).json()["data"]
            assert brief["failure"]["expected"]["fixture"]["final"] == {"receipt": "FIX1"}
            assert brief["protection"]["arguments"] == {"reference": "KEEP2"}
            suite = brief["test_suite"]
            assert suite["format"] == "nexent-mcp-repair-v1"
            assert (suite["failure"]["name"], suite["failure"]["expected_mcp_reply"]) == (
                "post_receipt",
                brief["failure"]["expected"],
            )
            assert "receipt_id" not in str(suite) and "binding_revision" not in str(suite)
            assert "query" not in str(brief) and "mcp_server" not in str(brief)
            seed_membership_roles(editor, ["ADMIN"])
            assert client.get(read, headers=editor_header).is_success
    finally:
        clear_default_thread_manager(config_thread_manager)
        asyncio.run(config_thread_manager.shutdown(timeout=5))
