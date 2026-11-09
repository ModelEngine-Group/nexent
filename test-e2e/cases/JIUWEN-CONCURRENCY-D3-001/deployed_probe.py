# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Verify every deployed child attempt; own only newly created conversations."""

import asyncio
import hashlib
import json
import sys
import threading
import time
from uuid import uuid4

import httpx

from gateway.authentication.auth import generate_session_jwt
from management.db.client import get_db_session
from management.db.models import AgentInfo, AgentRelation, ConversationMessage, ConversationMessageUnit, ConversationRecord, ModelRecord
from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def records(session, model, condition):
    return [{column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in session.query(model).filter(condition).order_by(*model.__table__.primary_key.columns)]


def unpack(value):
    for _ in range(3):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return {}
        if isinstance(value, dict) and "status" not in value and isinstance(value.get("content"), str):
            value = value["content"]
        else:
            break
    return value if isinstance(value, dict) else {}


def main():
    config = json.loads(sys.argv[1])
    source, model_id = int(config["source_agent_id"]), int(config["model_id"])
    report = {"status": "FAIL", "runs": [], "cleanup": False}
    owned, sent, clients, seen = set(), set(), set(), set()
    guard = threading.RLock()
    prefix = "JIUWEN_CONCURRENCY_" + uuid4().hex
    with get_db_session() as session:
        draft = session.query(AgentInfo).filter_by(agent_id=source, version_no=0, delete_flag="N").one()
        assert model_id in draft.model_ids
        actor, tenant = draft.created_by, draft.tenant_id
        children = {row.selected_agent_id for row in session.query(AgentRelation).filter_by(
            parent_agent_id=source, version_no=draft.current_version_no or 0, delete_flag="N")}
        assert len(children) == 3
        source_ids = children | {source}
        definitions = records(session, AgentInfo, AgentInfo.agent_id.in_(source_ids))
        outlet_ids = {identifier for row in definitions for identifier in row.get("model_ids") or []}
        originals = {row.conversation_id for row in session.query(ConversationRecord).filter_by(agent_id=source)}

        def snapshot(db):
            return {
                "agents": digest(records(db, AgentInfo, AgentInfo.agent_id.in_(source_ids))),
                "models": digest(records(db, ModelRecord, ModelRecord.model_id.in_(outlet_ids))),
                "history": {model.__name__: digest(records(db, model, model.conversation_id.in_(originals)))
                            for model in (ConversationRecord, ConversationMessage, ConversationMessageUnit)},
            }

        before = snapshot(session)
    headers = {"Authorization": "Bearer " + generate_session_jwt(actor, expires_in=3600)}
    manager = ThreadManager("deployed-concurrency-client", {
        "client": LanePolicy(name="client", max_workers=2, max_queue_size=2)})
    manager.start()
    cids = [None, None]

    def invoke(slot, batch):
        query = f"Execute your configured A/B/C parallel sandbox regression. New task {prefix}:{slot}:{batch}."
        with guard:
            sent.add(query)
        body = {"agent_id": source, "model_id": model_id, "query": query, "history": []}
        if cids[slot] is None:
            body["model_parameter_preferences"] = {str(model_id): {"enable_thinking": False}}
        else:
            body["conversation_id"] = cids[slot]
        with httpx.Client(base_url="http://nexent-runtime:5014", headers=headers, trust_env=False, timeout=240) as client:
            with guard:
                clients.add(client)
            try:
                events = []
                with client.stream("POST", "/agent/run", json=body) as response:
                    if response.headers.get("conversation_id"):
                        cids[slot] = int(response.headers["conversation_id"])
                        assert cids[slot] not in originals
                        with guard:
                            owned.add(cids[slot])
                    assert response.status_code == 200, "Agent request did not start"
                    for line in response.iter_lines():
                        if line.startswith("data:"):
                            events.append(json.loads(line[5:].strip()))
                starts = [e for e in events if e.get("type") == "subagent_start"]
                ends = [e for e in events if e.get("type") == "subagent_end"]
                terminals = [e for e in events if e.get("type") == "run_terminal"]
                nested = [e for e in terminals if e.get("invocation_id")]
                roots = [e for e in terminals if not e.get("invocation_id")]
                start_ids = {e["invocation_id"] for e in starts}
                end_ids = {e["invocation_id"] for e in ends}
                child_ids = {e["invocation_id"] for e in nested}
                payloads = [unpack(e["content"]) for e in starts]
                final = "".join(str(e.get("content", "")) for e in events
                                if e.get("type") == "final_answer" and not e.get("invocation_id"))
                summary = {"slot": slot, "round": batch, "root_statuses": [e.get("status") for e in roots],
                           "child_statuses": [e.get("status") for e in nested], "child_count": len(nested),
                           "starts": len(starts), "ends": len(ends), "has_results": all(
                               value in final for value in config.get("expected_values", ["11", "22", "33"])),
                           "loop_errors": "bound to a different event loop" in str(events)}
                with guard:
                    report["runs"].append(summary)
                assert len(roots) == 1 and roots[0].get("status") == "completed", "Root did not complete"
                assert len(starts) == len(ends) == len(nested) == 3, "Extra or missing child attempt"
                assert start_ids == end_ids == child_ids, "Invocation boundaries do not match"
                assert {e["agent_id"] for e in payloads} == children, "Unexpected child identity"
                assert all(e.get("status") == "completed" for e in nested), "A child failed before recovery"
                assert not [e for e in events if e.get("type") == "error"], "Execution emitted an error"
                assert not summary["loop_errors"] and summary["has_results"], "Wrong result or loop failure"
                with guard:
                    assert not seen & start_ids, "Invocation identity reused across runs"
                    seen.update(start_ids)
                cid = cids[slot]
                for _ in range(30):
                    with get_db_session() as session:
                        messages = records(session, ConversationMessage, ConversationMessage.conversation_id == cid)
                        if len(messages) == (batch + 1) * 2 and all(m["status"] == "completed" for m in messages):
                            units = records(session, ConversationMessageUnit, ConversationMessageUnit.conversation_id == cid)
                            break
                    time.sleep(0.1)
                else:
                    raise AssertionError("History did not reach a completed state")
                saved_ids = {u["invocation_id"] for u in units if u["unit_type"] == "run_terminal"
                             and u["invocation_id"] in child_ids and unpack(u["unit_content"]).get("status") == "completed"}
                assert saved_ids == child_ids, "Child terminal history differs from live events"
                prior = digest([messages, units])
                history = client.get(f"/conversation/{cid}")
                assert history.status_code == 200 and all(value in history.text for value in child_ids)
                with get_db_session() as session:
                    current = [records(session, ConversationMessage, ConversationMessage.conversation_id == cid),
                               records(session, ConversationMessageUnit, ConversationMessageUnit.conversation_id == cid)]
                assert digest(current) == prior, "History load rewrote messages or units"
                summary["history_matches"] = True
            finally:
                with guard:
                    clients.discard(client)

    try:
        with httpx.Client(base_url="http://nexent-config:5010", headers=headers, trust_env=False, timeout=30) as client:
            assert client.get("/tenant_config/deployment_version").json()["agent_core"] == "jiuwen"
        for batch in range(3):
            futures = [manager.submit("client", ManagedTaskSpec(task_name=f"probe-{batch}-{slot}", owner=__name__),
                                      invoke, slot, batch) for slot in range(2)]
            for execution in futures:
                execution.future.result(timeout=300)
        report["status"] = "PASS"
    except Exception as error:
        report["failure_type"] = type(error).__name__
        report["failure"] = str(error)[:180] if isinstance(error, AssertionError) else "Probe execution failed"
    finally:
        # Recover only IDs proven by this Case's unpredictable exact request texts.
        with get_db_session() as session:
            matches = session.query(ConversationMessage.conversation_id).filter(
                ConversationMessage.message_content.in_(sent), ConversationMessage.created_by == actor).all()
            owned.update(row.conversation_id for row in matches if row.conversation_id not in originals)
        with httpx.Client(base_url="http://nexent-runtime:5014", headers=headers, trust_env=False, timeout=30) as client:
            if report["status"] != "PASS":
                for cid in owned:
                    client.get(f"/agent/stop/{cid}")
            with guard:
                for active in tuple(clients):
                    active.close()
            drained = asyncio.run(manager.shutdown(timeout=10))
            assert not drained.stuck_execution_ids
            for cid in owned:
                with get_db_session() as session:
                    row = session.query(ConversationRecord).filter_by(conversation_id=cid).one()
                    assert row.agent_id == source and row.created_by == actor and cid not in originals
                assert client.delete(f"/conversation/{cid}").status_code == 200
        with get_db_session() as session:
            report["source_unchanged"] = snapshot(session) == before
        report["cleanup"] = manager.snapshot().active_count == 0
        report["owned_conversations_cleaned"] = len(owned)
        print("CONCURRENCY_RESULT=" + json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
