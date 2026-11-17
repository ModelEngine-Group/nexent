# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Protect original records and own only a marked Workbench conversation."""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

from gateway.authentication.auth import generate_session_jwt
from management.db.client import get_db_session
from management.db.models import AgentInfo, ConversationMessage, ConversationMessageUnit, ConversationRecord


def rows(session, model, condition):
    return [{column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in session.query(model).filter(condition).order_by(*model.__table__.primary_key.columns)]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def original(session, state):
    return {model.__name__: digest(rows(session, model, model.conversation_id.in_(state["conversations"])))
            for model in (ConversationRecord, ConversationMessage, ConversationMessageUnit)} | {
        "agents": digest(rows(session, AgentInfo, AgentInfo.agent_id.in_(state["agents"])))}


def main():
    mode, filename = sys.argv[1:3]
    path = Path(filename)
    if mode == "setup":
        with get_db_session() as session:
            agent = session.query(AgentInfo).filter_by(agent_id=int(sys.argv[3]), version_no=0, delete_flag="N").one()
            state = {"actor": agent.created_by, "tenant": agent.tenant_id,
                     "marker": "WORKBENCH_HITL_" + path.stem[-12:],
                     "access_token": generate_session_jwt(agent.created_by, expires_in=1800),
                     "expires_at": int(time.time()) + 1800}
            state["conversations"] = [row.conversation_id for row in session.query(ConversationRecord)
                                      .filter_by(created_by=state["actor"])]
            state["agents"] = [row.agent_id for row in session.query(AgentInfo).filter_by(created_by=state["actor"])]
            state["original"] = original(session, state)
        path.write_text(json.dumps(state), encoding="utf-8")
        print(json.dumps({"setup": True}))
        return
    state = json.loads(path.read_text(encoding="utf-8"))
    if mode == "audit":
        cid = int(sys.argv[3])
        with get_db_session() as session:
            conversation = session.query(ConversationRecord).filter_by(
                conversation_id=cid, created_by=state["actor"]).one()
            assert cid not in state["conversations"]
            messages = rows(session, ConversationMessage, ConversationMessage.conversation_id == cid)
            assert any(state["marker"] in (row["message_content"] or "") for row in messages
                       if row["message_role"] == "user")
            units = rows(session, ConversationMessageUnit, ConversationMessageUnit.conversation_id == cid)
            print(json.dumps({"mode": (conversation.workbench_config or {}).get("mode"),
                              "messages_hash": digest(messages), "units_hash": digest(units),
                              "message_count": len(messages)}))
        return
    assert mode == "cleanup"
    with get_db_session() as session:
        assert original(session, state) == state["original"], "Original records changed"
        owned = [row.conversation_id for row in session.query(ConversationRecord).filter_by(
            created_by=state["actor"], delete_flag="N")
            if row.conversation_id not in state["conversations"] and session.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == row.conversation_id,
                ConversationMessage.message_content.contains(state["marker"])).first()]
    with httpx.Client(headers={"Authorization": "Bearer " + state["access_token"]},
                      trust_env=False, timeout=30) as client:
        for cid in owned:
            assert client.delete(f"http://nexent-runtime:5014/conversation/{cid}").status_code == 200
    with get_db_session() as session:
        assert original(session, state) == state["original"], "Cleanup changed original records"
        assert not session.query(ConversationRecord).filter(
            ConversationRecord.conversation_id.in_(owned), ConversationRecord.delete_flag == "N").count()
    path.unlink()
    print(json.dumps({"cleanup": True, "original_records_unchanged": True, "owned_conversations": len(owned)}))


if __name__ == "__main__":
    main()
