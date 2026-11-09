# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own only a uniquely named creator conversation and Skill; never expose auth."""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

from gateway.authentication.auth import generate_session_jwt
from management.db.client import get_db_session
from management.db.models import AgentInfo, ConversationMessage, ConversationMessageUnit, ConversationRecord, SkillInfo


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def records(session, model, condition):
    return [{c.name: getattr(r, c.name) for c in model.__table__.columns}
            for r in session.query(model).filter(condition).order_by(*model.__table__.primary_key.columns)]


def original(session, state):
    return {model.__name__: digest(records(session, model, model.conversation_id.in_(state["original_conversations"])))
            for model in (ConversationRecord, ConversationMessage, ConversationMessageUnit)}


def main():
    mode, filename = sys.argv[1:3]
    path = Path(filename)
    if mode == "setup":
        with get_db_session() as session:
            agent = session.query(AgentInfo).filter_by(agent_id=int(sys.argv[3]), version_no=0, delete_flag="N").one()
            suffix = path.stem[-12:]
            state = {"actor": agent.created_by, "tenant": agent.tenant_id, "name": "skill-history-" + suffix,
                     "marker": "CREATOR_HISTORY_" + suffix, "access_token": generate_session_jwt(agent.created_by, expires_in=1800),
                     "expires_at": int(time.time()) + 1800}
            state["original_conversations"] = [r.conversation_id for r in session.query(ConversationRecord)
                                                .filter_by(created_by=state["actor"])]
            state["original_hashes"] = original(session, state)
        path.write_text(json.dumps(state), encoding="utf-8")
        print(json.dumps({"setup": True}))
        return
    state = json.loads(path.read_text(encoding="utf-8"))
    if mode == "audit":
        cid = int(sys.argv[3])
        with get_db_session() as session:
            conv = session.query(ConversationRecord).filter_by(conversation_id=cid, created_by=state["actor"]).one()
            assert cid not in state["original_conversations"]
            messages = records(session, ConversationMessage, ConversationMessage.conversation_id == cid)
            assert any(state["marker"] in (r["message_content"] or "") for r in messages if r["message_role"] == "user")
            units = records(session, ConversationMessageUnit, ConversationMessageUnit.conversation_id == cid)
            files = {}
            for unit in units:
                if unit["unit_type"] in {"skill_body", "file_content"}:
                    event = json.loads(unit["unit_content"])
                    name = "SKILL.md" if unit["unit_type"] == "skill_body" else event["path"]
                    files[name] = files.get(name, "") + event["content"]
            print(json.dumps({"files": files, "messages_hash": digest(messages), "units_hash": digest(units),
                              "mode": (conv.workbench_config or {}).get("mode")}))
        return
    assert mode == "cleanup"
    with get_db_session() as session:
        assert original(session, state) == state["original_hashes"], "Pre-existing history changed"
        owned = [r.conversation_id for r in session.query(ConversationRecord).filter_by(created_by=state["actor"], delete_flag="N")
                 if r.conversation_id not in state["original_conversations"] and session.query(ConversationMessage).filter(
                     ConversationMessage.conversation_id == r.conversation_id,
                     ConversationMessage.message_content.contains(state["marker"])).first()]
        skills = session.query(SkillInfo).filter_by(skill_name=state["name"], tenant_id=state["tenant"],
                                                   created_by=state["actor"], delete_flag="N").all()
        assert len(skills) <= 1
    headers = {"Authorization": "Bearer " + state["access_token"]}
    with httpx.Client(headers=headers, trust_env=False, timeout=30) as client:
        for cid in owned:
            assert client.delete(f"http://nexent-runtime:5014/conversation/{cid}").status_code == 200
        for skill in skills:
            assert client.delete(f"http://nexent-config:5010/skills/{state['name']}").status_code == 200
    path.unlink()
    print(json.dumps({"cleanup": True, "original_history_unchanged": True,
                      "owned_conversations": len(owned), "owned_skills": len(skills)}))


if __name__ == "__main__":
    main()
